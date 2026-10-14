"""语文确定性答题（无 LLM）：拼音注音、古诗词默写/出处、成语释义。

入口：``chinese_lookup_solve(text) -> dict | None``（同步、毫秒级、永不抛）。
字段与精确内核一致 {kernel, answer, steps, hint, explanation}，外加可选 ``card``。

数据（均为宽松许可）：
- 拼音：pypinyin（MIT，自带词典，随镜像安装）；
- 诗词：chinese-poetry（MIT）构建的 poetry.sqlite（全唐诗/全宋诗/宋词/元曲/诗经/楚辞/曹操诗集，繁转简）；
- 成语：chinese-xinhua idiom.json（MIT）构建的 idiom.sqlite。
数据缺失时对应功能返回 None。

kernel 取值：chinese.pinyin / chinese.poem / chinese.idiom
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

from services.ask_providers._data import connect

_HAN = r"\u3400-\u9fff"
_BLANK_RE = re.compile(r"_{2,}|＿{2,}|\(\s*\)|（\s*）|﹍{2,}|…{2,}|—{3,}|-{4,}")
_CLAUSE_SPLIT = re.compile(r"([，。？！；：、,.?!;:\n])")

# 统编版初中古诗词（部分，名家名篇）——同句多出处时优先这些（标题, 作者）
# 统编教材用的版本与《全唐诗》原文不同的名篇：卡片/答案按课本写法（学生默写按课本判）
TEXTBOOK_BODY: dict[tuple[str, str], str] = {
    ("静夜思", "李白"): "床前明月光，疑是地上霜。\n举头望明月，低头思故乡。",
}

CURRICULUM: set[tuple[str, str]] = {
    ("观沧海", "曹操"), ("龟虽寿", "曹操"), ("闻王昌龄左迁龙标遥有此寄", "李白"), ("次北固山下", "王湾"),
    ("天净沙·秋思", "马致远"), ("峨眉山月歌", "李白"), ("江南逢李龟年", "杜甫"), ("行军九日思长安故园", "岑参"),
    ("夜上受降城闻笛", "李益"), ("秋词", "刘禹锡"), ("夜雨寄北", "李商隐"), ("十一月四日风雨大作", "陆游"),
    ("潼关", "谭嗣同"), ("竹里馆", "王维"), ("春夜洛城闻笛", "李白"), ("逢入京使", "岑参"), ("晚春", "韩愈"),
    ("登幽州台歌", "陈子昂"), ("望岳", "杜甫"), ("登飞来峰", "王安石"), ("游山西村", "陆游"),
    ("己亥杂诗", "龚自珍"), ("泊秦淮", "杜牧"), ("贾生", "李商隐"), ("过松源晨炊漆公店", "杨万里"),
    ("约客", "赵师秀"), ("野望", "王绩"), ("黄鹤楼", "崔颢"), ("使至塞上", "王维"), ("渡荆门送别", "李白"),
    ("钱塘湖春行", "白居易"), ("庭中有奇树", "佚名"), ("龟虽寿", "曹操"), ("赠从弟", "刘桢"),
    ("梁甫行", "曹植"), ("春望", "杜甫"), ("雁门太守行", "李贺"), ("赤壁", "杜牧"), ("渔家傲", "李清照"),
    ("浣溪沙", "晏殊"), ("采桑子", "欧阳修"), ("相见欢", "朱敦儒"), ("如梦令", "李清照"),
    ("关雎", "佚名"), ("蒹葭", "佚名"), ("式微", "佚名"), ("子衿", "佚名"), ("送杜少府之任蜀州", "王勃"),
    ("茅屋为秋风所破歌", "杜甫"), ("卖炭翁", "白居易"), ("石壕吏", "杜甫"), ("饮酒", "陶渊明"),
    ("春望", "杜甫"), ("望洞庭湖赠张丞相", "孟浩然"), ("早春呈水部张十八员外", "韩愈"), ("咸阳城东楼", "许浑"),
    ("无题", "李商隐"), ("行路难", "李白"), ("酬乐天扬州初逢席上见赠", "刘禹锡"), ("水调歌头", "苏轼"),
    ("月夜忆舍弟", "杜甫"), ("长沙过贾谊宅", "刘长卿"), ("左迁至蓝关示侄孙湘", "韩愈"), ("商山早行", "温庭筠"),
    ("咸阳城东楼", "许浑"), ("南安军", "文天祥"), ("过零丁洋", "文天祥"), ("山坡羊·潼关怀古", "张养浩"),
    ("渔家傲·秋思", "范仲淹"), ("江城子·密州出猎", "苏轼"), ("破阵子·为陈同甫赋壮词以寄之", "辛弃疾"),
    ("满江红", "秋瑾"), ("定风波", "苏轼"), ("临江仙", "陈与义"), ("太常引", "辛弃疾"), ("浣溪沙", "纳兰性德"),
    ("静夜思", "李白"), ("凉州词", "王之涣"), ("凉州词二首 一", "王之涣"), ("出塞", "王昌龄"),
    ("登鹳雀楼", "王之涣"), ("春晓", "孟浩然"), ("望庐山瀑布", "李白"), ("早发白帝城", "李白"),
    ("题西林壁", "苏轼"), ("示儿", "陆游"), ("泊船瓜洲", "王安石"), ("望天门山", "李白"),
}


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").strip()


def _han_only(s: str) -> str:
    return re.sub(rf"[^{_HAN}]", "", s)


# ── 拼音 ─────────────────────────────────────────────────────────────────────

_PINYIN_TRIGGER = re.compile(r"注音|拼音|读音|怎么读|念什么|读什么|多音字|加点字")


def pinyin_items(text: str) -> list[dict]:
    from pypinyin import Style, pinyin

    out: list[dict] = []
    for seg in re.findall(rf"[{_HAN}]+", text):
        pys = pinyin(seg, style=Style.TONE, heteronym=False, errors="ignore")
        for ch, py in zip(seg, pys):
            out.append({"char": ch, "pinyin": py[0] if py else ""})
    return out


def _heteronyms(ch: str) -> list[str]:
    from pypinyin import Style, pinyin

    r = pinyin(ch, style=Style.TONE, heteronym=True)
    return list(dict.fromkeys(r[0])) if r else []


def _solve_pinyin(t: str) -> Optional[dict]:
    if not _PINYIN_TRIGGER.search(t):
        return None
    target = t
    m = re.search(r"[:：](.+)$", t, re.S)
    if m:
        target = m.group(1)
    else:
        q = re.search(r"[“\"「『‘']([^”\"」』’']+)[”\"」』’']", t)
        if q:
            target = q.group(1)
        else:
            target = re.sub(r"(给下列|下列|加点字|加点的字|注音|拼音|读音|的|怎么读|念什么|读什么|是什么|多音字|请|写出|标出|\?|？)", " ", t)
    words = re.findall(rf"[{_HAN}]+", target)
    if not words:
        return None
    try:
        items = pinyin_items(" ".join(words))
    except Exception:  # noqa: BLE001 — pypinyin 未安装
        return None
    if not items:
        return None
    pos = 0
    parts = []
    for w in words:
        seg = items[pos: pos + len(w)]
        pos += len(w)
        parts.append(f"{w}（{' '.join(i['pinyin'] for i in seg)}）")
    steps = ["逐字注音（按词语里的读音，多音字以词语为准）：", *parts]
    if len(words) == 1 and len(words[0]) == 1:
        hs = _heteronyms(words[0])
        if len(hs) > 1:
            steps.append(f"「{words[0]}」是多音字：{' / '.join(hs)}，要看词语确定读音。")
    return {
        "kernel": "chinese.pinyin",
        "answer": "；".join(parts),
        "steps": steps,
        "hint": "多音字要放在词语里读，注意声调标在主要元音上。",
        "explanation": "考点：字音（拼音与声调）。",
        "card": {"type": "pinyin", "items": items},
    }


# ── 古诗词 ───────────────────────────────────────────────────────────────────


def _clauses(body: str) -> list[str]:
    out = []
    for para in body.split("\n"):
        for c in re.split(r"[，。？！；：、,.?!;:]", para):
            n = _han_only(c)
            if len(n) >= 2:
                out.append(n)
    return out


def _poem(db: Any, pid: int) -> Optional[Any]:
    return db.execute("SELECT * FROM poems WHERE id = ?", (pid,)).fetchone()


def _find_candidates(db: Any, clause: str) -> list[tuple[int, int, int]]:
    """(poem_id, idx, 编辑距离)。先精确匹配，再同长度首/尾两字召回后算汉明距离（容 OCR 认错 1 个字）。"""
    rows = db.execute("SELECT poem_id, idx FROM clauses WHERE norm = ? LIMIT 200", (clause,)).fetchall()
    if rows:
        return [(int(r["poem_id"]), int(r["idx"]), 0) for r in rows]
    if len(clause) < 4:
        return []
    cand: dict[tuple[int, int], int] = {}
    for col, key in (("head", clause[:2]), ("tail", clause[-2:])):
        for r in db.execute(
            f"SELECT poem_id, idx, norm FROM clauses WHERE {col} = ? AND len = ? LIMIT 3000", (key, len(clause))
        ).fetchall():
            d = sum(1 for a, b in zip(r["norm"], clause) if a != b)
            if d <= max(1, len(clause) // 5):
                cand[(int(r["poem_id"]), int(r["idx"]))] = d
    return [(p, i, d) for (p, i), d in cand.items()]


def _is_quote(poem: Any) -> bool:
    """僧人偈颂/颂古常整句引用名句：不能当出处。"""
    t = str(poem["title"] or "")
    return "偈" in t or "颂古" in t or str(poem["author"] or "").startswith("释")


def _score(poem: Any, dist: int) -> float:
    s = float(poem["rank"] or 0.0) - 3.0 * dist - (6.0 if _is_quote(poem) else 0.0)
    if (poem["title"], poem["author"]) in CURRICULUM or any(
        poem["author"] == a and str(poem["title"]).startswith(t.split("·")[0]) for t, a in CURRICULUM
    ):
        s += 6.0
    return s


def _parse_question(t: str) -> list[tuple[str, str]]:
    """把题面切成 [(kind, text)]，kind ∈ {'known','blank'}（按出现顺序，标点分句）。"""
    t = re.sub(r"^\s*(\d+[.．、]\s*)?(古诗(文)?默写|默写|补写|填空|名句填空|根据(上|下)文填空|写出|补全)[:：]?", "", t)
    t = _BLANK_RE.sub("〔空〕", t)
    # 提问用语不是诗句：「床前明月光的下一句」「……出自哪首诗？」
    t = re.sub(
        r"(的)?(上一句|下一句|上句|下句|前一句|后一句)(是什么|是)?|(这句诗|这句|此句)?(出自哪首诗|出自哪里|出自|的出处|出处)"
        r"|(是)?谁写的|作者是谁|哪位诗人(写的)?|请写出|是什么",
        "，",
        t,
    )
    out: list[tuple[str, str]] = []
    for piece in re.split(r"[，。？！；：、,.?!;:\n]", t):
        if "〔空〕" in piece:
            # 中学默写都是整句挖空；OCR 偶尔吞掉空后的逗号（「〔空〕春风不度玉门关」）→ 拆成 空 + 已知句
            segs = piece.split("〔空〕")
            for k, seg in enumerate(segs):
                n = _han_only(seg)
                if len(n) >= 3:
                    out.append(("known", n))
                if k < len(segs) - 1:
                    out.append(("blank", ""))
            continue
        n = _han_only(piece)
        if len(n) >= 3:
            out.append(("known", n))
    return out


def _solve_poem(t: str) -> Optional[dict]:
    db = connect("poetry")
    if db is None:
        return None
    parts = _parse_question(t)
    known = [(i, p[1]) for i, p in enumerate(parts) if p[0] == "known"]
    blanks = [i for i, p in enumerate(parts) if p[0] == "blank"]
    want_next = bool(re.search(r"下一句|下句|后一句", t))
    want_prev = bool(re.search(r"上一句|上句|前一句", t))
    want_src = bool(re.search(r"出自|出处|哪首诗|作者|谁写的|哪位诗人", t))
    if not known:
        return None
    if not blanks and not (want_next or want_prev or want_src):
        # 只有诗句本身：整段都是诗句（≥2 个分句或单句 ≥5 字）才当出处查询，避免普通中文句子误命中
        if len(known) < 2 and len(known[0][1]) < 5:
            return None
        han = len(_han_only(t))
        if han > sum(len(k) for _, k in known) + 6:
            return None
    # 每个已知分句召回候选；同一首诗、位置偏移一致的候选累积打分
    votes: dict[tuple[int, int], list[int]] = {}
    for qi, clause in known:
        for pid, idx, dist in _find_candidates(db, clause):
            votes.setdefault((pid, idx - qi), []).append(dist)
    if not votes:
        return None
    best = None
    for (pid, offset), dists in votes.items():
        poem = _poem(db, pid)
        if poem is None:
            continue
        sc = 10.0 * len(dists) + _score(poem, sum(dists))
        if best is None or sc > best[0]:
            best = (sc, pid, offset, poem, dists)
    if best is None:
        return None
    _, pid, offset, poem, dists = best
    if len(known) >= 2 and len(dists) < 2 and not blanks:
        return None
    body = TEXTBOOK_BODY.get((str(poem["title"]), str(poem["author"])), str(poem["body"]))
    clauses = _clauses(body)
    answers: list[str] = []
    for bi in blanks:
        ci = bi + offset
        if 0 <= ci < len(clauses):
            answers.append(clauses[ci])
    if blanks and len(answers) != len(blanks):
        return None
    hl_idx: list[int] = [bi + offset for bi in blanks]
    if not blanks and (want_next or want_prev):
        last_q = known[-1][0] if want_next else known[0][0]
        ci = last_q + offset + (1 if want_next else -1)
        if 0 <= ci < len(clauses):
            answers.append(clauses[ci])
            hl_idx = [ci]
    quote_only = _is_quote(poem)
    if quote_only:
        src = "一首引用了这句名句的作品（原作暂未收录，出处以课本为准）"
    else:
        src = f"{poem['dynasty']}·{poem['author']}《{poem['title']}》" if poem["author"] else f"《{poem['title']}》"
    lines = [ln for ln in body.split("\n") if ln.strip()]
    # 高亮：答案所在的行
    hl_lines: list[int] = []
    pos = 0
    for li, ln in enumerate(lines):
        n = len(_clauses(ln))
        if any(pos <= h < pos + n for h in hl_idx):
            hl_lines.append(li)
        pos += n
    if quote_only and not answers:
        return None
    if answers:
        answer = "；".join(answers)
        steps = [f"这句出自 {src}。" if not quote_only else f"在{src}里找到了这句。", f"答案：{answer}"]
    else:
        answer = f"出自 {src}"
        steps = [answer]
    if not quote_only:
        steps.append("全诗：" + "".join(lines[:16]) + ("……" if len(lines) > 16 else ""))
    return {
        "kernel": "chinese.poem",
        "answer": answer,
        "steps": steps,
        "hint": ("想一想这句诗出自哪首诗？" + ("" if quote_only else f"提示：作者是{poem['author'] or '佚名'}。")),
        "explanation": "考点：古诗文默写。注意易错字，写完对照原文逐字检查。",
        "card": {
            "type": "poem",
            "title": None if quote_only else poem["title"],
            "author": None if quote_only else poem["author"],
            "dynasty": None if quote_only else poem["dynasty"],
            "lines": [] if quote_only else lines[:40],
            "highlight": hl_lines[0] if hl_lines else None,
            "highlights": hl_lines,
            "answer": answer if answers else None,
        },
    }


# ── 成语 ─────────────────────────────────────────────────────────────────────

_IDIOM_TRIGGER = re.compile(r"成语|意思|解释|含义|出处|典故|是什么|造句|近义|反义")


def lookup_idiom(word: str) -> Optional[dict]:
    db = connect("idiom")
    if db is None:
        return None
    r = db.execute("SELECT * FROM idioms WHERE word = ?", (word,)).fetchone()
    if r is None:
        return None
    return {
        "type": "idiom",
        "word": r["word"],
        "pinyin": r["pinyin"],
        "explanation": r["explanation"],
        "derivation": r["derivation"] or None,
        "example": (r["example"] or None) if (r["example"] or "").strip() not in {"无", ""} else None,
    }


def _solve_idiom(t: str) -> Optional[dict]:
    han = re.findall(rf"[{_HAN}]+", t)
    if not han:
        return None
    cands: list[str] = []
    q = re.search(r"[“\"「『]([^”\"」』]+)[”\"」』]", t)
    if q:
        cands.append(_han_only(q.group(1)))
    for seg in han:
        cands.append(seg)
        # 「刻舟求剑是什么意思」→ 取前 4~8 字试
        for n in (4, 5, 6, 7, 8):
            if len(seg) > n:
                cands.append(seg[:n])
    whole = _han_only(t)
    only_idiom = len(whole) <= 8
    if not only_idiom and not _IDIOM_TRIGGER.search(t):
        return None
    for c in dict.fromkeys(cands):
        if len(c) < 3:
            continue
        card = lookup_idiom(c)
        if card:
            steps = [f"读音：{card['pinyin']}", f"意思：{card['explanation']}"]
            if card.get("derivation"):
                steps.append(f"出处：{card['derivation']}")
            if card.get("example"):
                steps.append(f"例句：{card['example']}")
            return {
                "kernel": "chinese.idiom",
                "answer": card["explanation"],
                "steps": steps,
                "hint": "先拆开看每个字的意思，再想想整个成语的比喻义。",
                "explanation": f"「{card['word']}」：{card['explanation']}",
                "card": card,
            }
    return None


def chinese_lookup_solve(text: str) -> Optional[dict]:
    """语文确定性求解。不适用返回 None；永不抛。"""
    try:
        t = _norm(text)
        if not t or len(t) > 800 or not re.search(rf"[{_HAN}]", t):
            return None
        if re.search(r"[A-Za-z]{3,}", t) and len(re.findall(r"[A-Za-z]", t)) > len(re.findall(rf"[{_HAN}]", t)):
            return None
        for fn in (_solve_pinyin, _solve_poem, _solve_idiom):
            out = fn(t)
            if out:
                return out
        return None
    except Exception:  # noqa: BLE001 — provider 绝不打断主流程
        return None


__all__ = ["CURRICULUM", "chinese_lookup_solve", "lookup_idiom", "pinyin_items"]
