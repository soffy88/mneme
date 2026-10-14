// ImagePrep —— 上传前的客户端图片预处理（在 app/ask/page.tsx 的 pickFile 里调）。
//
// 为什么在客户端做：
//   1. 手机直出的 JPEG 动辄 3-8MB / 4000px，上传慢、服务端 OCR/存储都浪费；
//   2. 竖拍照片带 EXIF orientation：不解开服务端看到的就是横的，OCR 直接崩；
//   3. 裁剪放在编码前，一次 canvas 完成。
//
// 只用浏览器原生能力：createImageBitmap({imageOrientation:"from-image"}) 自动应用 EXIF
// （Safari 16.4+/Chrome 新版都有）；老浏览器回落 <img> + 手写 EXIF orientation 解析。

export interface PrepOptions {
  /** 长边上限，默认 1600（题库/OCR 足够，服务端也是按 1600 训练的）。 */
  maxSide?: number;
  /** JPEG 质量，默认 0.8。 */
  quality?: number;
  /** 裁剪框（源图像素坐标，会 clamp）。不给 = 整张。 */
  crop?: { x: number; y: number; width: number; height: number } | null;
  /** 额外顺时针旋转（度，0/90/180/360）：给「转错了」的学生手动补救。 */
  rotateDeg?: number;
}

export interface PrepResult {
  blob: Blob;
  width: number;
  height: number;
}

export const PREP_DEFAULTS = { maxSide: 1600, quality: 0.8 } as const;

/** 读 JPEG/PNG 的 EXIF orientation（1..8）。非 JPEG 或无 EXIF → 1。 */
export function readExifOrientation(buffer: ArrayBuffer): number {
  const view = new DataView(buffer);
  if (view.byteLength < 4 || view.getUint16(0, false) !== 0xffd8) return 1; // 不是 JPEG
  let offset = 2;
  while (offset + 4 <= view.byteLength) {
    if (view.getUint8(offset) !== 0xff) {
      offset += 1;
      continue;
    }
    const marker = view.getUint8(offset + 1);
    //  standalone markers（无长度字段）
    if (marker === 0xd8 || marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) {
      offset += 2;
      continue;
    }
    if (marker === 0xda || marker === 0xd9) break; // SOS/EOI：后面是压缩数据，不再找
    const len = view.getUint16(offset + 2, false);
    if (marker === 0xe1) {
      // APP1：找 "Exif\0\0" 头
      if (offset + 10 <= view.byteLength) {
        const tag = String.fromCharCode(
          view.getUint8(offset + 4),
          view.getUint8(offset + 5),
          view.getUint8(offset + 6),
          view.getUint8(offset + 7)
        );
        if (tag === "Exif") {
          const tiff = offset + 10;
          const little = view.getUint16(tiff, false) === 0x4949;
          const magic = view.getUint16(tiff + 2, little);
          if (magic !== 0x002a) return 1;
          const ifd = tiff + view.getUint32(tiff + 4, little);
          const entries = view.getUint16(ifd, little);
          for (let i = 0; i < entries; i++) {
            const entry = ifd + 2 + i * 12;
            if (entry + 12 > view.byteLength) break;
            if (view.getUint16(entry, little) === 0x0112) {
              const v = view.getUint16(entry + 8, little);
              return v >= 1 && v <= 8 ? v : 1;
            }
          }
        }
      }
      return 1;
    }
    offset += 2 + len;
  }
  return 1;
}

/** orientation(1..8) → 需要顺时针补转的度数，让最终画面是正的。 */
export function orientationToRotation(orientation: number): number {
  switch (orientation) {
    case 3:
      return 180;
    case 6:
      return 90;
    case 8:
      return 270;
    default:
      return 0;
  }
}

