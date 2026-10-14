"""英语确定性答题（无 LLM）：查词、词形变化、不规则动词、初中常见语法纠错、语法单选。

入口：``english_lookup_solve(text) -> dict | None``（同步、毫秒级、永不抛）。
返回与精确内核一致的字段 {kernel, answer, steps, hint, explanation}，外加可选 ``card``（前端卡片）。
不适用（不是英语题 / 拿不准）返回 None，交给后面的 provider 或 LLM。

数据：ECDICT（MIT，skywind3000/ECDICT），由 scripts/ask_data/fetch_and_build.py 构建成 ecdict.sqlite；
数据缺失时查词不可用，但不规则动词表 / 构词规则 / 语法规则仍可用（纯代码）。

kernel 取值：english.word / english.inflection / english.grammar / english.choice
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

from services.ask_providers._data import connect

# ── 不规则动词（初中常用，base past pp）────────────────────────────────────────
_IRREGULAR_RAW = """
be was/were been|bear bore born|beat beat beaten|become became become|begin began begun|bend bent bent
bet bet bet|bite bit bitten|blow blew blown|break broke broken|bring brought brought|build built built
burn burnt/burned burnt/burned|buy bought bought|catch caught caught|choose chose chosen|come came come
cost cost cost|cut cut cut|dig dug dug|do did done|draw drew drawn|dream dreamt/dreamed dreamt/dreamed
drink drank drunk|drive drove driven|eat ate eaten|fall fell fallen|feed fed fed|feel felt felt
fight fought fought|find found found|fly flew flown|forget forgot forgotten|forgive forgave forgiven
freeze froze frozen|get got got/gotten|give gave given|go went gone|grow grew grown|hang hung hung
have had had|hear heard heard|hide hid hidden|hit hit hit|hold held held|hurt hurt hurt|keep kept kept
know knew known|lay laid laid|lead led led|learn learnt/learned learnt/learned|leave left left|lend lent lent
let let let|lie lay lain|light lit lit|lose lost lost|make made made|mean meant meant|meet met met
pay paid paid|put put put|read read read|ride rode ridden|ring rang rung|rise rose risen|run ran run
say said said|see saw seen|sell sold sold|send sent sent|set set set|shake shook shaken|shine shone shone
shoot shot shot|show showed shown|shut shut shut|sing sang sung|sink sank sunk|sit sat sat|sleep slept slept
smell smelt/smelled smelt/smelled|speak spoke spoken|spell spelt/spelled spelt/spelled|spend spent spent
spread spread spread|stand stood stood|steal stole stolen|stick stuck stuck|sting stung stung
strike struck struck|swim swam swum|swing swung swung|take took taken|teach taught taught|tear tore torn
tell told told|think thought thought|throw threw thrown|understand understood understood|wake woke woken
wear wore worn|win won won|write wrote written|can could -|may might -|will would -|shall should -
""".strip()


def _parse_irregular() -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for chunk in _IRREGULAR_RAW.replace("\n", "|").split("|"):
        parts = chunk.split()
        if len(parts) == 3:
            out[parts[0]] = (parts[1], parts[2])
    return out


IRREGULAR_VERBS = _parse_irregular()
_PAST2BASE: dict[str, str] = {}
for _b, (_p, _pp) in IRREGULAR_VERBS.items():
    for _f in _p.split("/") + _pp.split("/"):
        if _f != "-" and _f != _b:
            _PAST2BASE.setdefault(_f, _b)

IRREGULAR_PLURALS = {
    "man": "men", "woman": "women", "child": "children", "foot": "feet", "tooth": "teeth", "mouse": "mice",
    "goose": "geese", "sheep": "sheep", "deer": "deer", "fish": "fish", "ox": "oxen", "person": "people",
    "chinese": "Chinese", "japanese": "Japanese", "potato": "potatoes", "tomato": "tomatoes", "hero": "heroes",
    "knife": "knives", "leaf": "leaves", "wife": "wives", "life": "lives", "half": "halves", "wolf": "wolves",
    "thief": "thieves", "shelf": "shelves", "photo": "photos", "piano": "pianos", "zoo": "zoos", "radio": "radios",
    "policeman": "policemen", "postman": "postmen", "mouth": "mouths",
}
IRREGULAR_COMPARE = {
    "good": ("better", "best"), "well": ("better", "best"), "bad": ("worse", "worst"), "ill": ("worse", "worst"),
    "many": ("more", "most"), "much": ("more", "most"), "little": ("less", "least"), "far": ("farther/further", "farthest/furthest"),
    "old": ("older/elder", "oldest/eldest"),
}
_VOWELS = "aeiou"


def third_person(verb: str) -> str:
    v = verb.lower()
    special = {"be": "is", "have": "has", "do": "does", "go": "goes"}
    if v in special:
        return special[v]
    ex = _exchange(v).get("3")
    if ex:
        return ex
    if re.search(r"(s|x|z|ch|sh|o)$", v):
        return v + "es"
    if re.search(r"[^aeiou]y$", v):
        return v[:-1] + "ies"
    return v + "s"


def _double_final(v: str) -> bool:
    # 重读闭音节（简化：单音节 辅-元-辅 结尾，且末尾不是 w/x/y）
    return bool(re.fullmatch(r"[^aeiou]*[aeiou][^aeiouwxy]", v))


def past_form(verb: str) -> str:
    v = verb.lower()
    if v in IRREGULAR_VERBS:
        return IRREGULAR_VERBS[v][0]
    ex = _exchange(v).get("p")
    if ex:
        return ex
    if v.endswith("e"):
        return v + "d"
    if re.search(r"[^aeiou]y$", v):
        return v[:-1] + "ied"
    if _double_final(v):
        return v + v[-1] + "ed"
    return v + "ed"


def past_participle(verb: str) -> str:
    v = verb.lower()
    if v in IRREGULAR_VERBS:
        return IRREGULAR_VERBS[v][1]
    ex = _exchange(v).get("d")
    return ex or past_form(v)


def ing_form(verb: str) -> str:
    v = verb.lower()
    ex = _exchange(v).get("i")
    if ex:
        return ex
    special = {"lie": "lying", "die": "dying", "tie": "tying", "be": "being", "see": "seeing"}
    if v in special:
        return special[v]
    if v.endswith("ie"):
        return v[:-2] + "ying"
    if v.endswith("e") and not v.endswith("ee"):
        return v[:-1] + "ing"
    if _double_final(v):
        return v + v[-1] + "ing"
    return v + "ing"


def plural(noun: str) -> str:
    n = noun.lower()
    if n in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[n]
    ex = _exchange(n).get("s")
    if ex:
        return ex
    if re.search(r"(s|x|z|ch|sh)$", n):
        return n + "es"
    if re.search(r"[^aeiou]y$", n):
        return n[:-1] + "ies"
    if re.search(r"(f|fe)$", n):
        return re.sub(r"(f|fe)$", "ves", n)
    return n + "s"


def comparative(adj: str) -> tuple[str, str]:
    a = adj.lower()
    if a in IRREGULAR_COMPARE:
        return IRREGULAR_COMPARE[a]
    ex = _exchange(a)
    if ex.get("r") and ex.get("t"):
        return ex["r"], ex["t"]
    syll = len(re.findall(r"[aeiouy]+", a.rstrip("e"))) or 1
    if syll >= 3 or (syll == 2 and not a.endswith(("y", "er", "ow", "le"))):
        return f"more {a}", f"most {a}"
    if a.endswith("e"):
        return a + "r", a + "st"
    if re.search(r"[^aeiou]y$", a):
        return a[:-1] + "ier", a[:-1] + "iest"
    if _double_final(a):
        return a + a[-1] + "er", a + a[-1] + "est"
    return a + "er", a + "est"


# ── ECDICT ───────────────────────────────────────────────────────────────────

_TAGS = {"zk": "中考", "gk": "高考", "cet4": "四级", "cet6": "六级", "ky": "考研", "toefl": "托福", "ielts": "雅思", "gre": "GRE"}
_EXCHANGE_LABEL = {"p": "过去式", "d": "过去分词", "i": "现在分词", "3": "第三人称单数", "s": "复数", "r": "比较级", "t": "最高级", "0": "原形"}


def _row(word: str) -> Optional[Any]:
    db = connect("ecdict")
    if db is None or not word:
        return None
    try:
        return db.execute("SELECT * FROM words WHERE word = ? COLLATE NOCASE", (word,)).fetchone()
    except Exception:  # noqa: BLE001
        return None


def _exchange(word: str) -> dict[str, str]:
    r = _row(word)
    if r is None or not r["exchange"]:
        return {}
    out: dict[str, str] = {}
    for part in str(r["exchange"]).split("/"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k] = v
    return out


def lemma_of(word: str) -> Optional[tuple[str, str]]:
    """变形 → (原形, 变形种类)。先查不规则表，再查 ECDICT forms 表。"""
    w = word.lower()
    if w in _PAST2BASE:
        base = _PAST2BASE[w]
        p, pp = IRREGULAR_VERBS[base]
        return base, ("p" if w in p.split("/") else "d")
    db = connect("ecdict")
    if db is not None:
        try:
            r = db.execute("SELECT lemma, kind FROM forms WHERE form = ? COLLATE NOCASE LIMIT 1", (w,)).fetchone()
        except Exception:  # noqa: BLE001
            r = None
        if r is not None:
            return str(r["lemma"]), str(r["kind"])
    return None


def lookup_word(word: str) -> Optional[dict]:
    r = _row(word)
    lem = None
    if r is None:
        lem = lemma_of(word)
        if lem:
            r = _row(lem[0])
    if r is None:
        return None
    meanings = [m.strip() for m in str(r["translation"] or "").split("\n") if m.strip()][:6]
    ex = {}
    for part in str(r["exchange"] or "").split("/"):
        if ":" in part:
            k, v = part.split(":", 1)
            if k in _EXCHANGE_LABEL and k not in {"0", "1"} and v:
                ex[_EXCHANGE_LABEL[k]] = v
    base = str(r["word"])
    if base.lower() in IRREGULAR_VERBS:
        p, pp = IRREGULAR_VERBS[base.lower()]
        ex.setdefault("过去式", p)
        if pp != "-":
            ex.setdefault("过去分词", pp)
    tags = [_TAGS[t] for t in str(r["tag"] or "").split() if t in _TAGS]
    return {
        "type": "english_word",
        "word": base,
        "query": word,
        "lemma_of": ({"form": word, "kind": _EXCHANGE_LABEL.get(lem[1], lem[1])} if lem else None),
        "phonetic": str(r["phonetic"] or ""),
        "meanings": meanings,
        "inflections": ex,
        "tags": tags,
    }


# ── 语法规则 ─────────────────────────────────────────────────────────────────

_THIRD = {"he", "she", "it"}
_NON_THIRD = {"i", "we", "you", "they"}
_MODALS = {"can", "could", "will", "would", "should", "must", "may", "might", "shall"}
_PAST_MARK = re.compile(r"\b(yesterday|ago|last\s+(night|week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekend|term|summer|winter|time)|in\s+(19|20)\d\d|just\s+now|the\s+day\s+before\s+yesterday)\b", re.I)
_FUTURE_MARK = re.compile(r"\b(tomorrow|next\s+(week|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekend|term|time)|in\s+the\s+future|soon)\b", re.I)
_HABIT_MARK = re.compile(r"\b(every\s+(day|morning|evening|week|year|sunday|weekend)|usually|often|always|sometimes|never|on\s+(sundays|weekends|mondays))\b", re.I)
_NOW_MARK = re.compile(r"\b(now|at\s+the\s+moment|right\s+now|look!|listen!)\b", re.I)
_AN_EXCEPT = {"hour", "honest", "honour", "honor", "heir", "hourly"}
_A_EXCEPT_PREFIX = ("uni", "use", "usu", "eu", "one", "once", "ur", "uto")
_NOT_VERB = {"to", "not", "very", "also", "really", "the", "a", "an", "and", "is", "am", "are", "was", "were"}


def _starts_with_vowel_sound(word: str) -> bool:
    w = word.lower()
    if w in _AN_EXCEPT or w.startswith("hour") or w.startswith("honest"):
        return True
    if w.startswith(_A_EXCEPT_PREFIX):
        return False
    if len(w) == 1:  # 字母：an F / an M / a U
        return w in "aefhilmnorsx"
    return w[0] in _VOWELS


def _is_verb_base(w: str) -> bool:
    lw = w.lower()
    if lw in _NOT_VERB or lw in _MODALS:
        return False
    if lw in IRREGULAR_VERBS:
        return True
    r = _row(lw)
    if r is None:
        return False
    pos = str(r["pos"] or "")
    ex = str(r["exchange"] or "")
    return ("3:" in ex or "p:" in ex) and ("v" in pos or pos == "" or "v." in str(r["translation"] or ""))


def check_grammar(sentence: str) -> list[dict]:
    """返回问题列表 [{wrong, right, rule}]。只报确定性高的错误；空列表=没发现问题。"""
    s = sentence.strip()
    toks = re.findall(r"[A-Za-z']+", s)
    low = [t.lower() for t in toks]
    issues: list[dict] = []

    def add(wrong: str, right: str, rule: str) -> None:
        issues.append({"wrong": wrong, "right": right, "rule": rule})

    has_past = bool(_PAST_MARK.search(s))
    has_future = bool(_FUTURE_MARK.search(s))
    for i, w in enumerate(low):
        nxt = low[i + 1] if i + 1 < len(low) else ""
        prev = low[i - 1] if i > 0 else ""
        orig_nxt = toks[i + 1] if i + 1 < len(toks) else ""
        # be 动词一致
        if w == "i" and nxt in {"is", "are"}:
            add(f"I {orig_nxt}", "I am" if not has_past else "I was", "主语是 I，be 动词用 am（过去用 was）")
        elif w in _THIRD and nxt in {"am", "are"}:
            add(f"{toks[i]} {orig_nxt}", f"{toks[i]} is" if not has_past else f"{toks[i]} was", "主语是第三人称单数，be 动词用 is（过去用 was）")
        elif w in {"we", "you", "they"} and nxt in {"is", "am"}:
            add(f"{toks[i]} {orig_nxt}", f"{toks[i]} are" if not has_past else f"{toks[i]} were", "主语是复数或 you，be 动词用 are（过去用 were）")
        elif w in _THIRD | {"i"} and nxt == "were" and "if" not in low[:i] and "wish" not in low[:i]:
            add(f"{toks[i]} were", f"{toks[i]} was", "主语是 I 或第三人称单数，过去式用 was")
        elif w in {"we", "you", "they"} and nxt == "was":
            add(f"{toks[i]} was", f"{toks[i]} were", "主语是复数或 you，过去式用 were")
        # 助动词 do/does 一致
        if w in _THIRD and nxt in {"don't", "do"} and prev not in {"what", "how", "why", "where", "when", "which", "who"}:
            if nxt == "don't" or (i + 2 < len(low) and low[i + 2] == "not"):
                add(f"{toks[i]} {orig_nxt}", f"{toks[i]} doesn't" if nxt == "don't" else f"{toks[i]} does", "主语是第三人称单数，否定用 doesn't")
        if w in _NON_THIRD and nxt == "doesn't":
            add(f"{toks[i]} doesn't", f"{toks[i]} don't", "主语不是第三人称单数，否定用 don't")
        if i == 0 and w == "does" and nxt in _NON_THIRD:
            add(f"Does {orig_nxt}", f"Do {orig_nxt}", "主语不是第三人称单数，疑问句用 Do")
        if i == 0 and w == "do" and nxt in _THIRD:
            add(f"Do {orig_nxt}", f"Does {orig_nxt}", "主语是第三人称单数，疑问句用 Does")
        # 助动词/情态动词后接动词原形
        if w in {"doesn't", "don't", "does", "did", "didn't", "do"} | _MODALS and nxt:
            target = nxt
            if w in {"does", "did", "do"} and i + 2 < len(low) and low[i + 1] in _THIRD | _NON_THIRD:
                target = low[i + 2] if i + 2 < len(low) else ""
            if target == "to" and w in _MODALS:
                add(f"{toks[i]} to", toks[i], "情态动词后直接跟动词原形，不加 to")
            else:
                lem = lemma_of(target) if target else None
                if lem and lem[1] in {"3", "p", "d"} and lem[0] not in {"be"}:
                    add(f"{toks[i]} … {target}", f"{toks[i]} … {lem[0]}", f"{toks[i]} 后面的动词要用原形")
        # a / an
        if w in {"a", "an"} and nxt and orig_nxt.isalpha():
            vowel = _starts_with_vowel_sound(nxt)
            if w == "a" and vowel:
                add(f"a {orig_nxt}", f"an {orig_nxt}", "元音音素开头的词前用 an")
            elif w == "an" and not vowel:
                add(f"an {orig_nxt}", f"a {orig_nxt}", "辅音音素开头的词前用 a")
        # There be
        if w == "there" and nxt == "is" and i + 2 < len(low) and low[i + 2] in {"two", "three", "four", "five", "many", "some", "lots", "a lot", "several"}:
            add("There is", "There are", "There be 后面是复数名词，用 are")
        if w == "there" and nxt == "are" and i + 2 < len(low) and low[i + 2] in {"a", "an", "one"}:
            add("There are", "There is", "There be 后面是单数名词，用 is")
    # 主谓一致（实义动词一般现在时）
    if low:
        subj_i = 0
        if low[0] in _THIRD | _NON_THIRD and len(low) > 1:
            w0, v = low[0], low[1]
            if w0 in _THIRD and _is_verb_base(v) and not has_past and not has_future and v not in {"have"}:
                if lemma_of(v) is None:
                    right = third_person(v)
                    add(f"{toks[0]} {toks[1]}", f"{toks[0]} {right}", "主语是第三人称单数，一般现在时动词加 -s/-es")
            elif w0 in _THIRD and v == "have" and not has_past and not has_future:
                add(f"{toks[0]} have", f"{toks[0]} has", "主语是第三人称单数，have 要变成 has")
            elif w0 in _NON_THIRD:
                lem = lemma_of(v)
                if lem and lem[1] == "3" and lem[0] != "be":
                    add(f"{toks[0]} {toks[1]}", f"{toks[0]} {lem[0]}", "主语不是第三人称单数，动词用原形")
            # 时间状语与时态
            lem = lemma_of(v)
            is_present = (_is_verb_base(v) and lem is None) or (lem is not None and lem[1] == "3")
            if has_past and is_present and v not in _MODALS:
                base = lem[0] if lem else v
                add(f"{toks[0]} {toks[1]}", f"{toks[0]} {past_form(base).split('/')[0]}", "句中有过去的时间（yesterday / … ago / last …），动词用过去式")
            if has_future and lem is not None and lem[1] == "p":
                add(f"{toks[0]} {toks[1]}", f"{toks[0]} will {lem[0]}", "句中有将来的时间（tomorrow / next …），用 will + 动词原形")
            # 主语后直接跟 -ing / 过去分词（缺 be / have）
            if v.endswith("ing") and lem is not None and lem[1] == "i":
                add(f"{toks[0]} {toks[1]}", f"{toks[0]} {'is' if w0 in _THIRD else ('am' if w0 == 'i' else 'are')} {toks[1]}", "现在进行时要有 be 动词（am/is/are + doing）")
            if lem is not None and lem[1] == "d" and past_form(lem[0]) != v:
                add(f"{toks[0]} {toks[1]}", f"{toks[0]} {'has' if w0 in _THIRD else 'have'} {toks[1]}", "过去分词不能单独作谓语（完成时要 have/has + 过去分词）")
        _ = subj_i
    # 去重
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for it in issues:
        k = (it["wrong"].lower(), it["right"].lower())
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


# ── 题型识别 ─────────────────────────────────────────────────────────────────

_BLANK = re.compile(r"_{2,}|\(\s*\)|（\s*）")
_OPTIONS = re.compile(r"(?:^|\s)([A-D])[.．、)]\s*([A-Za-z' ]+?)(?=\s+[A-D][.．、)]|\s*$)", re.M)
_INFL_ZH = [
    (re.compile(r"过去分词"), "d"), (re.compile(r"过去式"), "p"), (re.compile(r"现在分词|-ing ?形式|ing形式"), "i"),
    (re.compile(r"第三人称单数|三单"), "3"), (re.compile(r"复数"), "s"), (re.compile(r"比较级"), "r"),
    (re.compile(r"最高级"), "t"), (re.compile(r"原形"), "0"),
]
_INFL_EN = [
    (re.compile(r"past participle of", re.I), "d"), (re.compile(r"past (tense|form) of", re.I), "p"),
    (re.compile(r"(-ing|ing|present participle) form of", re.I), "i"), (re.compile(r"plural (form )?of", re.I), "s"),
    (re.compile(r"comparative (form )?of", re.I), "r"), (re.compile(r"superlative (form )?of", re.I), "t"),
    (re.compile(r"third person singular (form )?of", re.I), "3"),
]


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return t.strip()


def _english_ratio(t: str) -> tuple[int, int]:
    return len(re.findall(r"[A-Za-z]", t)), len(re.findall(r"[\u4e00-\u9fff]", t))


def _inflect(word: str, kind: str) -> Optional[str]:
    w = word.lower()
    if kind == "p":
        return past_form(w)
    if kind == "d":
        return past_participle(w)
    if kind == "i":
        return ing_form(w)
    if kind == "3":
        return third_person(w)
    if kind == "s":
        return plural(w)
    if kind == "r":
        return comparative(w)[0]
    if kind == "t":
        return comparative(w)[1]
    if kind == "0":
        lem = lemma_of(w)
        return lem[0] if lem else None
    return None


def _solve_inflection(t: str) -> Optional[dict]:
    kind = None
    for pat, k in _INFL_EN:
        if pat.search(t):
            kind = k
            break
    if kind is None:
        for pat, k in _INFL_ZH:
            if pat.search(t):
                kind = k
                break
    if kind is None:
        return None
    m = re.search(r"\bof\s+['\"]?([A-Za-z]+)", t) or re.search(r"([A-Za-z]+)['\"]?\s*的", t)
    if m:
        words = [m.group(1)]
    else:
        words = [w for w in re.findall(r"[A-Za-z]+", t) if w.lower() not in {
            "the", "of", "is", "what", "past", "tense", "form", "participle", "plural", "comparative", "superlative",
            "third", "person", "singular", "present", "ing", "write", "a", "an"}]
    if len(words) != 1:
        return None
    w = words[0]
    ans = _inflect(w, kind)
    if not ans:
        return None
    label = _EXCHANGE_LABEL[kind]
    steps = [f"{w} 的{label}是 {ans}。"]
    lw = w.lower()
    if kind in {"p", "d"}:
        if lw in IRREGULAR_VERBS:
            p, pp = IRREGULAR_VERBS[lw]
            steps.append(f"{w} 是不规则动词：{w} → {p} → {pp}（原形 → 过去式 → 过去分词），要单独记。")
        else:
            steps.append("规则动词：一般加 -ed；以 e 结尾加 -d；辅音字母+y 变 y 为 i 加 -ed；重读闭音节双写末尾辅音再加 -ed。")
    elif kind == "s":
        steps.append("规则：一般加 -s；以 s/x/ch/sh 结尾加 -es；辅音字母+y 变 y 为 i 加 -es；以 f/fe 结尾多变 -ves。" if lw not in IRREGULAR_PLURALS else f"{w} 的复数是不规则变化，要单独记。")
    elif kind in {"r", "t"}:
        steps.append("规则：单音节加 -er/-est；以 e 结尾加 -r/-st；辅音字母+y 变 y 为 i；多音节用 more/most。" if lw not in IRREGULAR_COMPARE else f"{w} 的比较级/最高级是不规则变化（{IRREGULAR_COMPARE[lw][0]} / {IRREGULAR_COMPARE[lw][1]}）。")
    elif kind == "3":
        steps.append("规则：一般加 -s；以 s/x/ch/sh/o 结尾加 -es；辅音字母+y 变 y 为 i 加 -es。")
    elif kind == "i":
        steps.append("规则：一般加 -ing；以不发音的 e 结尾去 e 加 -ing；重读闭音节双写末尾辅音；ie 结尾变 y 加 -ing。")
    card = lookup_word(w)
    return {
        "kernel": "english.inflection",
        "answer": ans,
        "steps": steps,
        "hint": f"想一想 {w} 是规则变化还是不规则变化？",
        "explanation": f"考点：{label}的构成。",
        **({"card": card} if card else {}),
    }


def _tense_need(t: str) -> Optional[str]:
    if _PAST_MARK.search(t):
        return "past"
    if _FUTURE_MARK.search(t):
        return "future"
    if _NOW_MARK.search(t):
        return "progressive"
    if _HABIT_MARK.search(t):
        return "present"
    return None


def _form_kind(opt: str) -> str:
    o = opt.strip().lower()
    if o.startswith("will "):
        return "future"
    if re.match(r"(is|am|are) \w+ing$", o):
        return "progressive"
    lem = lemma_of(o.split()[-1]) if o else None
    if lem and lem[1] == "p":
        return "past"
    if lem and lem[1] in {"3"}:
        return "present"
    if lem is None and o in IRREGULAR_VERBS:
        return "present"
    return "other"


def _solve_choice(t: str) -> Optional[dict]:
    if not _BLANK.search(t):
        return None
    opts = [(m.group(1), m.group(2).strip()) for m in _OPTIONS.finditer(t)]
    if len(opts) < 2:
        return None
    stem = t.split("\n")[0] if "\n" in t else re.split(r"\s+A[.．、)]", t)[0]
    stem = re.sub(r"^\s*(\d+[.．、]\s*)?(choose|选择)[:：]?\s*", "", stem, flags=re.I)
    ok: list[tuple[str, str]] = []
    for letter, o in opts:
        sent = _BLANK.sub(o, stem, count=1)
        if not check_grammar(sent):
            ok.append((letter, o))
    need = _tense_need(stem)
    if len(ok) > 1 and need:
        narrowed = [x for x in ok if _form_kind(x[1]) == need]
        if narrowed:
            ok = narrowed
    if len(ok) != 1:
        return None
    letter, o = ok[0]
    filled = _BLANK.sub(o, stem, count=1)
    steps = ["把每个选项代进句子检查主谓一致和时态。"]
    if need == "present":
        steps.append("句中有 every day / usually / often 等频度词 → 一般现在时。")
    elif need == "past":
        steps.append("句中有 yesterday / … ago / last … → 一般过去时。")
    elif need == "future":
        steps.append("句中有 tomorrow / next … → 一般将来时。")
    elif need == "progressive":
        steps.append("句中有 now / look / listen → 现在进行时。")
    m = re.match(r"\s*(he|she|it)\b", stem, re.I)
    if m:
        steps.append(f"主语 {m.group(1)} 是第三人称单数。")
    steps.append(f"所以选 {letter}：{filled.strip()}")
    return {
        "kernel": "english.choice",
        "answer": f"{letter}. {o}",
        "steps": steps,
        "hint": "先找时间词，确定时态；再看主语是不是第三人称单数。",
        "explanation": "考点：时态与主谓一致。",
    }


def _solve_correction(t: str) -> Optional[dict]:
    sent = re.sub(r"^\s*(\d+[.．、]\s*)?(改错|找错|correct( the)? (mistake|error)s?)[:：]?\s*", "", t, flags=re.I).strip()
    if len(re.findall(r"[A-Za-z]+", sent)) < 3:
        return None
    issues = check_grammar(sent)
    if not issues:
        return None
    fixed = sent
    for it in issues:
        if "…" in it["wrong"]:
            a, b = it["wrong"].split(" … ")
            ra, rb = it["right"].split(" … ")
            fixed = re.sub(rf"\b{re.escape(b)}\b", rb, fixed, count=1)
        else:
            fixed = re.sub(re.escape(it["wrong"]), it["right"], fixed, count=1, flags=re.I)
    steps = [f"「{it['wrong']}」→「{it['right']}」：{it['rule']}" for it in issues]
    steps.append(f"改正后：{fixed}")
    return {
        "kernel": "english.grammar",
        "answer": fixed,
        "steps": steps,
        "hint": "看看主语是谁，动词和它配不配；再找找时间词。",
        "explanation": "考点：" + "；".join(sorted({it["rule"].split("，")[0] for it in issues})),
    }


def _solve_word(t: str) -> Optional[dict]:
    q = re.sub(r"(是什么意思|什么意思|的意思|意思|翻译|怎么读|音标|中文|英文|单词|查一下|查词|是啥|\?|？|。|:|：)", " ", t)
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", q)
    rest = re.sub(r"[A-Za-z'\-\s]", "", q)
    if not words or len(words) > 3 or len(rest) > 6:
        return None
    phrase = " ".join(words)
    card = lookup_word(phrase) or (lookup_word(words[0]) if len(words) == 1 else None)
    if card is None:
        return None
    steps = []
    if card.get("phonetic"):
        steps.append(f"音标：/{card['phonetic']}/")
    if card.get("lemma_of"):
        steps.append(f"{card['lemma_of']['form']} 是 {card['word']} 的{card['lemma_of']['kind']}。")
    steps.extend(card["meanings"][:4])
    if card["inflections"]:
        steps.append("变形：" + "，".join(f"{k} {v}" for k, v in card["inflections"].items()))
    if card["tags"]:
        steps.append("考试范围：" + " / ".join(card["tags"]))
    return {
        "kernel": "english.word",
        "answer": (card["meanings"][0] if card["meanings"] else card["word"]),
        "steps": steps,
        "hint": "先读一读音标，再想想它在句子里的意思。",
        "explanation": f"{card['word']}：" + "；".join(card["meanings"][:2]),
        "card": card,
    }


def english_lookup_solve(text: str) -> Optional[dict]:
    """英语确定性求解。不适用返回 None；永不抛。"""
    try:
        t = _norm(text)
        if not t or len(t) > 600:
            return None
        latin, han = _english_ratio(t)
        if latin < 2:
            return None
        if re.search(r"[=+×÷^√]|\d\s*[a-z]\b", t) and not re.search(r"[A-Za-z]{3,}", t):
            return None
        for fn in (_solve_inflection, _solve_choice):
            out = fn(t)
            if out:
                return out
        if han > latin:  # 以中文为主（如中文题里夹一个字母），只做查词
            return _solve_word(t)
        return _solve_correction(t) or _solve_word(t)
    except Exception:  # noqa: BLE001 — provider 绝不打断主流程
        return None


__all__ = [
    "IRREGULAR_VERBS",
    "check_grammar",
    "comparative",
    "english_lookup_solve",
    "ing_form",
    "lemma_of",
    "lookup_word",
    "past_form",
    "past_participle",
    "plural",
    "third_person",
]
