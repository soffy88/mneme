"use client";

// CameraButton —— 「拍题目」入口组。手机-first：主按钮大、可盲点，
// 三个来源（相机 / 相册 / 打字）并列，避免学生找不到"我要打字"的入口。

import { useCallback, useRef } from "react";
import { OButton } from "@helios/blocks";

export interface CameraButtonProps {
  /** 选到文件（拍照或相册）后回调；null = 用户取消。 */
  onPick: (file: File | null) => void;
  /** 点「打字输入」。 */
  onType: () => void;
  busy?: boolean;
}

export function CameraButton({ onPick, onType, busy = false }: CameraButtonProps) {
  const cameraRef = useRef<HTMLInputElement>(null);
  const albumRef = useRef<HTMLInputElement>(null);

  const handle = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onPick(e.target.files?.[0] ?? null);
      // 同一文件再选一次也要触发 change（否则连续拍同一张没反应）。
      e.target.value = "";
    },
    [onPick]
  );

  return (
    <div className="space-y-3">
      <OButton
        size="lg"
        className="h-24 w-full flex-col gap-1 text-lg"
        data-testid="ask-camera"
        loading={busy}
        disabled={busy}
        onClick={() => cameraRef.current?.click()}
      >
        <span className="text-3xl" aria-hidden>
          📷
        </span>
        拍题目
      </OButton>

      <div className="grid grid-cols-2 gap-3">
        <OButton
          variant="outline"
          className="h-16 flex-col gap-0.5 text-base"
          data-testid="ask-album"
          disabled={busy}
          onClick={() => albumRef.current?.click()}
        >
          <span className="text-xl" aria-hidden>
            🖼️
          </span>
          从相册选
        </OButton>
        <OButton
          variant="outline"
          className="h-16 flex-col gap-0.5 text-base"
          data-testid="ask-type"
          disabled={busy}
          onClick={onType}
        >
          <span className="text-xl" aria-hidden>
            ⌨️
          </span>
          打字输入
        </OButton>
      </div>

      {/* capture="environment" 让手机直接开后置摄像头；相册不给 capture。 */}
      <input
        ref={cameraRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={handle}
      />
      <input
        ref={albumRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={handle}
      />
    </div>
  );
}
