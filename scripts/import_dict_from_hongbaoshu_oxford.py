"""scripts/import_dict_from_hongbaoshu_oxford.py — 从 EchoType 的红宝书/牛津 5000
词表回填 pos 与词典释义（第一批词表之后的第二批）。

数据源：EchoType（MIT）`public/wordbooks/`：

| 源 | N | payload 形状 |
|---|---|---|
| `hongbaoshu.json` | 4,770 | `放弃， 放置不管 (vt.)` —— **词性组在句尾** |
| `oxford5000.json` | 5,497 | `v. （不顾责任…）离弃…; n. 【正式】放任; 时态:abandoned…` |

已存到 `data/external/vocab_src/`（`data/external/` 已被 .gitignore 排除）。

## 为什么还值得做（第一批 `coca20000` 之后的实测）

`coca20000` 填完后，核心范围（单词口径）仍剩 **pos 空 163 词 / 无任何可用释义 776 词**。
释义缺口是记忆节点生成的**关键路径**：无释义 → 过不了 `MEANING_AUTHORITY`
→ 生成不了节点，而 `vocabulary_memory_nodes` 现在是 **0 行**。

实测这两个词表能补：

| | pos 缺口 | 释义缺口 |
|---|---|---|
| hongbaoshu 单独 | 14 | 378 |
| + oxford5000 | **32** | **544** |
| （完全不设门禁的天花板） | 41 | 592 |

所以门禁只砍掉约 8% 的天花板，换来「不给孩子看错词性」—— 值得。

## ⚠️ 两个源各有各的坑，都按**拒绝**而不是清洗处理

### 1. `hongbaoshu`：词性在句尾，且常是**多词性**

`access: 进入， 访问 (noun, vt.)` —— 2,770 条带多个词性（`{1: 3423, 2: 277, 3: 1}`）。
取**第一个**作 `pos`（词表已按义项重要性排序），不是猜。另有一段
`艺术 (n.) - 创造性表现` 形如「词性组 + ` - ` + 补充说明」，词性组仍可锚定。

### 2. `oxford5000`：**`adv.` 被 PDF 抽取截断成 `ad` + `v.`**（371 条）

实测 `abroad: ad; v. 到国外, 在国外到处` —— 若按「行首词性标签」解析，会把
`abroad` 标成**动词**。371 条全是副词（`abroad/absolutely/accidentally/accordingly/
accurately/…`），可判定是抽取器在句点处切坏。

本脚本**一律拒绝**这 371 条，不做「猜回adv.」的修复 —— 实测把修复打开只多拿
22 条释义 / 2 条 pos（566 vs 544），收益远小于「给孩子看错词性」的风险。
沿用象形 9000 那次的口径：**门控是拒绝，不是启发式清洗**。

### 3. 尾部元数据段（`时态:` / `名 词:` / `形容词:` / `副 词:` / `比较级:` …）

oxford5000 有 1,857 条带这种「派生词表」尾巴。它不是义项，切掉即可 —— 这是
**删除非释义内容**而非修改释义，故与上面的「拒绝」不同，处理方式是截到该标记前。

## 只填「当前完全拿不到释义」的词，不覆盖已有的

与 `import_dict_from_coca20k.py` 同一口径：词典释义质量高于单句派生，但覆盖
已有的会**改变学生看到的答案**，属要人决策的事。只写 `classify_meaning_source
(...).usable` 为 False 的词。

`pos` 那边不纠结：只写 `pos` 为空的行，绝不碰已有的 100+ 种历史脏值。

**不回退覆盖 coca2000 已写的行**：`vocabulary_dictionary_glosses` 有
`uq_vocab_dict_gloss_item` UNIQUE 约束 + `ON CONFLICT DO NOTHING`，天然幂等。

## 跑法

    docker compose exec api python scripts/import_dict_from_hongbaoshu_oxford.py
    docker compose exec api python scripts/import_dict_from_hongbaoshu_oxford.py --apply
    docker compose exec api python scripts/import_dict_from_hongbaoshu_oxford.py --pos-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
VOCAB_SRC = _REPO_ROOT / "data" / "external" / "vocab_src"
DEFAULT_SOURCES = (
    (VOCAB_SRC / "hongbaoshu.json", "ECHOTYPE_HONGBAOSHU"),
    (VOCAB_SRC / "oxford5000.json", "ECHOTYPE_OXFORD5000"),
)
COLLECTION = "core-exam-zhongkao-gaokao-k12"
MAX_GLOSS = 200

# 与 `services.vocab_senses.canon_pos` / coca20k 导入器同一套词性标签。
# 左侧是源文件里的写法（长短不一），右侧是写入 `vocabulary_items.pos` 的规范形。
_POS_CANON: dict[str, str] = {
    "n": "n",
    "noun": "n",
    "v": "v",
    "vb": "v",
    "verb": "v",
    "vt": "vt",
    "vi": "vi",
    "adj": "adj",
    "a": "adj",
    "adv": "adv",
    "adverb": "adv",
    "prep": "prep",
    "conj": "conj",
    "pron": "pron",
    "pronoun": "pron",
    "num": "num",
    "numeral": "num",
    "art": "art",
    "aux": "aux",
    "auxiliary verb": "aux",
    "modal verb": "aux",
    "int": "int",
    "interj": "int",
    # 「复数名词」「系动词」不是本仓 pos 词表里的词性，但它们**确定**是名词/动词，
    # 归一到 n/v 而不是丢弃 —— 丢整条释义比归一更糟。
    "plural noun": "n",
    "linking verb": "v",
}

_CJK = re.compile(r"[\u4e00-\u9fff]")

# ---- hongbaoshu：词性组 `… (vt.)` / `… (noun, vt.)` / `… (n./vt.)` ----
# 实测 4,770 条里：3,701 条词性组在句尾，1,069 条形如
# `艺术 (n.) - 创造性表现`（组后还有 ` - ` 说明段）。两类都是「恰好一个括号组」，
# 故按 finditer 取第一个并用「组后只能是句尾或 ` - ` 说明」把住形状。
_HB_GROUP = re.compile(r"\(([^)]*)\)")
_HB_NOTE = re.compile(r"^\s*[-—]\s*\S")

# ---- oxford5000：词性在行首/分号后 ----
_OX_SENSE = re.compile(
    r"(?:^|[;；]\s*)((?:n|v|vt|vi|adj|adv|prep|conj|pron|num|art|aux|int))\.\s*"
)
# `ad;` / `ad,` 开头 —— 截断的 `adv.`，一律拒绝（见 docstring）。
_OX_BROKEN_ADV = re.compile(r"^\s*(?:ad|a)\s*[;,]\s*(?:v|vt|vi)\.")
# 同一个截断也可能出现在**句中**（实测 `seventh`：`adj. 第七的；七分之一的ad\nv. 居第七位地`
# —— 抽取器把 `adv.` 切成 `ad` + 换行 + `v.`）。行首那条拦不住它。
# `(?<![A-Za-z])` 保证不把完整的 `adv.` 也当成坏掉的那个。
_OX_BROKEN_ADV_MID = re.compile(r"(?<![A-Za-z])ad(?!v)[\s]*[\n\r;,]?\s*(?:v|vt|vi)\.")
# 尾部派生词表段，不是义项。实测出现的写法很杂：`时态:` `名 词:` `动 词:`
# `形容词:` `副 词:` `复 数:`（注意「复数」的数不是词），故按
# 「任意词 + 可选空格 + 词/数 + 冒号」收。
_OX_TAIL = re.compile(
    r"(?:时态|[名动副复]\s*[词数]|形容词|比较级|最高级|过去式)\s*[:：]"
)
# 抽取器残渣：`add-on1 ENTRIES FOUND:add-on (noun)add-on/ˈædˌɑːn/ nounplural…`
_OX_EXTRACTOR_JUNK = "ENTRIES FOUND"
# `vt. & vi. (使)联合` —— 复合词性里第二项带 `&`。`& vi.` 不是释义，
# 若不剥掉会漏进释义文本（`combine` 的义项前就多出「& vi.」）。
_OX_COMPOUND_POS = re.compile(r"^\s*&\s*(?:v|vt|vi)\.\s*")
# 源数据里被粘进中文释义的英文（`抵销Balance天秤星座`、`追击Chase蔡斯(姓氏)`、
# `freeze的过去分词`）—— 百科尾巴粘上来的，不是义项。**整条拒**（实测 5 条）。
#
# 只查**括号外**：括号里的拉丁文是合法的补充说明（`女士(代替Miss或Mrs的字…)`），
# 把它算作粘接会误杀好数据。
_OX_PAREN = re.compile(r"[（(][^）)]*[）)]")
_OX_ASCII_GLUE = re.compile(r"[一-鿿][A-Za-z]{2,}[一-鿿]")
# 长串英文（实测 `回形针CLIPabbr. Cellular Logic Image Processor 单元逻辑映象处理器Compiler
# Language`）—— 缩略词/百科词条被整段粘进释义。比上一条更宽，能盖住「英文后跟
# 标点而非汉字」的漏网情况。长度取 8 是为了不误伤 `Miss` / `Mrs` 这类合法缩写。
_OX_LONG_LATIN = re.compile(r"[A-Za-z][A-Za-z' ]{8,}")


def _canon_pos(token: str) -> str | None:
    """源里的词性写法 → 规范 pos。认不出返回 None（调用方拒绝该条）。"""
    return _POS_CANON.get(token.strip().strip(".").lower())


def parse_hongbaoshu(field: str | None) -> tuple[str | None, str | None] | None:
    """`放弃， 放置不管 (vt.)` → `("vt", "放弃， 放置不管")`。

    也接 `艺术 (n.) - 创造性表现`（词性组后跟 ` - ` 说明段）与
    `广播 (n./vt.)`（斜杠并列词性）—— 三种都是实测出现最多的形状。

    返回 None = 拒绝这条。拒绝条件（**不是清洗**）：
    - 括号组不恰好一个 —— 形状不认得就别猜；
    - 组后既不是句尾也不是 ` - ` 说明段 —— 同上；
    - 组里有认不出的词性 token —— 宁可整条丢掉，也不写一个可能错的 pos；
    - 释义部分没有汉字 —— 空释义对判 `MEANING_AUTHORITY` 没有帮助。

    多词性（`(noun, vt.)` / `(n./vt.)`）取**第一个**：词表已按义项重要性排序，
    第一即主义项，这与 coca20k 导入器「取首个义项」的既有口径一致。
    """
    raw = (field or "").strip()
    if not raw:
        return None
    groups = list(_HB_GROUP.finditer(raw))
    if len(groups) != 1:
        return None
    m = groups[0]
    tail = raw[m.end() :].strip()
    if tail and not _HB_NOTE.match(tail):
        return None
    tokens = [t for t in re.split(r"[,/]", m.group(1)) if t.strip()]
    if not tokens:
        return None
    canon = [_canon_pos(t) for t in tokens]
    if any(c is None for c in canon):
        return None
    gloss = raw[: m.start()].strip(" 　-—·")
    if not _CJK.search(gloss):
        return None
    return canon[0], gloss


def parse_oxford5000(field: str | None) -> list[tuple[str, str]] | None:
    """`v. （不顾责任…）离弃…; n. 【正式】放任; 时态:abandoned…` → 多义项。

    返回 None = 拒绝这条。四种拒绝：
    1. 截断的 `adv.`（`ad; v.` / `ad, v.`）—— **不做修复**，见 docstring；
    2. 截掉尾部派生词段后仍找不到词性标签；
    3. 释义部分无汉字，或含抽取器残渣；
    4. 释义里粘进了英文（`抵销Balance天秤星座`）—— 百科尾巴，非义项。

    尾部 `时态:` 段是**删除非释义内容**（不是改释义），故在这里截断而非拒绝。
    """
    raw = (field or "").strip()
    if not raw:
        return None
    if _OX_BROKEN_ADV.match(raw):
        return None
    cut = _OX_TAIL.split(raw)[0].strip()
    if not cut or _OX_EXTRACTOR_JUNK in cut or not _CJK.search(cut):
        return None
    if _OX_BROKEN_ADV_MID.search(cut):
        return None
    matches = list(_OX_SENSE.finditer(cut))
    if not matches:
        return None
    senses: list[tuple[str, str]] = []
    for idx, m in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(cut)
        gloss = _OX_COMPOUND_POS.sub("", cut[m.end() : end].strip("；;，,、 　")).strip()
        if gloss:
            senses.append((m.group(1), gloss))
    body = _OX_PAREN.sub("", cut)
    if not senses or _OX_ASCII_GLUE.search(body) or _OX_LONG_LATIN.search(body):
        return None
    return senses


def join_gloss(senses: list[tuple[str, str]]) -> str | None:
    """全部义项合成一行（带词性标签、按行分隔），超 200 字拒掉。

    与 coca20k 导入器同口径：`services.vocab_senses.parse_senses` 按行解析、
    每行可带行首词性标签，写成它认的形状才能被义项选择用到。截断会丢义项，
    所以宁可拒掉并让调用方看见。
    """
    if not senses:
        return None
    text = "\n".join(f"{p}. {g}" for p, g in senses)
    return text if len(text) <= MAX_GLOSS else None


def primary_pos(senses: list[tuple[str, str]]) -> str | None:
    return senses[0][0] if senses else None


def parse_entry(source: str, field: str | None) -> tuple[str | None, str | None]:
    """统一入口：按源选解析器，返回 `(pos, gloss)`，任一为 None 表示不可用。

    hongbaoshu 只有一段释义 +（可能多个）词性，转成单义项好走同一条下游路径。
    """
    if source == "ECHOTYPE_HONGBAOSHU":
        got = parse_hongbaoshu(field)
        if got is None:
            return None, None
        pos, gloss = got
        senses = [(pos, gloss)]
    else:
        senses = parse_oxford5000(field)  # type: ignore[assignment]
        if not senses:
            return None, None
    return primary_pos(senses), join_gloss(senses)  # type: ignore[arg-type]


def load_entries(
    src: Path, tag: str, limit: int | None
) -> tuple[dict[str, dict[str, Any]], Counter]:
    """读一个词表 → `{word: {pos, gloss, line_no}}` + 拒收原因计数。

    同一文件内 `word` 重复时**先出现者胜**（不覆盖），避免后段噪声改写前段已
    解析出的释义。
    """
    rejects: Counter = Counter()
    out: dict[str, dict[str, Any]] = {}
    data = json.loads(src.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else (data.get("words") or data.get("items") or [])
    for idx, row in enumerate(items[: limit or len(items)]):
        word = (row.get("word") or "").strip().lower()
        if not word or word in out:
            if word in out:
                rejects["dup_word"] += 1
            continue
        pos, gloss = parse_entry(tag, row.get("sentence"))
        if not pos and not gloss:
            rejects["rejected_by_parser"] += 1
            continue
        out[word] = {"pos": pos, "gloss": gloss, "line_no": idx + 1, "source": tag}
    return out, rejects


async def run(apply: bool, pos_only: bool, limit: int | None) -> dict[str, Any]:
    from sqlalchemy import text

    from obase.db import SessionLocal

    entries: dict[str, dict[str, Any]] = {}
    rejects: Counter = Counter()
    src_stats = []
    for src, tag in DEFAULT_SOURCES:
        got, rej = load_entries(src, tag, limit)
        # **先出现者胜**（`DEFAULT_SOURCES` 的顺序即优先级）：hongbaoshu 是中高考
        # 词表，释义简洁干净；oxford5000 义项更全但更formal，且带源数据粘接的
        # 百科尾巴。重名时让 hongbaoshu 赢，而不是让后一个源覆盖前一个。
        for word, e in got.items():
            if word in entries:
                rejects["shadowed_by_higher_priority_source"] += 1
                continue
            entries[word] = e
        rejects.update(rej)
        src_stats.append(
            {
                "source": tag,
                "file": src.name,
                "parsed": len(got),
                **{f"reject_{k}": v for k, v in rej.items()},
            }
        )

    pos_plan: list[dict[str, str]] = []
    gloss_plan: list[dict[str, str]] = []

    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
            SELECT DISTINCT ON (lower(btrim(v.word)))
                   v.id, lower(btrim(v.word)) AS word,
                   btrim(coalesce(v.pos, '')) AS pos,
                   btrim(coalesce(v.meaning_cn, '')) AS mc,
                   btrim(coalesce(v.canonical_meaning, '')) AS cm,
                   g.gloss AS dg,
                   k.gloss AS kg
            FROM vocabulary_items v
            JOIN vocabulary_collection_memberships m ON m.vocabulary_item_id = v.id
            LEFT JOIN vocabulary_derived_glosses g ON g.vocabulary_item_id = v.id
            LEFT JOIN vocabulary_dictionary_glosses k ON k.vocabulary_item_id = v.id
            WHERE m.collection_id = :coll AND v.word ~ '^[A-Za-z][A-Za-z-]*$'
            ORDER BY lower(btrim(v.word)), v.id
            """
                ),
                {"coll": COLLECTION},
            )
        ).all()

        from services.vocab_meaning import classify_meaning_source

        for r in rows:
            e = entries.get(r.word)
            if not e:
                continue
            if not r.pos and e["pos"]:
                pos_plan.append({"id": r.id, "word": r.word, "pos": e["pos"]})
            if pos_only or not e["gloss"]:
                continue
            verdict = classify_meaning_source(
                meaning_cn=r.mc,
                canonical_meaning=r.cm,
                derived_gloss=r.dg,
                # **必须把已有的词典释义喂进去**：coca20k 那一轮已经写了 274 行，
                # 不读这张表就会把它们重新算进计划（实测 197 条计划里 186 条其实
                # 早已有词典释义，靠 `ON CONFLICT DO NOTHING` 才没覆盖掉）。
                # 喂进去之后本脚本对「已跑过的词」幂等：再跑一次计划应为 0。
                dictionary_gloss=r.kg,
            )
            if not verdict.usable:
                gloss_plan.append(
                    {
                        "vocabulary_item_id": r.id,
                        "word": r.word,
                        "gloss": e["gloss"],
                        "source": e["source"],
                        "source_ref": f"{e['source']}:{e['line_no']}",
                    }
                )

    if limit:
        pos_plan = pos_plan[:limit]
        gloss_plan = gloss_plan[:limit]

    pos_written = gloss_written = 0
    if apply:
        async with SessionLocal() as db:
            for row in pos_plan:
                res = await db.execute(
                    text("UPDATE vocabulary_items SET pos = :p WHERE id = :v"),
                    {"p": row["pos"], "v": row["id"]},
                )
                pos_written += res.rowcount or 0
            for g in gloss_plan:
                res = await db.execute(
                    text(
                        """
                    INSERT INTO vocabulary_dictionary_glosses
                        (vocabulary_item_id, gloss, source, source_ref)
                    VALUES (:v, :g, :src, :ref)
                    ON CONFLICT (vocabulary_item_id) DO NOTHING
                    """
                    ),
                    {
                        "v": g["vocabulary_item_id"],
                        "g": g["gloss"],
                        "src": g["source"],
                        "ref": g["source_ref"],
                    },
                )
                gloss_written += res.rowcount or 0
            await db.commit()

    overlong = [w for w, e in entries.items() if e["pos"] and not e["gloss"]]
    return {
        "summary": {
            "sources": src_stats,
            "parsed_entries": len(entries),
            "core_words": len(rows),
            "pos_plan": len(pos_plan),
            "gloss_plan": len(gloss_plan),
            "pos_no_gloss_overlong": len(overlong),
            "applied": apply,
            "pos_written": pos_written,
            "gloss_written": gloss_written,
        },
        "pos_plan": [{"word": r["word"], "pos": r["pos"]} for r in pos_plan],
        "gloss_plan": gloss_plan,
        "pos_no_gloss_sample": overlong[:15],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="EchoType 红宝书/牛津5000 → pos/词典释义")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pos-only", action="store_true", help="只填 pos，不写词典释义")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument(
        "--out",
        type=Path,
        default=_REPO_ROOT
        / "reports"
        / "vocab_memory_p0"
        / "dict_from_hongbaoshu_oxford5000.json",
    )
    args = ap.parse_args()

    for src, _tag in DEFAULT_SOURCES:
        if not src.exists():
            print(f"源文件不存在：{src}", file=sys.stderr)
            raise SystemExit(1)

    rep = asyncio.run(run(args.apply, args.pos_only, args.limit or None))
    s = rep["summary"]
    print("逐源解析结果：")
    for st in s["sources"]:
        rej = {k: v for k, v in st.items() if k.startswith("reject_")}
        print(
            f"  {st['source']:<26} 解析 {st['parsed']:>5}  拒收 {rej or '{}'}"
        )
    print(f"\n核心词              {s['core_words']}")
    print(f"可填 pos 空位       {s['pos_plan']}")
    print(f"可填词典释义        {s['gloss_plan']}  （只填当前完全无可用释义的词）")
    if s["applied"]:
        print(f"已写库              pos {s['pos_written']} 行 / 词典释义 {s['gloss_written']} 行")
    else:
        print("[dry-run] 不写库")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {"generated_at": datetime.now(timezone.utc).isoformat(), **rep},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"明细: {args.out}")
    print("\npos 抽样:", ", ".join(f"{r['word']}={r['pos']}" for r in rep["pos_plan"][:10]))
    for g in rep["gloss_plan"][:3]:
        print(f"\n{g['word']} ({g['source_ref']}):\n{g['gloss'][:160]}")


if __name__ == "__main__":
    main()