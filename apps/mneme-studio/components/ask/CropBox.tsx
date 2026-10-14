"use client";

// CropBox —— 拍完照先裁一下（桌面杂物、同桌的胳膊、半张上一题）。
// pointer events（统一鼠标/触摸/笔）+ setPointerCapture，手机上拖动不会断。
// 默认 = 整张；四个角 + 四条边都能拖；框不能出图、不能小于 40px。

import { useCallback, useEffect, useRef, useState } from "react";
import { OButton } from "@helios/blocks";

export interface CropRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

type Handle = "nw" | "ne" | "sw" | "se" | "n" | "s" | "w" | "e" | "move";

const MIN_SIZE = 40;

interface Props {
  /** 待裁图片（object URL）。 */
  src: string;
  /** 图片原始像素尺寸（用于换算成源图坐标输出）。 */
  naturalWidth: number;
  naturalHeight: number;
  onCancel?: () => void;
  onConfirm: (crop: CropRect | null) => void;
}

/** 把元素坐标 → 图片内 0..1 归一化，并 clamp。 */
function toNorm(rect: DOMRect, clientX: number, clientY: number) {
  return {
    x: Math.min(1, Math.max(0, (clientX - rect.left) / rect.width)),
    y: Math.min(1, Math.max(0, (clientY - rect.top) / rect.height)),
  };
}

export function CropBox({ src, naturalWidth, naturalHeight, onCancel, onConfirm }: Props) {
  const boxRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ handle: Handle; startX: number; startY: number; start: CropRect } | null>(
    null
  );
  const full: CropRect = { x: 0, y: 0, width: 1, height: 1 };
  const [crop, setCrop] = useState<CropRect>(full);

  const onPointerDown = useCallback(
    (handle: Handle) => (e: React.PointerEvent) => {
      if (!boxRef.current) return;
      e.preventDefault();
      (e.target as Element).setPointerCapture?.(e.pointerId);
      dragRef.current = {
        handle,
        startX: e.clientX,
        startY: e.clientY,
        start: crop,
      };
    },
    [crop]
  );

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    const drag = dragRef.current;
    const box = boxRef.current;
    if (!drag || !box) return;
    e.preventDefault();
    const rect = box.getBoundingClientRect();
    const dx = (e.clientX - drag.startX) / rect.width;
    const dy = (e.clientY - drag.startY) / rect.height;
    const s = drag.start;
    let { x, y, width, height } = s;

    if (drag.handle === "move") {
      x = Math.min(Math.max(0, s.x + dx), 1 - s.width);
      y = Math.min(Math.max(0, s.y + dy), 1 - s.height);
    } else {
      if (drag.handle.includes("w")) {
        const nx = Math.min(Math.max(0, s.x + dx), s.x + s.width - MIN_SIZE / rect.width);
        width = s.width + (s.x - nx);
        x = nx;
      }
      if (drag.handle.includes("e")) {
        width = Math.min(1 - s.x, Math.max(MIN_SIZE / rect.width, s.width + dx));
      }
      if (drag.handle.includes("n")) {
        const ny = Math.min(Math.max(0, s.y + dy), s.y + s.height - MIN_SIZE / rect.height);
        height = s.height + (s.y - ny);
        y = ny;
      }
      if (drag.handle.includes("s")) {
        height = Math.min(1 - s.y, Math.max(MIN_SIZE / rect.height, s.height + dy));
      }
    }
    setCrop({ x, y, width, height });
  }, []);

  const endDrag = useCallback(() => {
    dragRef.current = null;
  }, []);

  useEffect(() => {
    // 拖动中松手/取消：指针可能落在 capture 元素之外。
    window.addEventListener("pointerup", endDrag);
    window.addEventListener("pointercancel", endDrag);
    return () => {
      window.removeEventListener("pointerup", endDrag);
      window.removeEventListener("pointercancel", endDrag);
    };
  }, [endDrag]);

  const confirm = () => {
    const isFull =
      crop.width > 0.995 && crop.height > 0.995 && crop.x < 0.005 && crop.y < 0.005;
    onConfirm(
      isFull
        ? null
        : {
            x: Math.round(crop.x * naturalWidth),
            y: Math.round(crop.y * naturalHeight),
            width: Math.round(crop.width * naturalWidth),
            height: Math.round(crop.height * naturalHeight),
          }
    );
  };

  // 角/边把手：绝对定位于裁剪框，热区 44px（手机可点）。
  const knob =
    "absolute h-11 w-11 -m-1 touch-none select-none" +
    " before:absolute before:bg-[var(--primary)] before:content-['']";
  const corners: Record<string, string> = {
    nw: "top-0 left-0 cursor-nwse-resize",
    ne: "top-0 right-0 cursor-nesw-resize",
    sw: "bottom-0 left-0 cursor-nesw-resize",
    se: "bottom-0 right-0 cursor-nwse-resize",
  };

  return (
    <div className="space-y-3" data-testid="ask-crop">
      <div
        ref={boxRef}
        className="relative touch-none overflow-hidden rounded-xl border bg-black/5"
        onPointerMove={onPointerMove}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt="待裁剪的题目" className="block max-h-[60vh] w-full object-contain" />

        {/* 遮罩：裁剪框外压暗 */}
        <div
          className="pointer-events-none absolute inset-0 bg-black/50"
          style={{
            clipPath: `polygon(0% 0%, 0% 100%, ${crop.x * 100}% 100%, ${crop.x * 100}% ${
              crop.y * 100
            }%, ${(crop.x + crop.width) * 100}% ${crop.y * 100}%, ${
              (crop.x + crop.width) * 100
            }% ${(crop.y + crop.height) * 100}%, ${crop.x * 100}% ${(crop.y + crop.height) * 100}%, ${
              crop.x * 100
            }% 100%, 100% 100%, 100% 0%)`,
          }}
        />

        <div
          className="absolute border-2 border-[var(--primary)]"
          style={{
            left: `${crop.x * 100}%`,
            top: `${crop.y * 100}%`,
            width: `${crop.width * 100}%`,
            height: `${crop.height * 100}%`,
          }}
        >
          {/* 整体移动 */}
          <div
            className="absolute inset-0 cursor-move touch-none"
            onPointerDown={onPointerDown("move")}
          />
          {/* 四角 */}
          {(["nw", "ne", "sw", "se"] as const).map((h) => (
            <div
              key={h}
              role="presentation"
              className={`${knob} ${corners[h]}`}
              onPointerDown={onPointerDown(h)}
            />
          ))}
        </div>
      </div>

      <div className="flex gap-2">
        {onCancel && (
          <OButton variant="ghost" className="min-h-[44px]" onClick={onCancel}>
            换一张
          </OButton>
        )}
        <OButton
          variant="outline"
          className="min-h-[44px]"
          data-testid="ask-crop-full"
          onClick={() => setCrop(full)}
        >
          整张
        </OButton>
        <OButton className="flex-1 min-h-[44px]" data-testid="ask-crop-confirm" onClick={confirm}>
          确定
        </OButton>
      </div>
    </div>
  );
}
