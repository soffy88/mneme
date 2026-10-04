"""scripts/parse_opd_topic_anchors.py — 从《牛津图解词典》第三版抽「词 → 主题面板」

## 为什么抽这个

20 词人工审查发现的问题 #3：**记忆画面可能与语境句不是同一个义项**。
`blind` 的 NCE 真实句是动词义（`the gleams blind and dazzle`），生成的画面却是
名词义（百叶窗）。根因是引擎只知道词，不知道这个词**被画成什么**。

图解词典正好给这个确定性：它按主题图面板组织，每个词出现在一个**具体画面**里
（`A Kitchen: 1. cabinet 2. shelf 3. sink …`）。于是「cabinet 的画面义 = 厨房里的
橱柜」是**可确定读取**的，不需要模型去猜。

## 只抽词 + 主题标签（最小版权面）

用户已授权入库，但本脚本**只**输出 `(word, topic_label)`：

- **不**抽释义文本（那是词典正文）
- **不**抽插图
- 主题标签是**版面结构信息**（这一页在讲什么话题），不是内容表达

这样把版权面压到最小，同时拿到义项锚定这个真正需要的收益。

## 版面噪声（实测）

文本层有垃圾：`poge1t`（页码 OCR 错）、`IITI`、`illllimmi`、以及混入的例句
（`Survey your class. Record the responses.`）。所以：

- 只认 `N. word` 这种**编号词条**格式；
- 例句没有编号，会被自然排除；
- 页码/页眉这类噪声不在编号格式里。

源文件：`data/external/vocab_src/OPD3_en.pdf`（**不入库**，`.gitignore` 已排除
`data/external/` 与 `*.pdf`；175MB 二进制不进 git）。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

# `12. dishwasher` —— 编号 + 小写词/短语
_ENTRY_RE = re.compile(r"(?<![\d.])(\d{1,2})\.\s+([a-z][A-Za-z][A-Za-z\- ,']{0,26})")
# 页首的页码噪声（`poge1t`、`page1t`、纯数字行）
_PAGE_NOISE_RE = re.compile(r"^\s*(poge|page|pagc)?\s*\d{0,3}\s*$", re.I)
# 主题面板标题：独占一行、Title-ish、2~5 个词，且不是编号行
_TOPIC_RE = re.compile(r"^[A-Z][A-Za-z'’\-]*(?:\s+[A-Za-z'’\-]+){0,4}$")

# 明显不是词条的英文句子片段（含句号或典型动词开头）
_SENTENCEISH = re.compile(
    r"\b(survey|record|report|ask|answer|write|read|look|listen|talk|choose|"
    r"discuss|describe|explain|practice|review|learn|teach|give|take|make)\b",
    re.I,
)

MAX_PAGE_CHARS = 4000


def extract_page_entries(page_text: str) -> list[str]:
    """从一页文本里抽编号词条。纯函数，可单测。"""
    out: list[str] = []
    for line in page_text.split("\n"):
        raw = line.strip()
        if not raw or _PAGE_NOISE_RE.match(raw):
            continue
        for m in _ENTRY_RE.finditer(raw):
            phrase = " ".join(m.group(2).split()).strip(" ,'")
            if not phrase or _SENTENCEISH.search(phrase):
                continue
            # 词条不应含句号（那说明抓到的是句子）
            if "." in phrase:
                continue
            out.append(phrase)
    return out


def extract_topic_label(page_text: str) -> str | None:
    """抽本页的主题面板标题。取**第一个**像标题的独占行。"""
    for line in page_text.split("\n")[:12]:
        raw = line.strip()
        if not raw or _PAGE_NOISE_RE.match(raw):
            continue
        if _ENTRY_RE.match(raw):
            continue
        if _TOPIC_RE.match(raw) and " " in raw:
            return raw
    return None


def parse_document(pdf_path: Path) -> list[dict[str, str]]:
    """整本 → ``[{"word", "topic"}]``。词按首次出现去重。"""
    import pymupdf

    seen: set[str] = set()
    rows: list[dict[str, str]] = []
    doc = pymupdf.open(pdf_path)
    for page in doc:
        text = page.get_text()[:MAX_PAGE_CHARS]
        topic = extract_topic_label(text)
        if not topic:
            continue
        for word in extract_page_entries(text):
            key = word.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append({"word": key, "topic": topic})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pdf",
        default="data/external/vocab_src/OPD3_en.pdf",
        help="OPD 第三版英文版 PDF（不入库，需自行从 gdrive 取得）",
    )
    parser.add_argument(
        "--out",
        default="data/external/vocab_src/opd_topic_anchors.json",
        help="抽取结果 JSON（中间产物，不入库）",
    )
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    pdf = Path(args.pdf)
    if not pdf.exists():
        raise SystemExit(
            f"找不到 {pdf}。该文件不入库（data/external/ 与 *.pdf 已在 .gitignore），"
            "需从 gdrive:英语优先/【OPD牛津图解词典】第3版…/ 自行取得。"
        )
    rows = parse_document(pdf)
    if args.limit:
        rows = rows[: args.limit]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    topics = sorted({r["topic"] for r in rows})
    print(f"抽出词条 = {len(rows)}（去重后）")
    print(f"主题面板 = {len(topics)}")
    print(f"写入 {out}")
    print("\n主题面板样例:")
    for t in topics[:12]:
        n = sum(1 for r in rows if r["topic"] == t)
        print(f"  {t}  ({n} 词)")


if __name__ == "__main__":
    main()