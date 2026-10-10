#!/usr/bin/env python3
"""scripts/ocr_pep_pages.py — 对人教社英语教材页图跑 OCR，产出**过滤后**的句子。

输入：`data/external/pep_pages/<slug>/p<N>.jpg`（`fetch_pep_pages.py` 拉的 300 DPI
位图，零文本层）。输出：`<slug>/p<N>.txt`，每行一个 OCR box 文本（按版面顺序）。

用 RapidOCR —— 与 `scripts/ocr_xingxing9000.py` 同一个引擎（STATUS.md 实测
8.5s/页、置信度 0.85–0.94）。实测英语页 9.4s/页，识别质量可用
（`Don't be late for school. Arrive on time.` 干净可读）。

## 为什么 OCR 结果**不能直接当语料**

一本初中英语教材的页面上，混着三类东西：

1. **课文/对话正文** —— 这是我们要的；
2. **练习指令** —— `Tick the correct boxes.`、`Listen again.`、`Make up a
   conversation with a partner.`、`Read and match.`。这些是**题型说明**，
   不是语言材料，进 `context_evidence` 等于拿练习说明当例句；
3. **版面噪声** —— 单元标题 `1a`、页码、`录音` 提示、表格数字。

本脚本的职责是**只交出第 1 类**。判定用三类否决信号，全部是**拒绝**而非
清洗（沿用象形 9000 / COCA 词表那两次的口径）：

- `IMPERATIVE_TASK`：以题型动词开头的祈使句（`Tick`/`Listen`/`Read`/`Write`/
  `Match`/`Complete`/`Circle`/`Number`/`Think`/`Discuss`/`Role-play` …），
  或含 `Listen and` / `Read and` / `in pairs` / `your partner` 等题型短语；
- `HAS_CJK`：页面含中文（音标注释、译文、旁注）—— 我们只收纯英文正文句；
- `SHORT_OR_JUNK`：少于 4 词，或无句末标点，或全是数字/字母碎片。

**不确定就丢**：宁可少收，不可让题型说明混进语境层。丢弃量与原因全部计入
报告，由人判读。

    python scripts/ocr_pep_pages.py --limit 5          # 只跑 5 页，试口径
    python scripts/ocr_pep_pages.py                    # 全跑
    python scripts/ocr_pep_pages.py --jobs 8
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE_DIR = _REPO_ROOT / "data" / "external" / "pep_pages"
REPORT_DIR = _REPO_ROOT / "reports" / "vocab_memory_p0"

# 题型动词 → 练习指令。开头的祈使句几乎都是题型说明而非正文。
_TASK_VERBS = frozenset(
    {
        "tick", "listen", "read", "write", "match", "complete", "circle",
        "number", "think", "discuss", "role-play", "roleplay", "act", "look",
        "answer", "fill", "choose", "join", "mark", "draw", "colour", "color",
        "correct", "put", "ask", "imagine", "use", "make", "translate",
        # 补：实测漏网的题型动词。`Interview your classmates and tick…` 的首词
        # 是 `Interview`（不在表里）→ 整句当正文收了。`survey`/`report` 同理。
        "interview", "survey", "brainstorm", "predict", "guess", "survey",
        "report", "retell", "skim", "scan", "underline", "highlight",
        "describe", "report", "compare", "find", "check", "practise", "practice",
        "repeat", "say", "learn", "study", "review", "note", "add", "study",
        "work", "try", "help", "let", "spell", "pronounce", "record", "listen again",
    }
)
_TASK_PHRASES = (
    "in pairs",
    "your partner",
    "your teacher",
    "listening and reading",
    "listen and read",
    "read and write",
    "read and match",
    "work in pairs",
    "according to the recording",
    "the recording",
    "tick the",
    "choose the",
    "fill in the",
    "put the",
    "what does",
    "how many",
    "your school",
)
_CJK = re.compile(r"[\u4e00-\u9fff]")
# **存在性**判据（是否含拉丁字母），不是词计数 —— ``_ALPHA.search`` 用它。
_ALPHA = re.compile(r"[A-Za-z]")
# **词**计数必须用能一次匹配整词的模式。踩过的坑：用 ``[A-Za-z]`` 去数「词数」，
# `Why do you like?` 会数成 12（字母个数）而不是 4，于是 4 词的碎片压线通过。
_WORD = re.compile(r"[A-Za-z][A-Za-z']*")
_SENT_END = re.compile(r"[.!?][\"')\]]?$")
# 单句词数上限。与 `services/vocab_context._SENTENCE_MAX_LEN`（160 字符）同一
# 量级：超过就不是「一个用法」。
_MAX_SENT_WORDS = 28
# 词数下限。实测 4 词是分界：`Why do you like?`（4 词）是教材里真实出现的
# 句子，该留；`words.` / `A B C D.` 这类才是碎片。真正挡碎片的主力是
# `_MAX_MERGE_BOXES` 与 `_MIN_SCORE` 两个结构判据，不是这个词数。
_MIN_SENT_WORDS = 4

REJECT_IMPERATIVE_TASK = "IMPERATIVE_TASK"
REJECT_HAS_CJK = "HAS_CJK"
REJECT_SHORT_OR_JUNK = "SHORT_OR_JUNK"
REJECT_NOT_PROSE = "NOT_PROSE"
REJECT_LAYOUT_MERGE = "LAYOUT_MERGE"
REJECT_LOW_CONFIDENCE = "LOW_CONFIDENCE"

# 单句最多允许由几行 OCR 拼成。实测对话正文通常 1–3 行；跨 4 行以上基本都是
# 跨栏/跨块被并（`Every day, from Monday to Friday, Across the country, in many
# schools, Students like…` 是两栏并成一句）。
_MAX_MERGE_BOXES = 3
# 最低置信度。RapidOCR 实测英语正文 0.9+，而拼坏的区域明显更低。
# 0.80 与象形 9000 那次用的下限一致。
_MIN_SCORE = 0.80

# 版面噪声：OCR 在**每一页**都会吐出这几行（实测 100% 出现），它们不是正文。
# 逐条剔除，否则每一页都会被 HAS_CJK 否掉。
#
# OCR 对水印「人民教育出版社」有多种误读：实测见过 `人民龙育出版社`、
# `人民意育出版社`、`人民育出版社`。所以按**模式**认，不枚举字面量。
_WATERMARK = re.compile(r"^人民.{0,2}育?育?出版社$|^人民.{0,2}育出版社$")
# 音标碎片（`/i:/` `/1a/` `/e/`）：成串出现即音标表，不是句子。
_PHONETIC = re.compile(r"[/ˈˌ][^\s/ˈˌ]{1,6}[/ˌ]?")
# 剔掉音标记号后的残留检测（冒号是 IPA 长音符，必须一并剔）
# 整段剔掉 `/…/` 音标跨段。**不能**只剔符号：IPA 的字母就是 ASCII（`/i:/`
# 里的 `i`），只剔符号会剩下 `i` 被当成拉丁词。
_PHONETIC_SPAN = re.compile(r"/[^/\s]{1,8}/")
# 单元/小节标记（`1a` `3c` `2b`）与项目标记（`*Project` `Reflecting` `Brainstorming`）。
_SECTION_MARK = re.compile(r"(?:^|\s)[1-9][a-d](?:\s|$)|\*+Project|\bReflecting\b|\bBrainstorm", re.I)
# 全大写词组（`WE ARE FAMILY`、`IN THIS CLASS`）：来自海报/栏目标题，
# 是版面块而不是句子。正文里连续两个 ≥4 字符全大写词 = 判定为版面碎片。
_ALLCAPS_RUN = re.compile(r"\b[A-Z][A-Z]{3,}(?:\s+[A-Z][A-Z]{3,})+\b")
# 说话人标签（`Anne:`）。**一个**说话人是正常对话（有价值）；**两个及以上**
# 说明 OCR 把相邻的两轮发言并成了一句（`Anne: Tom: Well, I can't find…`），
# 那是损坏的句子，不是原文的句子。
_SPEAKER = re.compile(r"\b[A-Z][a-z]{1,12}:")

# 非正文版面：目录页 / 音标页 / 词汇表 / 页眉页脚。这些页的英文句子是**标题
# 片段**（`Why do you like animals?`、`/i:/`），不是可作语境例句的完整表达。
_NOT_PROSE_MARKERS = (
    "contents",
    "pronunciation",
    "word list",
    "vocabulary",
    "unit 1",
    "section a",
    "listening:",
    "speaking:",
    "reading:",
    "writing:",
    "grammar:",
    "self check",
    "单元",
    "目录",
)


def _is_noise_box(b: str) -> bool:
    """单个 OCR box 是否为版面噪声（水印 / 音标 / 页码 / 纯符号）。"""
    t = b.strip()
    if not t:
        return True
    if _WATERMARK.match(t):
        return True
    # 纯页码（`p.1` / `12` / `Unit 3` 里的数字）
    if re.fullmatch(r"(?:p\.?\s*)?\d{1,3}", t, re.I):
        return True
    # 纯音标（`/i:/` `/1a/` `/e/`）—— 这些不是词。冒号也是 IPA 的一部分
    # （`/i:/` 的长音符号），所以残留检测必须连 `:` 一起剔，否则 `/i:/`
    # 会因为剩下一个 `i` 被当成含拉丁字母而漏过。
    if len(t) <= 10 and _PHONETIC.search(t):
        if _ALPHA.search(_PHONETIC_SPAN.sub("", t)) is None:
            return True
    return False


_OCR: Any = None  # 进程内复用，避免每页重载模型（RapidOCR 初始化很贵）
_BOX_CACHE_DIR = PAGE_DIR / "_boxes"


def _cache_path(jpg: Path) -> Path:
    return _BOX_CACHE_DIR / jpg.parent.name / f"{jpg.stem}.json"


def ocr_page(path: Path) -> dict[str, Any]:
    """OCR 一页 → ``{"page", "boxes": [(text, score)], "has_cjk"}``。

    **原始 box（含置信度）落盘缓存**到 ``data/external/pep_pages/_boxes/<book>/p<n>.json``。
    实测 9.4s/页，179 页就是半个多小时；而调门禁必然要反复重跑 —— 有了缓存，
    改门禁后重新筛一遍是**秒级**，不必重新 OCR。缓存 key 含文件大小，
    改了图片自动失效。

    单独成函数以便 ``ProcessPoolExecutor`` 进程池调用；模型走模块级缓存，
    每个 worker 进程各建一次。
    """
    global _OCR
    cache = _cache_path(path)
    if cache.exists():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            return {
                "page": cached["page"],
                "file": str(path),
                "boxes": [(t, float(s)) for t, s in cached["boxes"]],
                "has_cjk": bool(cached["has_cjk"]),
                "from_cache": True,
            }
        except (ValueError, KeyError, OSError):
            pass  # 缓存坏了就重跑 OCR，不要因此失败

    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR

        _OCR = RapidOCR()

    res, _el = _OCR(str(path))
    boxes: list[tuple[str, float]] = []
    if res:
        # res 每项 [box, text, score]；按 y 排序还原阅读顺序。
        items = sorted(res, key=lambda r: min(pt[1] for pt in r[0]))
        for r in items:
            t = str(r[1]).strip()
            if t:
                boxes.append((t, float(r[2]) if len(r) > 2 else 1.0))
    text = " ".join(b[0] for b in boxes)
    out = {
        "page": path.stem.lstrip("p"),
        "file": str(path),
        "boxes": boxes,
        "has_cjk": bool(_CJK.search(text)),
        "from_cache": False,
    }
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json.dumps(
                {
                    "page": out["page"],
                    "has_cjk": out["has_cjk"],
                    "boxes": [[t, s] for t, s in boxes],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass  # 缓存写不进去不影响主流程
    return out


def _is_task_sentence(sent: str) -> bool:
    """判定一句是否为**练习指令**。任一信号命中即拒。"""
    low = sent.lower().strip()
    first = re.split(r"[\s,]", low, maxsplit=1)[0].strip(".:;!?")
    if first in _TASK_VERBS:
        return True
    if any(p in low for p in _TASK_PHRASES):
        return True
    return False


def _is_not_prose(sent: str) -> bool:
    """目录 / 音标 / 词汇表标题片段 —— 看着是英文，但不是可作例句的表达。"""
    low = sent.lower()
    return any(m in low for m in _NOT_PROSE_MARKERS)


# 练习题编号：`4. What can you do to manage…`、`3. Whose tennis racket is it?`
# 那是**题型提示**（问学生要什么），不是课文句子。实测这类在保留句里占比不低。
_EXERCISE_NUM = re.compile(r"^\d{1,2}\s*[.)]\s")
# 词表串：`cap, glove, form, balloon, scissors, bamboo It's made of used wood…`
# —— 前半是并列名词（器材清单），后半被并进来。判据：连续 ≥4 个逗号分隔的
# 短词，且全句没有句末标点出现在第一个逗号之前（即前半不是句子）。
_WORDLIST_RUN = re.compile(r"(?:^|[\s,])[A-Za-z]{1,9}(?:,\s*[A-Za-z]{1,9}){3,}")


def _is_layout_merge(sent: str) -> bool:
    """OCR 把**多栏/海报/音标表**并成一句 —— 那不是原文的句子。

    三个结构信号（都不是关键词表，对新教材同样成立）：
    - 成串音标（≥3 个 `/x/`）→ 音标表；
    - 连续全大写词组（`WE ARE FAMILY`）→ 海报/栏目标题；
    - ≥2 个说话人标签（`Anne: Tom:`）→ 相邻发言被并成一句。
    """
    if len(_PHONETIC.findall(sent)) >= 3:
        return True
    if _ALLCAPS_RUN.search(sent):
        return True
    if len(_SPEAKER.findall(sent)) >= 2:
        return True
    return False


def classify_sentence(
    sent: str,
    *,
    has_cjk_page: bool = False,
    n_boxes: int = 1,
    min_score: float = 1.0,
) -> tuple[str | None, str | None]:
    """返回 ``(keep_reason, reject_reason)``，二者恰有一个非 None。

    纯函数、可单测。顺序有讲究：先剔题型句与非正文（最便宜且最准），再剔
    布局合并、最后剔中文与碎片。

    ``n_boxes`` / ``min_score`` 来自 :func:`split_sentences_scored`：这是两个
    **结构性**判据，用来替代补不完的关键词表 ——
    - 跨了 ≥``_MAX_MERGE_BOXES`` 行才凑成一句 → 几乎必然是多栏/多块被并；
    - 最低置信度 <``_MIN_SCORE`` → 有字没认对（`Say"thankyou"` 丢了空格）。
    """
    s = " ".join(sent.split())
    if not s:
        return None, REJECT_SHORT_OR_JUNK
    if n_boxes > _MAX_MERGE_BOXES:
        return None, REJECT_LAYOUT_MERGE
    if min_score < _MIN_SCORE:
        return None, REJECT_LOW_CONFIDENCE
    if _is_task_sentence(s):
        return None, REJECT_IMPERATIVE_TASK
    if _EXERCISE_NUM.match(s):
        return None, REJECT_IMPERATIVE_TASK
    if _WORDLIST_RUN.search(s):
        return None, REJECT_NOT_PROSE
    if _is_not_prose(s):
        return None, REJECT_NOT_PROSE
    if _is_layout_merge(s):
        return None, REJECT_LAYOUT_MERGE
    if _CJK.search(s):
        return None, REJECT_HAS_CJK
    if _SECTION_MARK.search(s):
        return None, REJECT_NOT_PROSE
    words = _WORD.findall(s)
    # 5 词下限：实测 4 词时大量版面碎片（`Anne: Tom: Well, I can't.`）刚好
    # 压线通过，抬到 5 词后对话正文（普遍 ≥6 词）不受影响。
    if len(words) < _MIN_SENT_WORDS:
        return None, REJECT_SHORT_OR_JUNK
    if not _SENT_END.search(s):
        return None, REJECT_SHORT_OR_JUNK
    content = [w.lower() for w in _WORD.findall(s) if len(w) >= 3]
    if len(content) < 2:
        return None, REJECT_SHORT_OR_JUNK
    return "KEPT_CORPUS", None


def split_sentences(boxes: list[tuple[str, float]] | list[str]) -> list[str]:
    """把 OCR box 序列拼成句子。

    OCR 是逐行/逐块给文本，一个句子常被拆成多个 box（`Put up your hand if you
    want to ask your teacher` + `a question.`）。所以先按「是否以句末标点
    结尾」把 box 串起来，凑成句子。

    先剔掉版面噪声 box（水印/页码/纯音标），否则水印会被拼进第一句、把整句
    染成 HAS_CJK。

    ⚠️ **必须给未闭合的 buffer 封顶**：教材页常有大块无标点的排版元素（音标
    表、单词表、图片说明）。若只等句末标点才 flush，这些 box 会全部堆成一个
    几十上百词的「句子」。实测某页 24 个 box 被并成 1 句 200+ 词 —— 那不是
    句子，只是版面碎片。超 ``_MAX_SENT_WORDS`` 即按当前 buffer 收口并丢弃
    （不硬拼，因为拼出来的「句子」不是原文的句子）。
    """
    sents: list[str] = []
    buf: list[str] = []
    buf_n = 0
    for item in boxes:
        b = item[0] if isinstance(item, tuple) else item
        if _is_noise_box(b):
            continue
        buf.append(b)
        buf_n += 1
        if _SENT_END.search(b):
            sents.append(" ".join(buf))
            buf = []
            buf_n = 0
            continue
        # 缓冲过长 = 这是排版碎片而非句子，收口后丢弃
        if len(" ".join(buf).split()) > _MAX_SENT_WORDS:
            buf = []
            buf_n = 0
    if buf and len(" ".join(buf).split()) <= _MAX_SENT_WORDS:
        sents.append(" ".join(buf))
    return [" ".join(s.split()) for s in sents if s.strip()]


def split_sentences_scored(
    boxes: list[tuple[str, float]]
) -> list[dict[str, Any]]:
    """同 :func:`split_sentences`，但每句附上**拼接行数**与**最低置信度**。

    这两个数是判「OCR 把版面拼坏了」最可靠的信号：
    - 行数多 → 跨栏/跨块拼接（`Every day, from Monday to Friday, Across the
      country…` 是两栏内容被并成一句）；
    - 最低置信度低 → 字形本身没认对（`Say"thankyou"` 丢了空格）。

    关键词表只能一个个补（补不完），这两个数是结构性的。
    """
    out: list[dict[str, Any]] = []
    buf: list[str] = []
    scores: list[float] = []
    for b, score in boxes:
        if _is_noise_box(b):
            continue
        buf.append(b)
        scores.append(score)
        joined = " ".join(buf)
        if _SENT_END.search(b):
            out.append(
                {
                    "text": " ".join(joined.split()),
                    "n_boxes": len(buf),
                    "min_score": min(scores) if scores else 1.0,
                }
            )
            buf, scores = [], []
            continue
        if len(joined.split()) > _MAX_SENT_WORDS:
            buf, scores = [], []
    if buf:
        joined = " ".join(buf)
        if len(joined.split()) <= _MAX_SENT_WORDS:
            out.append(
                {
                    "text": " ".join(joined.split()),
                    "n_boxes": len(buf),
                    "min_score": min(scores) if scores else 1.0,
                }
            )
    return [o for o in out if o["text"].strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description="OCR 人教社英语教材页图并筛出正文句")
    ap.add_argument("--limit", type=int, default=0, help="每本最多处理多少页（0=不限）")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    ap.add_argument("--out", type=Path, default=REPORT_DIR / "pep_ocr_sentences.json")
    args = ap.parse_args()

    if not PAGE_DIR.exists():
        print(f"未找到页图目录：{PAGE_DIR}，先跑 fetch_pep_pages.py", file=sys.stderr)
        raise SystemExit(1)

    jobs: list[Path] = []
    for book_dir in sorted(PAGE_DIR.iterdir()):
        if not book_dir.is_dir():
            continue
        pages = sorted(book_dir.glob("p*.jpg"), key=lambda p: int(p.stem[1:]))
        if args.limit:
            pages = pages[: args.limit]
        jobs.extend(pages)
    if not jobs:
        print("没有待处理页图", file=sys.stderr)
        raise SystemExit(1)

    print(f"OCR {len(jobs)} 页，{args.jobs} 进程…")
    results: list[dict[str, Any]] = []
    if args.jobs > 1:
        with ProcessPoolExecutor(max_workers=args.jobs) as ex:
            for i, r in enumerate(ex.map(ocr_page, jobs), 1):
                results.append(r)
                if i % 10 == 0:
                    print(f"  {i}/{len(jobs)}")
    else:
        for i, p in enumerate(jobs, 1):
            results.append(ocr_page(p))
            if i % 10 == 0:
                print(f"  {i}/{len(jobs)}")

    rejects: Counter = Counter()
    per_book: dict[str, dict[str, Any]] = {}
    out_sentences: list[dict[str, Any]] = []
    for r in results:
        book = Path(r["file"]).parent.name
        sents = split_sentences_scored(r["boxes"])
        kept = 0
        for s in sents:
            keep, rej = classify_sentence(
                s["text"],
                has_cjk_page=r["has_cjk"],
                n_boxes=s["n_boxes"],
                min_score=s["min_score"],
            )
            if keep:
                kept += 1
                out_sentences.append(
                    {
                        "book": book,
                        "page": r["page"],
                        "text": s["text"],
                        "n_boxes": s["n_boxes"],
                        "min_score": round(s["min_score"], 3),
                    }
                )
            else:
                rejects[rej or "UNKNOWN"] += 1
        agg = per_book.setdefault(book, {"pages": 0, "sentences_raw": 0, "kept": 0})
        agg["pages"] += 1
        agg["sentences_raw"] += len(sents)
        agg["kept"] += kept

    report = {
        "summary": {
            "pages_ocr": len(results),
            "sentences_raw": sum(v["sentences_raw"] for v in per_book.values()),
            "sentences_kept": len(out_sentences),
            "reject_reasons": dict(rejects),
        },
        "per_book": per_book,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({**report, "sentences": out_sentences}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print("\n".join(f"  {k}: {v}" for k, v in report["summary"].items() if k != "reject_reasons"))
    print(f"  reject_reasons: {dict(rejects)}")
    print(f"报告: {args.out}")
    print("\n保留句抽样:")
    for s in out_sentences[:8]:
        print(f"  [{s['book']} p{s['page']}] {s['text'][:100]}")


if __name__ == "__main__":
    main()