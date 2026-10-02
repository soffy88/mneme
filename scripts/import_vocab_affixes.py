"""P4 从《威威的GPT单词本》词根/词缀分析抽取结构化分解，写入 vocabulary_affixes。

## 为什么用确定性规则而不是再调一次 LLM

源数据已经是 LLM 写的散文了。再叠一层 LLM 抽取 = 多一个误差面，且不可复现。
实测这些散文的句式相当规整，可直接规则化（7,948 词条命中量）：
    `词根是 "cap-"`                     1,384
    `"X" 是词根`                          507
    `"X" 是后缀`                          491
    `该单词没有前缀和后缀`                 419  → 无分解，留空
    `"X" 是前缀`                          303
    `由词根 "cap-" 与后缀 "-able" 合成`     4

## 关键防线：**形态自洽校验**

散文会自相矛盾，最典型的是 `discover`：先说词根是 `dis-`+`cooperire`，紧接着又说
「该单词没有前缀和后缀。中缀是 -ver」。

因此抽取结果必须能**还原出原词**才采信：
    prefix → word 以它开头
    suffix → word 以它结尾
    root   → word 包含它
`discover` 的 `cooperire` 不出现在 `discover` 里 → 直接判否，不入库。
这一步纯确定性，能拦掉整类幻觉，不依赖任何模型判断。

## 留空而非猜测

- 散文里明说「没有前缀和后缀」→ 不写（不是缺失，是确定没有）。
- 同一角色出现互相矛盾的候选 → 该角色留空（consensus 失败）。
- 形态校验不过 → 整条留空。
- `meaning_cn` 只有在能确定对应中文释义时才填，否则留空。

    docker compose exec api python scripts/import_vocab_affixes.py
    docker compose exec api python scripts/import_vocab_affixes.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import html
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services  # noqa: E402,F401  (vendor sys.path shim)
from obase.db import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402
from services.vocab_affixes import validate_segment  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EPUB = _REPO_ROOT / "data" / "external" / "vocab_src" / "威威的GPT单词本(8000词).epub"
CORE_COLLECTION = "core-exam-zhongkao-gaokao-k12"

SEG = r"([A-Za-z][A-Za-z\-]{1,14})"
# 各角色的候选抽取式。引号与「是/为」都设为可选 —— 实测散文里
# `词根"sider"意为`、`前缀"de-"的意思是`、`-ity 是后缀`（无引号）、
# `由词根capt- 构成` 混用，只认「X 是词根」会漏掉 1290 条。
# 顺序即优先级；同角色多个**不同**候选 -> 判为矛盾，留空不猜。
_PATTERNS: dict[str, list[str]] = {
    "prefix": [
        rf"{SEG}\s*[\"“”]?\s*是前缀",
        rf"前缀(?:是|为)?\s*[\"“]{SEG}[\"”]?",
        rf"由前缀\s*[\"“]?{SEG}",
        rf"[\"“]{SEG}[\"”]?\s*是前缀",
    ],
    "root": [
        rf"词根(?:是|为)?\s*[\"“]{SEG}[\"”]?",
        rf"{SEG}\s*[\"“”]?\s*是词根",
        rf"由词根\s*[\"“]?{SEG}",
        rf"[\"“]{SEG}[\"”]?\s*是词根",
    ],
    "suffix": [
        rf"{SEG}\s*[\"“”]?\s*是后缀",
        rf"后缀(?:是|为)?\s*[\"“]{SEG}[\"”]?",
        rf"与后缀\s*[\"“]?{SEG}",
        rf"[\"“]{SEG}[\"”]?\s*是后缀",
    ],
}
# 明确说没有分解
PATTERNS: dict[str, list[re.Pattern]] = {
    k: [re.compile(p_) for p_ in v] for k, v in _PATTERNS.items()
}
NO_AFFIX = re.compile(r"没有前缀和后缀|没有词缀|无前缀和后缀|没有前缀或后缀|没有前缀")
# 来源语词：来自拉丁词"capere" / 源自拉丁语
ORIGIN = re.compile(r"来自(?:拉丁|希腊|法语|德语)?[词语]?[\"“]([A-Za-z][A-Za-z\-]{{1,20}})[\"”]")


def _entry_text(z: zipfile.ZipFile, name: str) -> str:
    s = z.read(name).decode("utf-8", "ignore")
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _bare(seg: str) -> str:
    """去掉词缀标记横线，用于形态比对：cap- -> cap"""
    return seg.strip().strip("-").lower()


def morphology_ok(word: str, prefix: str | None, root: str | None, suffix: str | None) -> bool:
    """分解必须能还原出原词，否则判为幻觉。"""
    w = word.lower()
    p, r, s = (_bare(prefix or ""), _bare(root or ""), _bare(suffix or ""))
    if p and not w.startswith(p):
        return False
    if s and not w.endswith(s):
        return False
    if r and r not in w:
        return False
    return bool(p or r or s)


def extract(word: str, body: str) -> tuple[dict | None, str]:
    """从词条散文抽结构化分解。返回 (结果, 原因)。纯函数，可单测。

    注意：只取**词根分析 / 词缀分析**两段，避免「发展历史」「单词变形」里的
    其它拉丁词被误当成词根。
    """
    seg_roots = body.find("词根分析")
    seg_affix = body.find("词缀分析")
    if seg_roots < 0 and seg_affix < 0:
        return None, "no_affix_section"
    end = min([i for i in (body.find("发展历史"), body.find("单词变形")) if i > 0] or [len(body)])
    scope = body[:end]

    if NO_AFFIX.search(scope) and not any(
        p.search(scope) for pats in PATTERNS.values() for p in pats
    ):
        return None, "explicit_no_affix"

    picked: dict[str, str | None] = {}
    for role, pats in PATTERNS.items():
        cands: list[str] = []
        for p in pats:
            for m in p.finditer(scope):
                seg = validate_segment(m.group(1), max_len=32 if role != "root" else 48)
                if seg:
                    cands.append(seg.lower())
        # 归一化：去掉词缀标记横线并小写。SEG 允许尾连字符但不允许首连字符，
        # 直接存会出现 `pre-` 与 `dict` 并存的不一致形态；连字符属于书写习惯，
        # 由 format_affix_chain 按位置决定，不该混进数据。
        uniq = sorted({_bare(c) for c in cands if _bare(c)})
        if not uniq:
            picked[role] = None
        elif len(uniq) == 1:
            picked[role] = uniq[0]
        else:
            picked[role] = None  # 角色内互相矛盾 -> 留空，不猜

    if not any(picked.values()):
        return None, "nothing_extracted"

    # 词根质量门：排除「平凡词根」——等于整词、或与整词相差 <=2 字符
    # （coach->coach）。仅此而已。
    #
    # 曾试过加「词根位于词末即判为后缀」的规则，实测**过度拒绝**：predict->dict、
    # factory->fact、conduct->duct、reject->ject、inspect->spect —— 拉丁词根大量
    # 落在词尾，这条规则会砍掉一大类真词根，损失远大于它挡掉的 chinese->ese。
    # 角色的权威来源是散文里的「词根/前缀/后缀」标注，形态校验只负责否掉
    # 明显幻觉（如 discover 的 cooperire）。
    r = _bare(picked["root"] or "")
    if picked["root"]:
        if len(r) < 3 or len(_bare(word)) - len(r) <= 2:
            picked["root"] = None
    if not morphology_ok(word, picked["prefix"], picked["root"], picked["suffix"]):
        return None, "morphology_mismatch"
    if not any(picked.values()):
        return None, "root_too_trivial"

    om = ORIGIN.search(scope)
    origin = om.group(1) if om else None
    # confidence：三个角色都能还原且无留空 -> 高；有留空但根能还原 -> 中
    filled = sum(1 for v in picked.values() if v)
    conf = 0.9 if filled == 3 else (0.75 if filled == 2 else 0.6)
    return (
        {
            "word": word,
            "prefix": picked["prefix"],
            "root": picked["root"],
            "suffix": picked["suffix"],
            "origin": origin,
            "source": "WLLM",
            "confidence": conf,
        },
        "",
    )


async def run(epub: Path, apply: bool) -> None:
    if not epub.exists():
        print(f"缺少 EPUB：{epub}")
        return
    z = zipfile.ZipFile(epub)

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT v.id, lower(v.word) FROM vocabulary_items v "
                    "JOIN vocabulary_collection_memberships m ON m.vocabulary_item_id = v.id "
                    "WHERE m.collection_id = :c"
                ),
                {"c": CORE_COLLECTION},
            )
        ).all()
        by_word: dict[str, list[str]] = {}
        for vid, w in rows:
            by_word.setdefault(w, []).append(vid)
        have = (
            await db.execute(text("SELECT vocabulary_item_id FROM vocabulary_affixes"))
        ).scalars().all()
        already = set(have)
        print(f"核心范围 {len(rows)} 行 / {len(by_word)} 词；已有分解 {len(already)} 条")

    plans: list[tuple[str, dict]] = []
    reasons: dict[str, int] = {}
    for name in z.namelist():
        m = re.match(r"OEBPS/\d+_([a-z][a-z\-]*)\.xhtml$", name)
        if not m:
            continue
        word = m.group(1)
        if word not in by_word:
            continue
        got, why = extract(word, _entry_text(z, name))
        if not got:
            reasons[why] = reasons.get(why, 0) + 1
            continue
        for vid in by_word[word]:
            if vid in already:
                continue
            plans.append((vid, got))

    print(f"可入库分解 = {len(plans)}（覆盖 {len({p[1]['word'] for p in plans})} 词）")
    print(f"  留空原因分布 = {reasons}")

    if not plans:
        print("无可写入项")
        return
    if not apply:
        from services.vocab_affixes import format_affix_chain

        for vid, g in plans[:12]:
            print(
                f"    {g['word']:16s} {format_affix_chain(g['prefix'], g['root'], g['suffix']):24s}"
                f" conf={g['confidence']}"
            )
        print("\n[dry-run] 未落库。")
        return

    async with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        for vid, g in plans:
            await db.execute(
                text(
                    "INSERT INTO vocabulary_affixes "
                    "(vocabulary_item_id, prefix, root, suffix, origin, source, confidence, "
                    " created_at, updated_at) "
                    "VALUES (:vid, :p, :r, :s, :o, :src, :c, :now, :now) "
                    "ON CONFLICT (vocabulary_item_id) DO NOTHING"
                ),
                {
                    "vid": vid,
                    "p": g["prefix"],
                    "r": g["root"],
                    "s": g["suffix"],
                    "o": g["origin"],
                    "src": g["source"],
                    "c": g["confidence"],
                    "now": now,
                },
            )
        await db.commit()
        n = (await db.execute(text("SELECT count(*) FROM vocabulary_affixes"))).scalar()
        print(f"\n完成：库内分解 {n} 条")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--epub", type=Path, default=DEFAULT_EPUB)
    _a = ap.parse_args()
    asyncio.run(run(_a.epub, _a.apply))