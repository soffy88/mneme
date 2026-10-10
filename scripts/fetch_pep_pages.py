#!/usr/bin/env python3
"""scripts/fetch_pep_pages.py — 拉取人教社电子教材页图（FreePEP 同款方式）。

数据源：`siknet/FreePEP`（MIT）的 `pep_catalog.json` 里的 PEP 电子书条目，
实际内容来自 `book.pep.com.cn/<book_id>/files/mobile/<page>.jpg`。

⚠️ **这些是 300 DPI 位图，零文本层**（实测）。这正是 `scripts/scan_textbooks.py`
里 `LARGE_THRESHOLD_MB` 想提前识别的「扫描件」，只不过这里是逐页 JPEG。
所以入库时 `textbook_files.has_text_layer` 必须是 **false**，语料靠 OCR 得到。

**必须带 Referer**，否则 403（`denied by Referer ACL`）—— FreePEP 的
`pep_crawler.py` 顶部注释记的就是这件事。

页图缓存到 `data/external/pep_pages/<book_id>/p<page>.jpg`，已存在则跳过，
所以重跑不会重复下载。OCR 结果另存 `.txt`（每行一个 OCR box），由
`ocr_pep_pages.py` 消费。

    python scripts/fetch_pep_pages.py                 # 3 本初中英语，各 40 页
    python scripts/fetch_pep_pages.py --pages 60
    python scripts/fetch_pep_pages.py --book 1312001102241 --pages 200
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE_DIR = _REPO_ROOT / "data" / "external" / "pep_pages"
CATALOG_URL = (
    "https://raw.githubusercontent.com/siknet/FreePEP/main/pep_catalog.json"
)
PAGE_URL = "https://book.pep.com.cn/{book_id}/files/mobile/{page}.jpg"
# FreePEP pep_crawler.py 里用的同一组标头。少了 Referer 就是 403。
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Referer": "https://jc.pep.com.cn/",
}

# 人教社**常规版**（非盲校/低视力）英语教材。catalog 里英语共 58 条，剔掉
# `xd` 含「盲校」/ 标题含「低视力」的 26 条后剩 **32 本**，这里取对核心词表
# （中考/高考 K12）真正相关的 13 本：初中 6 + 高中 7。
#
# 为什么不全要 32 本：小学 8 本是「三年级起点」和「精通」两套平行教材 + 一年
# 起点第三套，同一册次有 2–3 个版本，混进语料会让同一句话重复出现且来源不唯一。
# 先要初中/高中，够不够看实测覆盖率再决定要不要加小学。
#
# book_id → (slug, 册次标签, PEP 教材 id)
PEP_JUNIOR_ENGLISH: dict[str, tuple[str, str]] = {
    "1312001101241": ("g7a", "七年级上册"),
    "1312001102241": ("g7b", "七年级下册"),
    "1312001201251": ("g8a", "八年级上册"),
    "1312001202251": ("g8b", "八年级下册"),
    "1312001301261": ("g9a", "九年级上册"),
    "1312001303141": ("g9all", "九年级全一册"),
    "1412001121191": ("h1", "必修第一册"),
    "1412001122191": ("h2", "必修第二册"),
    "1412001123191": ("h3", "必修第三册"),
    "1412001127191": ("hs1", "选择性必修第一册"),
    "1412001128201": ("hs2", "选择性必修第二册"),
    "1412001129201": ("hs3", "选择性必修第三册"),
    "1412001130201": ("hs4", "选择性必修第四册"),
}


def load_catalog() -> list[dict]:
    req = urllib.request.Request(CATALOG_URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_page(book_id: str, page: int, dest: Path, *, retries: int = 3) -> bool:
    """取一页图。**已存在即跳过**（幂等）。返回是否成功落盘。"""
    if dest.exists() and dest.stat().st_size > 10_000:
        return True
    url = PAGE_URL.format(book_id=book_id, page=page)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = resp.read()
            # 404.html 会被当成 200 返回（FreePEP 注释提到过），按大小兜底
            if len(data) < 10_000:
                break
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return True
        except (urllib.error.URLError, OSError, TimeoutError):
            if attempt == retries - 1:
                break
            time.sleep(1.5 * (attempt + 1))
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="拉取人教社英语教材页图")
    ap.add_argument("--book", default="", help="只拉这一本（book_id）")
    ap.add_argument("--pages", type=int, default=40, help="每本取多少页（1 起）")
    ap.add_argument("--start", type=int, default=1, help="起始页")
    args = ap.parse_args()

    books = (
        {args.book: ("", "")} if args.book else PEP_JUNIOR_ENGLISH
    )

    for book_id, (slug, label) in books.items():
        outdir = PAGE_DIR / (slug or book_id)
        got = miss = 0
        for page in range(args.start, args.start + args.pages):
            dest = outdir / f"p{page}.jpg"
            if fetch_page(book_id, page, dest):
                got += 1
            else:
                miss += 1
                # 连续 3 页取不到 = 到书尾了，提前收手，不空转
                if miss >= 3:
                    print(f"  {book_id}: 连续 3 页 404，判定到书尾，停止", file=sys.stderr)
                    break
        print(f"{book_id} ({label or slug}): 取到 {got} 页，失败 {miss} 页 → {outdir}")


if __name__ == "__main__":
    main()