/** 解码成 {bitmap, orientation}：EXIF 已应用（能）或留给调用方补转（不能）。 */
async function decode(
  file: Blob
): Promise<{ source: ImageBitmap | HTMLImageElement; orientation: number; revoke?: () => void }> {
  if (typeof createImageBitmap === "function") {
    try {
      const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
      return { source: bmp, orientation: 1, revoke: () => bmp.close() };
    } catch {
      /* 老浏览器/解码失败 → 走 <img> 路径 */
    }
  }
  const url = URL.createObjectURL(file);
  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const el = new Image();
    el.onload = () => resolve(el);
    el.onerror = () => reject(new Error("图片读取失败，换一张试试"));
    el.src = url;
  });
  let orientation = 1;
  try {
    orientation = readExifOrientation(await file.arrayBuffer());
  } catch {
    orientation = 1;
  }
  return { source: img, orientation, revoke: () => URL.revokeObjectURL(url) };
}

function dimsOf(source: ImageBitmap | HTMLImageElement): { w: number; h: number } {
  return source instanceof ImageBitmap
    ? { w: source.width, h: source.height }
    : { w: source.naturalWidth, h: source.naturalHeight };
}

/**
 * 解码 → 裁剪 → 缩放（长边 ≤ maxSide）→ JPEG 编码。
 * 抛中文错误（调用方直接显示给学生）。
 */
export async function prepImage(file: Blob, opts: PrepOptions = {}): Promise<PrepResult> {
  const maxSide = Math.max(64, opts.maxSide ?? PREP_DEFAULTS.maxSide);
  const quality = Math.min(1, Math.max(0.3, opts.quality ?? PREP_DEFAULTS.quality));
  const extra = ((opts.rotateDeg ?? 0) % 360 + 360) % 360;

  const { source, orientation, revoke } = await decode(file);
  try {
    const src = dimsOf(source);
    if (!src.w || !src.h) throw new Error("图片读取失败，换一张试试");

    // orientation 1..3 不改变宽高语义；4..8 被镜像/旋转 90 度（我们只补旋转，镜像罕见，
    // createImageBitmap 的 from-image 已处理多数情形；老 <img> 路径下 5-8 走补转）。
    const rot = ((orientationToRotation(orientation) + extra) % 360 + 360) % 360;
    const swap = rot % 180 !== 0;
    const fullW = swap ? src.h : src.w;
    const fullH = swap ? src.w : src.h;

    const crop = clampCrop(opts.crop, fullW, fullH);

    const scale = Math.min(1, maxSide / Math.max(crop.width, crop.height));
    const outW = Math.max(1, Math.round(crop.width * scale));
    const outH = Math.max(1, Math.round(crop.height * scale));

    const canvas = document.createElement("canvas");
    canvas.width = outW;
    canvas.height = outH;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("这个浏览器处理不了图片");
    ctx.imageSmoothingQuality = "high";

    // 把"裁剪 → 旋转 → 缩放"合成一个矩阵：先平移到输出中心，旋转，再按缩放比把裁剪区画进去。
    ctx.translate(outW / 2, outH / 2);
    ctx.rotate((rot * Math.PI) / 180);
    ctx.drawImage(
      source,
      crop.x,
      crop.y,
      crop.width,
      crop.height,
      (-crop.width * scale) / 2,
      (-crop.height * scale) / 2,
      crop.width * scale,
      crop.height * scale
    );

    const blob = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob((b) => resolve(b), "image/jpeg", quality)
    );
    if (!blob) throw new Error("图片处理失败，换一张试试");
    return { blob, width: outW, height: outH };
  } finally {
    revoke?.();
  }
}

/** 把用户拖出来的裁剪框限制在图内，且至少 20px，避免零面积的 canvas。 */
export function clampCrop(
  crop: { x: number; y: number; width: number; height: number } | null | undefined,
  w: number,
  h: number
): { x: number; y: number; width: number; height: number } {
  const MIN = 20;
  if (!crop || crop.width < MIN || crop.height < MIN) {
    return { x: 0, y: 0, width: w, height: h };
  }
  const width = Math.min(w, crop.width);
  const height = Math.min(h, crop.height);
  const x = Math.min(Math.max(0, crop.x), w - width);
  const y = Math.min(Math.max(0, crop.y), h - height);
  return { x, y, width, height };
}
