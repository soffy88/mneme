"""P3 从《2022版课标新增词汇》抽取「单词 / 词性&词义 / 用法搭配」。

⚠️ 产出是**待人工复核队列**，不直接入库：本 PDF 是扫描件，中文 OCR 会出
**形近错字**（实测 `v.攻击;袭击` → `U.攻击;秤击`）。这类错「含中文」「词性在
白名单」都能通过，机械校验拦不住。给 K-12 学生背的释义错一字就是错的。

## 为什么用「表格线建单元格」而不是「按 y 聚类猜行」

第一版按 y 聚类，产出 76 条「通过校验」的记录，但**词与释义整体错位**：
`196 pressure → 王子`、`197 prince → 公主`、`11 aid → 闹钟`。这不是 OCR 噪声，
是行对齐错了 —— 一个记录里 word / meaning / 搭配 三块的 y 坐标并不相同
（实测 attack y=411 而 U.攻击 y=384、序号 19 y=413），按 y 切行必然劈开。

本版改为从 PDF **矢量表格线**建精确单元格网格
（实测 40 条水平线 / 12 条垂直线，去重后 5 列 × 约 21 行/页），再把 OCR
文本块按中心点投到单元格里。行对齐因此由表格结构保证，不依赖任何启发式。

用法：
    python scripts/extract_curriculum_collocation.py --audit
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PDF = (
    _REPO_ROOT / "data" / "external" / "vocab_src"
    / "2022版课标新增词汇【背诵手册+用法搭配】.pdf"
)

DPI = 300
SCALE = DPI / 72.0            # px per pt
DEDUPE_PT = 2.0               # 表格线成对出现（43.4/44.2），容差去重
MIN_CONF = 0.60

POS_WHITELIST = {
    "n", "v", "vt", "vi", "adj", "adv", "prep", "conj", "pron", "det",
    "num", "art", "int", "aux", "modal", "abbr", "pl", "link",
}
# 刻意**不含** `u` / `c`：它们是语法记号（不可数/可数）不是本表的词性标注，
# 而且会放过 OCR 把 `v.` 误读成 `u.` 的噪声 —— 实测 `attack` 就因此把
# pos 记成了 `u`，释义里还留着 `秤击`（应为 `袭击`）。宁可少收，不可错收。
POS_RE = re.compile(
    r"^\**\s*(" + "|".join(sorted(POS_WHITELIST, key=len, reverse=True)) + r")\s*[.．、]\s*",
    re.IGNORECASE,
)
WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'\-/ ()/.]*$")
SEQ_RE = re.compile(r"^\d{1,4}$")
CJK = re.compile(r"[一-鿿]")


def split_collocation(raw: str) -> list[tuple[str, str]]:
    """把一个单元格拆成若干 (英文, 中文) 搭配。

    OCR 经常吃掉英文与中文之间的空格（`boiled water开水`），而且**一个单元格
    里常常有多条搭配**（实测 `traffic accident 交通事故 by accident 偶然地；意外地`
    被当成一条，phrase_cn 里混进了第二个搭配的英文）。所以按
    「拉丁串 → 紧跟中文串」交替切分，不能只在第一个汉字处切一刀。

    中文侧允许夹杂括号等非拉丁字符（`（呼吸的)空气;吸气`）。
    """
    s = raw.strip()
    if not s:
        return []
    # 交替段：拉丁段 / 非拉丁段
    segs = re.findall(r"[一-鿥][^A-Za-z]*|[A-Za-z][^一-鿥]*", s)
    out: list[tuple[str, str]] = []
    i = 0
    while i < len(segs) - 1:
        if re.match(r"^[A-Za-z]", segs[i]) and re.match(r"^[一-鿥]", segs[i + 1]):
            en = segs[i].strip(" ,;，、（(")   # 尾部可能粘上半角/全角左括号
            zh = segs[i + 1].strip(" ,;，")
            if en and zh:
                out.append((en, zh))
            i += 2
            continue
        i += 1
    if not out:
        return []
    return out
# 纯英文词形的单元格（搭配的英文部分也长这样）
ENG_CELL = re.compile(r"^[A-Za-z][A-Za-z'\-/ ()/.,]*$")
# OCR 会在词义单元格里塞进杂散记号：实测 `n.＆.疼痛`（多出全角＆）、
# `& .帮助;援助`（半角& + 空格）。剥掉合法词性后剩下的仍以垃圾记号开头，
# 说明这个单元格的 OCR 结果不可信 —— **拒绝**而不是启发式清洗，脏数据宁可
# 进复核队列也不要静默修补。
_JUNK_PREFIX = re.compile(r"^[^一-鿥A-Za-z0-9（(\[【]+")


def _dedupe(vals: list[float], tol: float = DEDUPE_PT) -> list[float]:
    out: list[float] = []
    for v in sorted(vals):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def _drop_slivers(bounds: list[float], min_gap_pt: float = 10.0) -> list[float]:
    """丢掉切出「极窄列」的边界。

    实测列边界里 386.5 与 390.0 只差 3.5pt（多半是表格外框的双线），不去掉会
    多出一个 3.5pt 的伪列，把该列的文本挤到错误的下标上，表现为大量
    `no_word` 拒绝。
    """
    keep = [bounds[0]]
    for b in bounds[1:]:
        if b - keep[-1] >= min_gap_pt:
            keep.append(b)
    return keep


def table_grid(page) -> tuple[list[float], list[float]]:
    """从矢量线提取 (行 y 边界, 列 x 边界)。纯函数，可单测。"""
    ys: list[float] = []
    xs: list[float] = []
    for dr in page.get_drawings():
        for item in dr["items"]:
            if item[0] == "l":
                a, b = item[1], item[2]
                if abs(a.y - b.y) < 1.0 and abs(a.x - b.x) > 30:
                    ys.append(round((a.y + b.y) / 2, 2))
                elif abs(a.x - b.x) < 1.0 and abs(a.y - b.y) > 10:
                    xs.append(round((a.x + b.x) / 2, 2))
            elif item[0] == "re":
                r = item[1]
                if r.height < 1.5 and r.width > 30:
                    ys.append(round(r.y0, 1))
                elif r.width < 1.5 and r.height > 10:
                    xs.append(round(r.x0, 1))
    return _dedupe(ys), _drop_slivers(_dedupe(xs))


def cell_of(x: float, y: float, ys: list[float], xs: list[float]):
    """点落在哪个单元格，返回 (row_idx, col_idx)；落在格外返回 None。

    边界判定用「最近的两条线之间」，并对超出范围做夹取 —— OCR 框可能略微
    越出表格线，不该因此丢内容。
    """
    def idx(v: float, bounds: list[float]) -> int | None:
        if len(bounds) < 2:
            return None
        for i in range(len(bounds) - 1):
            if bounds[i] <= v <= bounds[i + 1]:
                return i
        if v < bounds[0]:
            return 0
        return len(bounds) - 2

    r, c = idx(y, ys), idx(x, xs)
    if r is None or c is None:
        return None
    return r, c



def profile_columns(buckets: dict[tuple[int, int], list[tuple[float, str]]]) -> dict:
    """按**内容特征**判定每列的角色，不依赖列下标。

    为什么必须这么做：实测同类型的页面，词义列下标在 c2/c3/c4 之间跳
    （p1=c2, p2=c4, p4=c3, p5=c2, p6=c3…），因为某些页多检测到一条竖线，
    多出一个空列。硬编码 col==2 直接导致 81 行找不到词义。
    """
    by_col: dict[int, list[str]] = {}
    for (_r, c), items in buckets.items():
        by_col.setdefault(c, []).extend(t for _y, t in items)

    stats: dict[int, tuple[int, int, int]] = {}
    for c, txts in by_col.items():
        n = len(txts) or 1
        cjk = sum(1 for t in txts if CJK.search(t))
        eng = sum(1 for t in txts if ENG_CELL.match(t))
        num = sum(1 for t in txts if SEQ_RE.match(t))
        stats[c] = (cjk, eng, num)

    def ratio(c: int, i: int) -> float:
        return stats[c][i] / max(len(by_col[c]), 1)

    # 单词列：英文占比最高且块数够
    cands = [c for c in by_col if len(by_col[c]) >= 3]
    if not cands:
        return {"word": None, "seq": None, "meaning": None, "collo": []}
    word_col = max(cands, key=lambda c: ratio(c, 1))
    if ratio(word_col, 1) < 0.5:
        return {"word": None, "seq": None, "meaning": None, "collo": []}

    # 序号列：单词列之外数字占比最高的
    seq_pool = [c for c in cands if c != word_col and ratio(c, 2) > ratio(c, 0)]
    seq_col = max(seq_pool, key=lambda c: ratio(c, 2)) if seq_pool else None

    # 词义列：单词列**右侧**第一个中文占比过半的列
    meaning_col = None
    for c in sorted(c for c in by_col if c > word_col):
        if ratio(c, 0) >= 0.5:
            meaning_col = c
            break

    # 搭配列：词义列右侧再往右、且有中文的列
    collo_cols: list[int] = []
    if meaning_col is not None:
        for c in sorted(c for c in by_col if c > meaning_col):
            if ratio(c, 0) >= 0.3 and c != seq_col:
                collo_cols.append(c)
    return {"word": word_col, "seq": seq_col, "meaning": meaning_col, "collo": collo_cols}


def extract_page(pdf_path: Path, page_no: int) -> tuple[list[dict], dict]:
    """返回 (记录, 统计)。行对齐完全由表格线保证，列角色由内容特征判定。"""
    import pymupdf
    from rapidocr_onnxruntime import RapidOCR

    doc = pymupdf.open(pdf_path)
    page = doc[page_no]
    ys, xs = table_grid(page)
    n_col = max(len(xs) - 1, 1)

    tmp = tempfile.mkdtemp()
    subprocess.run(
        ["pdftoppm", "-png", "-r", str(DPI), "-f", str(page_no + 1),
         "-l", str(page_no + 1), str(pdf_path), f"{tmp}/p"], check=True
    )
    img = next(Path(tmp).glob("p-*.png"))
    res, _ = RapidOCR()(str(img))

    buckets: dict[tuple[int, int], list[tuple[float, str]]] = {}
    low_conf = 0
    for box, txt, conf in res or []:
        if float(conf) < MIN_CONF:
            low_conf += 1
            continue
        xs_px = [p[0] for p in box]
        ys_px = [p[1] for p in box]
        cx = (min(xs_px) + max(xs_px)) / 2 / SCALE
        cy = (min(ys_px) + max(ys_px)) / 2 / SCALE
        pos = cell_of(cx, cy, ys, xs)
        if pos is None:
            continue
        buckets.setdefault(pos, []).append((cy, txt.strip()))

    roles = profile_columns(buckets)
    if roles["word"] is None:
        stats = {"rows": len(ys) - 1, "cols": n_col, "blocks_low_conf": low_conf,
                 "roles": None}
        doc.close()
        return [], stats

    def text_of(row: int, col: int) -> str:
        return " ".join(t for _y, t in sorted(buckets.get((row, col), []))).strip()

    records = []
    for (row, col) in sorted(buckets):
        if col != roles["word"]:
            continue
        word = text_of(row, col)
        if not WORD_RE.match(word):
            continue
        rec = {
            "row": row,
            "seq": text_of(row, roles["seq"]) if roles["seq"] is not None else "",
            "word": word,
            "meaning": text_of(row, roles["meaning"]) if roles["meaning"] is not None else "",
            "collocations": [text_of(row, c) for c in roles["collo"] if text_of(row, c)],
            "rejected": [],
        }
        records.append(rec)
    stats = {"rows": len(ys) - 1, "cols": n_col, "blocks_low_conf": low_conf,
             "roles": roles}
    doc.close()
    return records, stats


def validate(rec: dict) -> tuple[dict | None, str]:
    word = rec["word"].strip()
    if not word:
        return None, "no_word"
    if not WORD_RE.match(word):
        return None, "bad_word"
    meaning = rec["meaning"].strip()
    if not CJK.search(meaning):
        return None, "no_chinese_meaning"
    m = POS_RE.match(meaning)
    if not m:
        return None, "pos_not_in_whitelist"
    body = meaning[m.end():].strip()
    if _JUNK_PREFIX.match(body):
        return None, "ocr_junk_in_meaning"

    col = []
    for raw in rec["collocations"]:
        for en, zh in split_collocation(raw):
            if not WORD_RE.match(en + " "):
                rec["rejected"].append({"text": f"{en}|{zh}", "why": "bad_en"})
                continue
            col.append({"en": en, "zh": zh})
    return (
        {"row": rec["row"], "seq": rec["seq"], "word": word.lower(),
         "pos": m.group(1).lower(), "meaning": body,
         "collocations": col},
        "",
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    ap.add_argument("--audit", action="store_true", default=True)
    args = ap.parse_args()

    if not args.pdf.exists():
        print(f"缺少 PDF：{args.pdf}")
        return

    import pymupdf

    n_pages = pymupdf.open(args.pdf).page_count
    kept, rejects, dropped = [], {}, 0
    for pno in range(n_pages):
        recs, st = extract_page(args.pdf, pno)
        dropped += st["blocks_low_conf"]
        if pno == 0:
            print(f"页面网格：{n_pages} 页，第 1 页 {st['rows']} 行 × {st['cols']} 列")
        for rec in recs:
            ok, why = validate(rec)
            if ok:
                kept.append(ok)
            else:
                rejects[why] = rejects.get(why, 0) + 1

    print(f"低置信丢弃块：{dropped}")
    print(f"通过机械校验：{len(kept)} 条   拒绝：{rejects or '无'}")
    print(f"提取到用法搭配：{sum(len(r['collocations']) for r in kept)} 条")
    print(f"含搭配的记录：{sum(1 for r in kept if r['collocations'])}/{len(kept)}")

    print("\n--- 样例（词/释义配对现由表格线保证；字形仍需人工看）---")
    for r in kept[:10]:
        print(f"  {r['word']:16s} {r['pos']:5s} {r['meaning'][:30]}")
        for c in r["collocations"][:2]:
            print(f"        · {c['en']}  {c['zh']}")

    out = _REPO_ROOT / "data" / "external" / "vocab_src" / "curriculum_collocations_review.json"
    out.write_text(
        json.dumps({"source": args.pdf.name, "note": "OCR 待人工复核，未入库",
                    "records": kept}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\n复核队列：{out}")
    print("⚠️ 未写库。中文形近错字（v.袭击→U.秤击）无法机械拦截。")


if __name__ == "__main__":
    main()