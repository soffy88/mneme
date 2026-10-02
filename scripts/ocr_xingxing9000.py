"""象形9000 全套 6 册 PDF -> OCR 文本缓存。

PDF 是纯位图扫描（600 DPI CCITT G4，无文本层），所以只能 OCR。
输出按册分文件存 JSON 行，后续解析（scripts/parse_xingxing9000.py）与 OCR 解耦：
OCR 慢、解析快，解析规则迭代时不必重跑 OCR。

不写库。本脚本只负责把像素变成文本缓存。
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from pypdf import PdfReader

SRC = Path("/data/soffy/projects/mneme/data/external/vocab_src")
OUT = Path(os.environ.get("XIANGXING_OCR_DIR", "/tmp/opencode/ocr_cache"))
DPI = 200

VOLUMES = [
    "第一册  上[vxia.net].pdf",
    "第二册 上.pdf",
    "第二册  下.pdf",
    "第三册  上[vxia.net].pdf",
    "第三册  下.pdf",
]
MIN_CONF = 0.60  # 象形字块与页码噪声多，放宽到 0.6，解析阶段再按字段筛


def ocr_page(job: tuple[str, int]) -> dict:
    """渲染单页并 OCR。返回该页的文本块（含坐标与置信度）。"""
    pdf_rel, page_no = job
    pdf = SRC / pdf_rel
    out: dict = {"pdf": pdf_rel, "page": page_no, "lines": [], "low_conf": 0}
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(
            ["pdftoppm", "-png", "-r", str(DPI), "-f", str(page_no + 1),
             "-l", str(page_no + 1), str(pdf), f"{tmp}/p"],
            check=True, capture_output=True,
        )
        img = next(Path(tmp).glob("p-*.png"))
        from rapidocr_onnxruntime import RapidOCR

        res, _ = RapidOCR()(str(img))
    for box, txt, conf in res or []:
        try:
            c = float(conf)
        except (TypeError, ValueError):
            c = 0.0
        if c < MIN_CONF:
            out["low_conf"] += 1
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        out["lines"].append({
            "text": txt,
            "conf": round(c, 3),
            "x0": int(min(xs)), "x1": int(max(xs)),
            "y0": int(min(ys)), "y1": int(max(ys)),
        })
    out["lines"].sort(key=lambda r: (r["y0"], r["x0"]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="象形9000 PDF -> OCR 文本缓存")
    ap.add_argument("--only", nargs="*", metavar="PDF",
                    help="只处理指定册（文件名片段），缺省处理 VOLUMES 全部")
    ap.add_argument("--append", action="store_true",
                    help="追加到已有缓存而非覆盖，用于补跑单册")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    wanted = VOLUMES
    if args.only:
        wanted = [n for n in VOLUMES if any(k in n for k in args.only)]
        if not wanted:
            print(f"[stop] --only {args.only} 未匹配到任何册", flush=True)
            return 1
    jobs: list[tuple[str, int]] = []
    for name in wanted:
        if not (SRC / name).exists():
            print(f"[skip] 缺失 {name}", flush=True)
            continue
        n = len(PdfReader(str(SRC / name)).pages)
        print(f"[plan] {name}: {n} 页", flush=True)
        jobs.extend((name, i) for i in range(n))

    print(f"[run] 共 {len(jobs)} 页，DPI={DPI}，8 进程", flush=True)
    done = 0
    mode = "a" if args.append else "w"
    with ProcessPoolExecutor(max_workers=8) as ex, \
            (OUT / "ocr.jsonl").open(mode, encoding="utf-8") as fh:
        futs = {ex.submit(ocr_page, j): j for j in jobs}
        for fut in as_completed(futs):
            try:
                rec = fut.result()
            except Exception as exc:  # noqa: BLE001 — 单页失败不能拖垮整批
                print(f"[err] {futs[fut]}: {exc}", flush=True)
                continue
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            done += 1
            if done % 25 == 0:
                print(f"  {done}/{len(jobs)}", flush=True)
    print(f"[done] {done} 页 -> {OUT/'ocr.jsonl'}", flush=True)


if __name__ == "__main__":
    sys.exit(main())