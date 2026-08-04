"""Green-screen person cutouts → RGBA PNG for Aria digital human layer."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
import numpy as np


def key_green(src: Path, dst: Path, thr: float = 40.0) -> None:
    im = Image.open(src).convert("RGBA")
    arr = np.array(im).astype(np.float32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    a = arr[:, :, 3].copy()
    mask = (g > 85) & (g > r + thr) & (g > b + thr)
    mask |= (g > 160) & (r < 130) & (b < 130)
    a[mask] = 0
    near = (g > 60) & (g > r + 20) & (g > b + 20) & (~mask)
    a[near] = np.minimum(a[near], 50)
    arr[:, :, 3] = a
    Image.fromarray(arr.astype(np.uint8), "RGBA").save(dst, optimize=True)
    print(f"wrote {dst} transparent={int((a == 0).sum())}")


def main() -> int:
    base = Path(sys.argv[1] if len(sys.argv) > 1 else "public/aria/dh")
    pairs = [
        ("person_play_src.jpg", "person_play.png"),
        ("person_talk_src.jpg", "person_talk.png"),
    ]
    # also accept already-named pngs as input
    for src_name, dst_name in pairs:
        src = base / src_name
        if not src.exists():
            # try green jpg next to dst
            alt = base / dst_name.replace(".png", "_green.jpg")
            src = alt if alt.exists() else src
        if src.exists():
            key_green(src, base / dst_name)
        else:
            print("skip missing", src)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
