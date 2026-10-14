"""把评测语料里的一部分题渲染成“像手机拍的”图片（不同字体/字号/旋转/模糊/噪点/JPEG 压缩/竖式分数），
写 tests/eval/ask_corpus/images/*.jpg + manifest.jsonl。确定性（固定随机种子）。

用法（api 镜像里有 Pillow；字体从宿主挂进来）：
    docker run --rm -v $PWD:/app -v /usr/share/fonts:/usr/share/fonts:ro -w /app --entrypoint python \
        mneme-api:latest tests/eval/render_ask_images.py --n 45
"""

from __future__ import annotations

import argparse
import io
import json
import random
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests/eval/ask_corpus/problems.jsonl"
OUT = ROOT / "tests/eval/ask_corpus/images"

FONTS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
]


def _fonts() -> list[str]:
    return [f for f in FONTS if Path(f).exists()]


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) > width:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def _render(text: str, rng: random.Random, stacked: bool) -> bytes:
    fonts = _fonts()
    fpath = rng.choice(fonts)
    size = rng.choice([30, 34, 38, 42])
    font = ImageFont.truetype(fpath, size)
    W = rng.choice([900, 1000, 1100])
    bg = tuple(rng.randint(225, 252) for _ in range(3))
    img = Image.new("RGB", (W, 1400), bg)
    d = ImageDraw.Draw(img)
    x0, y = 50, 60
    ink = tuple(rng.randint(0, 50) for _ in range(3))
    if stacked and re.search(r"\d+/\d+", text):
        # 竖式分数：把 a/b 画成上下两行（OCR 常见难点）
        x = x0
        for tok in re.split(r"(\d+/\d+)", text):
            if not tok:
                continue
            m = re.fullmatch(r"(\d+)/(\d+)", tok)
            if m:
                small = ImageFont.truetype(fpath, int(size * 0.8))
                a, b = m.groups()
                wa, wb = d.textlength(a, font=small), d.textlength(b, font=small)
                w = max(wa, wb) + 8
                if x + w > W - 50:
                    x, y = x0, y + int(size * 2.4)
                d.text((x + (w - wa) / 2, y - size * 0.55), a, font=small, fill=ink)
                d.line((x, y + size * 0.45, x + w, y + size * 0.45), fill=ink, width=2)
                d.text((x + (w - wb) / 2, y + size * 0.5), b, font=small, fill=ink)
                x += w + 4
            else:
                for ch in tok:
                    cw = d.textlength(ch, font=font)
                    if x + cw > W - 50:
                        x, y = x0, y + int(size * 2.4)
                    d.text((x, y), ch, font=font, fill=ink)
                    x += cw
        y += int(size * 2.4)
    else:
        for line in _wrap(text, font, W - 100, d):
            d.text((x0, y), line, font=font, fill=ink)
            y += int(size * 1.6)
    img = img.crop((0, 0, W, min(1400, y + 60)))
    # 光照不均
    grad = Image.linear_gradient("L").resize(img.size).point(lambda v: int(v * rng.uniform(0.05, 0.25)))
    img = Image.composite(Image.new("RGB", img.size, (200, 200, 190)), img, grad)
    img = img.rotate(rng.uniform(-4, 4), expand=True, fillcolor=bg, resample=Image.BICUBIC)
    if rng.random() < 0.7:
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 1.3)))
    # 噪点
    px = img.load()
    for _ in range(img.size[0] * img.size[1] // 60):
        xx, yy = rng.randrange(img.size[0]), rng.randrange(img.size[1])
        v = rng.randint(120, 255)
        px[xx, yy] = (v, v, v)
    if rng.random() < 0.5:
        sc = rng.uniform(0.6, 0.85)
        img = img.resize((int(img.size[0] * sc), int(img.size[1] * sc)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=rng.randint(55, 85))
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=45)
    ap.add_argument("--seed", type=int, default=20261014)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    probs = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_type: dict[str, list[dict]] = {}
    for p in probs:
        by_type.setdefault(p["type"], []).append(p)
    picked: list[dict] = []
    types = sorted(by_type)
    i = 0
    while len(picked) < args.n and any(by_type.values()):
        t = types[i % len(types)]
        if by_type[t]:
            picked.append(by_type[t].pop(rng.randrange(len(by_type[t]))))
        i += 1
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for k, p in enumerate(picked):
        stacked = p["type"] in ("frac", "frac_eq", "simplify_frac") and rng.random() < 0.5
        data = _render(p["text"], rng, stacked)
        name = f"{k:03d}_{p['id']}.jpg"
        (OUT / name).write_bytes(data)
        rows.append({"file": name, "problem_id": p["id"], "type": p["type"], "stacked_fraction": stacked})
    (OUT / "manifest.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    print(f"rendered {len(rows)} images into {OUT}")


if __name__ == "__main__":
    main()
