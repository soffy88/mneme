#!/usr/bin/env node
// 生成 PWA 图标（善学记 Mneme）—— 纯 JS PNG 编码器，零依赖（node_modules 里没有 sharp）。
// 用 `node scripts/gen-icons.mjs` 重新生成；产物：public/icon-{192,512}.png、
// public/icon-maskable-512.png、public/apple-touch-icon.png。
//
// 图案取产品意象：一枚"记忆书签"（圆角方块 + 折角 + 书脊点），配色与 mneme-friendly 主题一致。
// 纯色背景 + 圆角是 PWA 的安全选择：maskable 图标的 20% 安全区外才裁切，主体居中即可。

import { deflateSync } from "node:zlib";
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "..", "public");

const BG = [255, 255, 255]; // 主题 background_color 同色
const INK = [37, 48, 74]; // 深墨蓝（foreground）
const ACCENT = [232, 126, 60]; // 暖橙：书签折角/强调

// ── PNG 编码（RGBA8 + filter 0，浏览器/系统都认）────────────────────────────
function crc32(buf) {
  let c = ~0;
  for (let i = 0; i < buf.length; i++) {
    c ^= buf[i];
    for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1));
  }
  return ~c >>> 0;
}

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

function encodePng(width, height, rgba) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // color type RGBA
  const raw = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y++) {
    raw[y * (width * 4 + 1)] = 0; // filter: none
    rgba.copy(raw, y * (width * 4 + 1) + 1, y * width * 4, (y + 1) * width * 4);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

// ── 画布（单位化到 size，所有坐标用 0..1 表达）──────────────────────────────
function mix(a, b, t) {
  return a.map((v, i) => Math.round(v + (b[i] - v) * t));
}

/** 抗锯齿圆角矩形覆盖率：矩形外 1px 内的羽化。 */
function roundedRect(x, y, w, h, r, px, py) {
  const dx = Math.max(x + r - px, px - (x + w - r), 0);
  const dy = Math.max(y + r - py, py - (y + h - r), 0);
  if (dx <= 0 && dy <= 0) return 1; // 直边区
  const d = Math.hypot(dx, dy) - r;
  return d <= -0.5 ? 1 : d >= 0.5 ? 0 : 0.5 - d;
}

function render(size, { maskable }) {
  const buf = Buffer.alloc(size * size * 4);
  const S = (v) => v * size;
  // maskable 图标会被裁成圆形/圆角方：主体收进中心 80% 安全区（非 maskable 用满）。
  const k = maskable ? 0.72 : 0.92;
  const pad = (1 - k) / 2;
  const put = (i, rgb, a) => {
    buf[i] = rgb[0];
    buf[i + 1] = rgb[1];
    buf[i + 2] = rgb[2];
    buf[i + 3] = Math.round(255 * a);
  };

  for (let py = 0; py < size; py++) {
    for (let px = 0; px < size; px++) {
      const i = (py * size + px) * 4;
      const u = px / size;
      const v = py / size;
      // 底色（非 maskable 用整幅白；maskable 铺满，安全区外反正被裁）
      let rgb = BG;
      let a = 1;

      // 书签主体：上半圆角矩形 + 下半收窄成 V 缺口（ worn bookmark）
      const bx0 = pad + 0.16 * k;
      const bx1 = pad + 0.84 * k;
      const by0 = pad + 0.1 * k;
      const by1 = pad + 0.9 * k;
      const rr = 0.07 * k;
      const notchTop = by1 - 0.19 * k; // V 缺口起点
      const bodyH = notchTop - by0;
      const cover = roundedRect(S(bx0), S(by0), S(bx1 - bx0), S(bodyH), S(rr), px, py);
      const halfW = 0.3 * k;
      const cx = (bx0 + bx1) / 2;
      const tri =
        u >= cx - halfW && u <= cx + halfW && v >= notchTop && v <= by1
          ? Math.max(
              0,
              1 - Math.abs(u - cx) / halfW - (v - notchTop) / (by1 - notchTop)
            )
          : 0;
      const shape = Math.max(cover, tri);

      if (shape > 0) {
        // 竖向暖色渐变：墨蓝 → 偏亮的蓝
        const t = (v - by0) / (by1 - by0);
        rgb = mix(INK, [58, 84, 128], Math.max(0, Math.min(1, t)));
        a = shape;
      }

      // 折角高亮（书签右上角一道暖橙斜线）
      const fx0 = pad + 0.56 * k;
      const fx1 = pad + 0.84 * k;
      const fy0 = pad + 0.1 * k;
      const fy1 = pad + 0.36 * k;
      const inCorner =
        u >= fx0 && u <= fx1 && v >= fy0 && v <= fy1 && u + v <= fx0 + fy1 - 0.1 * k;
      const dEdge = Math.abs((u - (fx0 + fx1) / 2) - (v - (fy0 + fy1) / 2)) - 0.03 * k;
      if (inCorner && Math.abs(dEdge) < 0.014 * k) {
        rgb = ACCENT;
        a = 1;
      }

      // 记忆点（三颗白点：检索 / 间隔 / 交错）
      for (const cy of [0.3, 0.44, 0.58]) {
        const dx = cx - 0.1 * k;
        const d = Math.hypot(u - dx, v - (pad + cy * k));
        if (d < 0.036 * k) {
          rgb = BG;
          a = 1;
        }
      }

      put(i, rgb, a);
    }
  }
  return encodePng(size, size, buf);
}

mkdirSync(OUT, { recursive: true });
const files = [
  ["icon-192.png", render(192, { maskable: false })],
  ["icon-512.png", render(512, { maskable: false })],
  ["icon-maskable-512.png", render(512, { maskable: true })],
  ["apple-touch-icon.png", render(180, { maskable: false })],
];
for (const [name, data] of files) {
  writeFileSync(join(OUT, name), data);
  console.log(`wrote public/${name} (${data.length} bytes)`);
}
