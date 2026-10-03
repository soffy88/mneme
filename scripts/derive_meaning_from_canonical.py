"""P0.4a 从既有 canonical_meaning 确定性派生 meaning_cn + pos（零 LLM 调用）。

发现（2026-10-02 实测，改变了 P0.4 的做法）：
`vocabulary_items.canonical_meaning` 里已经存着**词典级、多义、带词性**的中文
释义，来源是教材词表导入（source=k12_sync）。样例：

    bank       => "n. 银行；岸；浅滩；储库\nvt. 将…存入银行；倾斜转弯\nvi. 堆积；倾斜转弯"
    beautiful  => "adj. 美丽的\nadv. 出色地\nadj. 出色的..."
    A Christmas Carol => "圣诞颂歌；小气财神；圣诞欢歌"

这比「拿 1 条 NCE 例句让 LLM 猜释义」**更权威**（词典 vs 推断），而且免费、确定、
无幻觉风险。因此 P0.4 拆成两步，本脚本是 a：能派生的直接派生，只把真正没有中文
释义的少数词留给 b（LLM 生成）。

核心范围的 canonical_meaning 构成（3,369 词）：
    含中文释义 2,201 (65.3%)  ← 本脚本处理这批
    IPA 形如 [..]  807 (24.0%)  ← 是音标不是释义，**跳过**（见下方说明）
    占位符 无/-   361 (10.7%)  ← 无内容，跳过

那 807 条 IPA 为什么跳过：它们是教材词表里给专名/缩略词标的音标，属于**读音**
而非释义。它们的自然去处是 phonetic_us/phonetic_uk，但无法从该列判断英美音，
且本脚本不写 phonetic_* —— 混写记音体系的事已在 a7b8c9d0e1f2 里定过规矩，
不在这里重复犯。属独立决策，已记入 STATUS。

派生规则（纯确定性，无模型）：
    1. 取第一行（主词性）
    2. 行首 "n. " / "vt. " 之类的词性标签抽出写进 pos 列
    3. 剩下的义项以 '；' 连接，作为 meaning_cn
    4. 释义为空 / 只剩标点的行不写

只写 meaning_cn IS NULL 的行，按 id 更新（word 不唯一），天然幂等。

    docker compose exec api python scripts/derive_meaning_from_canonical.py
    docker compose exec api python scripts/derive_meaning_from_canonical.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services  # noqa: E402,F401  (vendor sys.path shim)
from obase.db import SessionLocal  # noqa: E402
from sqlalchemy import text  # noqa: E402

CORE_COLLECTION = "core-exam-zhongkao-gaokao-k12"

# 占位符与「是读音还是释义」的判定**不再本地实现** —— 统一走
# services.vocab_meaning（单源红线：两个互相矛盾的判定正是本仓要防的漂移）。
# 旧规则是 `_IPA_RE = ^[\[（(]`，它把 `[法] 法案`、`(使)远离`、`[人名] 齐珀`
# 这类**带方括号义项标签的释义**误判成音标丢掉（全表 11 条至今 meaning_cn 为空）。
from services.vocab_meaning import (  # noqa: E402
    PLACEHOLDERS,
    is_phonetic_transcription,
)

# 行首词性标签：n. / vt. / vi. / adj. / adv. / prep. / conj. / pron. / det. /
# int. / aux. / num. / art. / abbr. / pl. / link v. / mod. 等。
# 限定在 14 字符内且只含字母/点/空格，避免把普通句子误判成词性标签。
_POS_PREFIX_RE = re.compile(r"^((?:[A-Za-z]+\.?\s*){1,3})\s+(.+)$", re.DOTALL)

# meaning_cn 是 TEXT，但展示用要短。超过这个长度就按义项边界截断，绝不切在词中间。
MAX_GLOSS_CHARS = 60


def _clean_senses(raw: str) -> str:
    """把一行义项文本收拾干净：去首尾空白、去掉纯占位义项、限长按边界截断。"""
    parts = [p.strip() for p in raw.replace("\r", "").split("；")]
    parts = [p for p in parts if p and p not in PLACEHOLDERS]
    if not parts:
        return ""
    gloss = "；".join(parts)
    if len(gloss) <= MAX_GLOSS_CHARS:
        return gloss
    # 超长则保留能放下的完整义项，不切在词中间
    kept: list[str] = []
    total = 0
    for p in parts:
        if total + len(p) + 1 > MAX_GLOSS_CHARS:
            break
        kept.append(p)
        total += len(p) + 1
    return "；".join(kept) if kept else parts[0][:MAX_GLOSS_CHARS]


def derive(canonical: str | None) -> tuple[str | None, str | None]:
    """从 canonical_meaning 派生 (meaning_cn, pos)。无法派生返回 (None, None)。

    纯函数，便于单测。
    """
    if not canonical:
        return None, None
    text_all = canonical.strip()
    if text_all in PLACEHOLDERS:
        return None, None
    if is_phonetic_transcription(text_all):
        # 形如 [ˈeərən]（括号开头且内部无汉字）——是读音不是释义。
        # 注意不能只看「括号开头」：`[法] 法案` / `(使)远离` 是带义项标签的释义。
        return None, None

    for line in text_all.split("\n"):
        line = line.strip()
        if not line or line in PLACEHOLDERS:
            continue
        m = _POS_PREFIX_RE.match(line)
        if m:
            pos_raw, senses = m.group(1).strip(), m.group(2)
            # 词性标签必须短且像标签，否则整行当作无词性释义
            if len(pos_raw) <= 14 and "." in pos_raw:
                gloss = _clean_senses(senses)
                if gloss:
                    return gloss, pos_raw[:20]
                continue
            # 没有点号就不是标签，整行当释义
            gloss = _clean_senses(line)
            if gloss:
                return gloss, None
        else:
            # 整行可能只是一个光秃秃的词性标签（"n." / "vt." / "link v."）。
            # 这类行没有义项，若不拦就会把 "n." 直接当成中文释义写进 meaning_cn。
            stripped = re.sub(r"[.\s]", "", line)
            if stripped and stripped.isalpha() and len(stripped) <= 8 and "." in line:
                continue
            gloss = _clean_senses(line)
            if gloss:
                return gloss, None
    return None, None


async def run(collection: str, apply: bool, fill_pos: bool) -> None:
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT v.id, v.word, v.canonical_meaning, v.pos, v.example_sentence "
                    "FROM vocabulary_items v "
                    "JOIN vocabulary_collection_memberships m ON m.vocabulary_item_id = v.id "
                    "WHERE m.collection_id = :c AND coalesce(v.meaning_cn, '') = ''"
                ),
                {"c": collection},
            )
        ).all()

        print(f"目标范围 collection={collection}")
        print(f"  待填 meaning_cn 词数 = {len(rows)}")

        plans: list[tuple[str, str, str | None, str]] = []
        stats = {
            "derived": 0, "derived_with_pos": 0, "no_chinese": 0, "ipa_only": 0, "empty": 0,
        }
        for vid, word, canonical, pos_now, example in rows:
            if not canonical or not canonical.strip():
                stats["empty"] += 1
                continue
            if canonical.strip() in PLACEHOLDERS:
                stats["empty"] += 1
                continue
            if is_phonetic_transcription(canonical.strip()):
                stats["ipa_only"] += 1
                continue
            gloss, pos = derive(canonical)
            if not gloss:
                stats["no_chinese"] += 1
                continue
            # pos 已有值就不覆盖（尊重既有数据）
            final_pos = pos if (pos and not pos_now) else None
            stats["derived"] += 1
            if final_pos:
                stats["derived_with_pos"] += 1
            plans.append((vid, gloss, final_pos, word))

        n = len(plans)
        print(f"  可派生             = {stats['derived']}")
        print(f"    其中可导出 pos   = {stats['derived_with_pos']}")
        print(f"  canonical 是 IPA   = {stats['ipa_only']}（读音，非释义，跳过）")
        print(f"  canonical 是占位符 = {stats['empty']}")
        print(f"  派生不出（需 LLM） = {stats['no_chinese']}")
        if not fill_pos:
            print("  pos 写入           = 关闭（--fill-pos 才写，见下）")

        print(f"  注：可派生 {len(plans)} 词是否有 NCE 例句不影响本步（教材释义优先）")

        if not plans:
            print("无可写入项，退出")
            return

        if not apply:
            print(f"\n[dry-run] 将更新 {n} 行。未落库。")
            for vid, gloss, pos, word in plans[:8]:
                print(f"    {word:18s} pos={pos or '-':6s} {gloss}")
            return

        now = datetime.now(timezone.utc)
        # pos 默认**不写**：meaning_cn 是教材原文照搬（可追溯），pos 则是从词性标签
        # 推断出来的，对专名/一词多性会明显出错（实测 Tuesday → "n."、cool 的
        # 释义混了形容词义却标 "n."）。不把我推断的结构化数据塞进展示字段。
        # 要写就显式 --fill-pos。
        for vid, gloss, pos, _word in plans:
            if fill_pos:
                await db.execute(
                    text(
                        "UPDATE vocabulary_items "
                        "SET meaning_cn = :g, pos = COALESCE(pos, :p), updated_at = :now "
                        "WHERE id = :vid AND coalesce(meaning_cn, '') = ''"
                    ),
                    {"g": gloss, "p": pos, "now": now, "vid": vid},
                )
            else:
                await db.execute(
                    text(
                        "UPDATE vocabulary_items SET meaning_cn = :g, updated_at = :now "
                        "WHERE id = :vid AND coalesce(meaning_cn, '') = ''"
                    ),
                    {"g": gloss, "now": now, "vid": vid},
                )
        await db.commit()

        done = (
            await db.execute(
                text(
                    "SELECT count(*) FROM vocabulary_items v "
                    "JOIN vocabulary_collection_memberships m ON m.vocabulary_item_id = v.id "
                    "WHERE m.collection_id = :c AND coalesce(v.meaning_cn,'') <> ''"
                ),
                {"c": collection},
            )
        ).scalar()
        print(f"\n完成：本次更新 {n} 行；范围内已有 meaning_cn {done} 词")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    parser.add_argument("--collection", default=CORE_COLLECTION)
    parser.add_argument(
        "--fill-pos",
        action="store_true",
        help="同时回填 pos（默认不写：pos 是推断值，专名/多性词会错）",
    )
    args = parser.parse_args()
    asyncio.run(run(args.collection, apply=args.apply, fill_pos=args.fill_pos))