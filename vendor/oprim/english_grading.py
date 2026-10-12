"""
英语作答确定性判分原语（oprim 层）
===================================

面向中国 K-12 学生的英语客观题：填空 / 连词成句 / 听写，以及句型（固定搭配）
使用检测。全部是确定性字符串计算，不依赖 LLM。

- 缩写感知的答案等价：``'s`` = is，或在过去分词前 = has（"She's finished" =
  "She has finished"，但 "He's a car" ≠ "He has a car"）；``'d`` = would，
  或在过去分词 / better 前 = had；``n't`` / ``'m`` / ``'re`` / ``'ve`` / ``'ll``
  展开；``2 p.m.`` = ``2pm``；逗号、句末标点、引号、弯撇号忽略。
- 连词成句：句中 ``. ? !`` 不计（词块可能带标点）。
- 听写：漏写撇号（``dont``）算小失误而非另一个词；按“词”的增删改计编辑数，
  ≤1 处全对，其余按序列相似度 ×0.9 给分。
- 句型：``___`` 为空位；固定部分须按序出现，词可屈折（put → puts/putting），
  相邻词之间最多插 2 个词（"put the meeting off" 匹配 "put ___ off"），缩写按展开形式比对。

3O 范式 oprim 约束：
- 每个公开函数是一次原子计算，公开函数之间互不调用（只共享 ``_`` 私有工具）
- 纯函数：无 IO、无全局状态、无随机；纯计算故为同步函数
- 签名：≤1 个核心位置参数，其余 keyword-only
- 输入输出类型显式（Pydantic 模型 / bool / int / str / list）

来源：派生自 recepyagmur/EnglishPractice ``app/backend/exams.py``（normalize_answer、
answer_forms、answer_ok、_order_key、_NO_APOSTROPHE、_dictation_words、_word_edits、
听写评分）、``app/backend/patterns.py``（fixed_parts、contains_pattern、uses_pattern、
_match）与 ``app/backend/words.py``（word_forms），commit
040d95546f7ffa1ef439ee66f9e8a3cbc7323072。只移植代码，未复制其 app/content 内容。
改动：改写为 3O oprim 形态；word_forms 去掉离线词典查询，改为规则屈折 +
本模块自带的常用不规则动词表；新增 Pydantic 结果模型。

MIT License — Copyright (c) 2026 recepyagmur

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

AnswerMode = Literal["fill", "order", "dictation"]

MAX_ANSWER_LEN = 2000
MAX_ACCEPTED = 50

# ──────────────────────────────────────────────────────────────────────────────
# 结果模型
# ──────────────────────────────────────────────────────────────────────────────


class AnswerEquivalence(BaseModel):
    """作答与参考答案的等价判定结果。"""

    model_config = ConfigDict(frozen=True)

    ok: bool
    mode: AnswerMode
    given_forms: list[str]  # 作答的全部规范化读法（排序）
    matched_answer: str | None  # 命中的参考答案原文
    matched_form: str | None  # 命中的规范化读法


class DictationScore(BaseModel):
    """听写按词评分结果。"""

    model_config = ConfigDict(frozen=True)

    expected_words: list[str]
    given_words: list[str]
    edits: int  # 词级增 / 删 / 改次数
    score: float  # 0–1；edits ≤ 1 记 1.0
    ok: bool  # edits ≤ 1


# ──────────────────────────────────────────────────────────────────────────────
# 私有工具：规范化 / 缩写读法
# ──────────────────────────────────────────────────────────────────────────────

_CONTRACTIONS: list[tuple[str, str]] = [
    (r"\bcan't\b", "can not"),
    (r"\bcannot\b", "can not"),
    (r"\bwon't\b", "will not"),
    (r"n't\b", " not"),
    (r"'m\b", " am"),
    (r"'re\b", " are"),
    (r"'ve\b", " have"),
    (r"'ll\b", " will"),
    (r"\b(he|she|it|that|there|what|where|who|here)'s\b", r"\1 is"),
    (r"'d have\b", " would have"),
    # 缩略：2 p.m. = 2pm = 2 pm，e.g. = eg，Mr. = Mr
    (r"\b([a-z])\.([a-z])\.", r"\1\2"),
    (r"\b(mr|mrs|ms|dr)\.", r"\1"),
    (r"(\d)\s*(am|pm)\b", r"\1 \2"),
]


def _wordset(*lines: str) -> frozenset[str]:
    return frozenset(" ".join(lines).split())


# 代词的 's 是 is——在过去分词前是 has；'d 是 would——在过去分词或 better 前是 had。
_PARTICIPLES = _wordset(
    "been got gotten had done gone seen made said sent left lost met paid put read spent",
    "taken told thought bought brought built found heard held kept known run sold written",
    "won begun come become given forgotten chosen spoken broken eaten fallen flown grown",
    "shown thrown drawn worn sat stood understood taught caught felt led set cut hit let",
    "shut hurt cost quit sung drunk swum rung forgiven driven ridden risen hidden bitten",
    "beaten woken fed meant slept dealt lent stuck struck",
)
_ADVERBS = _wordset(
    "just already never ever not always recently finally also still only really probably",
    "definitely certainly obviously clearly",
)
_PRONOUN_S = re.compile(r"\b(he|she|it|that|there|what|where|who|here)'s\b", re.IGNORECASE)
_PRONOUN_D = re.compile(r"\b(i|you|he|she|it|we|they|there|who|that)'d\b", re.IGNORECASE)

# 听写：漏写撇号（"dont"）是小失误，不是另一个词。
_NO_APOSTROPHE = re.compile(
    r"\b(do|does|did|is|are|was|were|has|have|had|could|should|would|ca|wo)nt\b"
)


def _check_len(text: str) -> str:
    if len(text) > MAX_ANSWER_LEN:
        raise ValueError(f"作答过长（>{MAX_ANSWER_LEN} 字符）")
    return text


def _normalize(text: str) -> str:
    s = text.lower().replace("’", "'").replace("‘", "'")
    s = re.sub(r"[“”\"]", "", s).strip()
    for pattern, rep in _CONTRACTIONS:
        s = re.sub(pattern, rep, s)
    s = re.sub(r"\s+", " ", s.replace(",", ""))
    return re.sub(r"[.!?]+$", "", s).strip()


def _order(text: str) -> str:
    return _normalize(re.sub(r"[.?!]", " ", text))


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", _normalize(text))


def _before_participle(rest: str) -> bool:
    words = re.findall(r"[a-z']+", rest.lower())[:2]
    if words and words[0] in _ADVERBS:
        words = words[1:]
    return bool(words) and (
        words[0] in _PARTICIPLES or words[0].endswith("ed") or words[0].endswith("en")
    )


def _readings(
    text: str, pattern: re.Pattern[str], plain: str, perfect: str, extra: tuple[str, ...] = ()
) -> set[str]:
    """每个缩写按普通读法，或在其后紧跟分词时按完成时读法（整句统一替换）。"""
    perfect_text = pattern.sub(
        lambda m: (
            f"{m.group(1)} {perfect}"
            if _before_participle(text[m.end() :])
            or text[m.end() :].lower().lstrip().startswith(extra)
            else m.group(0)
        ),
        text,
    )
    return {pattern.sub(rf"\1 {plain}", text), pattern.sub(rf"\1 {plain}", perfect_text)}


def _forms(text: str, key: Callable[[str], str]) -> set[str]:
    forms = _readings(text.replace("’", "'").replace("‘", "'"), _PRONOUN_S, "is", "has")
    forms = set().union(*(_readings(f, _PRONOUN_D, "would", "had", ("better",)) for f in forms))
    return {key(f) for f in forms}


def _key_for(mode: AnswerMode) -> Callable[[str], str]:
    return _order if mode == "order" else _normalize


def _dictation(text: str) -> list[str]:
    return _words(_NO_APOSTROPHE.sub(r"\1n't", text.lower()))


def _edits(a: list[str], b: list[str]) -> int:
    edits = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag != "equal":
            edits += max(i2 - i1, j2 - j1)
    return edits


# ──────────────────────────────────────────────────────────────────────────────
# 私有工具：词形 / 句型
# ──────────────────────────────────────────────────────────────────────────────

# Mneme 自带：常用不规则动词（原形 → 过去式 / 过去分词 / 三单）。原项目从离线词典取词形。
_IRREGULAR: dict[str, tuple[str, ...]] = {
    "be": ("am", "is", "are", "was", "were", "been", "being"),
    "have": ("has", "had", "having"),
    "do": ("does", "did", "done", "doing"),
    "go": ("goes", "went", "gone", "going"),
    "get": ("got", "gotten", "getting"),
    "make": ("made",),
    "take": ("took", "taken"),
    "come": ("came",),
    "see": ("saw", "seen"),
    "give": ("gave", "given"),
    "know": ("knew", "known"),
    "think": ("thought",),
    "tell": ("told",),
    "say": ("said",),
    "find": ("found",),
    "bring": ("brought",),
    "buy": ("bought",),
    "catch": ("caught",),
    "teach": ("taught",),
    "keep": ("kept",),
    "leave": ("left",),
    "meet": ("met",),
    "pay": ("paid",),
    "send": ("sent",),
    "spend": ("spent",),
    "write": ("wrote", "written"),
    "speak": ("spoke", "spoken"),
    "break": ("broke", "broken"),
    "choose": ("chose", "chosen"),
    "eat": ("ate", "eaten"),
    "fall": ("fell", "fallen"),
    "fly": ("flew", "flown", "flies"),
    "grow": ("grew", "grown"),
    "throw": ("threw", "thrown"),
    "draw": ("drew", "drawn"),
    "wear": ("wore", "worn"),
    "begin": ("began", "begun"),
    "run": ("ran", "running"),
    "swim": ("swam", "swum", "swimming"),
    "sing": ("sang", "sung"),
    "drink": ("drank", "drunk"),
    "drive": ("drove", "driven"),
    "ride": ("rode", "ridden"),
    "rise": ("rose", "risen"),
    "hide": ("hid", "hidden"),
    "forget": ("forgot", "forgotten", "forgetting"),
    "lose": ("lost",),
    "feel": ("felt",),
    "hold": ("held",),
    "hear": ("heard",),
    "stand": ("stood",),
    "understand": ("understood",),
    "sit": ("sat", "sitting"),
    "sleep": ("slept",),
    "build": ("built",),
    "lead": ("led",),
    "mean": ("meant",),
    "read": ("read",),
    "sell": ("sold",),
    "win": ("won", "winning"),
    "become": ("became",),
    "wake": ("woke", "woken"),
    "show": ("showed", "shown"),
    "set": ("setting",),
    "put": ("putting",),
    "cut": ("cutting",),
    "let": ("letting",),
    "hit": ("hitting",),
    "shut": ("shutting",),
    "lie": ("lay", "lain", "lying", "lied"),
    "die": ("dying",),
    "tie": ("tying",),
    "child": ("children",),
    "man": ("men",),
    "woman": ("women",),
    "person": ("people",),
    "foot": ("feet",),
    "tooth": ("teeth",),
    "mouse": ("mice",),
}


def _word_forms(word: str) -> set[str]:
    w = word.lower()
    forms = {w, w + "s", w + "es", w + "ed", w + "d", w + "ing", w + "er", w + "est"}
    if w.endswith("e"):
        forms |= {w[:-1] + "ing", w[:-1] + "ed"}
    if w.endswith("y"):
        forms |= {w[:-1] + "ies", w[:-1] + "ied"}
    if len(w) > 2 and w[-1] not in "aeiouwy" and w[-2] in "aeiou":  # stop → stopped, stopping
        forms |= {w + w[-1] + "ed", w + w[-1] + "ing"}
    forms |= set(_IRREGULAR.get(w, ()))
    return forms


def _norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("’", "'")).strip()


def _fixed_parts(p: str) -> list[str]:
    parts = (_norm_space(x).strip(" ,.;:!?…") for x in p.split("___"))
    return [x for x in parts if x]


def _match(tokens: list[str], want: list[str], start: int) -> int | None:
    """``want`` 在 ``tokens``（从 start 起）中结束的位置：词可屈折，相邻两词间最多插 2 个词。"""

    def same(tok: str, w: str) -> bool:
        return tok == w or tok in _word_forms(w)

    for i in range(start, len(tokens)):
        if not same(tokens[i], want[0]):
            continue
        pos, ok = i + 1, True
        for w in want[1:]:
            nxt = next(
                (k for k in range(pos, min(pos + 3, len(tokens))) if same(tokens[k], w)), None
            )
            if nxt is None:
                ok = False
                break
            pos = nxt + 1
        if ok:
            return pos
    return None


def _check_pattern(p: str) -> str:
    if not p or len(p) > 200:
        raise ValueError("句型为空或过长（≤200 字符）")
    if not _fixed_parts(p):
        raise ValueError("句型没有固定词（只有 ___ 空位）")
    return p


# ──────────────────────────────────────────────────────────────────────────────
# 公开原语
# ──────────────────────────────────────────────────────────────────────────────


def normalize_english_answer(text: str, *, mode: AnswerMode = "fill") -> str:
    """规范化一条英语作答（小写、展开 n't/'m/'re/'ve/'ll 与代词 's=is、去逗号与句末标点）。

    ``mode="order"`` 时句中 ``. ? !`` 也忽略（连词成句的词块可带标点）。

    Example:
        >>> normalize_english_answer("I can't go, sorry.")
        'i can not go sorry'
    """
    _check_len(text)
    return _key_for(mode)(text)


def english_answer_forms(text: str, *, mode: AnswerMode = "fill") -> list[str]:
    """一条作答的全部规范化读法（排序）：``'s`` 读 is / has，``'d`` 读 would / had。

    Example:
        >>> english_answer_forms("She's finished")
        ['she has finished', 'she is finished']
    """
    _check_len(text)
    return sorted(_forms(text, _key_for(mode)))


def english_answers_equivalent(
    given: str, *, accepted: list[str], mode: AnswerMode = "fill"
) -> AnswerEquivalence:
    """作答是否与任一参考答案等价（两侧读法集合有交集）。空作答恒为 False。

    ``mode="dictation"`` 时按听写词序列比较（漏撇号容错），需完全一致；听写评分见
    :func:`score_dictation_words`。

    Raises:
        ValueError: 无参考答案 / 参考答案过多 / 文本过长。
    """
    _check_len(given)
    if not accepted:
        raise ValueError("至少需要 1 个参考答案")
    if len(accepted) > MAX_ACCEPTED:
        raise ValueError(f"参考答案过多（>{MAX_ACCEPTED}）")
    for a in accepted:
        _check_len(a)
    if mode == "dictation":
        got = " ".join(_dictation(given))
        hit = next((a for a in accepted if got and " ".join(_dictation(a)) == got), None)
        return AnswerEquivalence(
            ok=hit is not None,
            mode=mode,
            given_forms=[got] if got else [],
            matched_answer=hit,
            matched_form=got if hit is not None else None,
        )
    key = _key_for(mode)
    given_forms = _forms(given, key) if given.strip() else set()
    for a in accepted:
        common = given_forms & _forms(a, key)
        if common:
            return AnswerEquivalence(
                ok=True,
                mode=mode,
                given_forms=sorted(given_forms),
                matched_answer=a,
                matched_form=min(common),
            )
    return AnswerEquivalence(
        ok=False, mode=mode, given_forms=sorted(given_forms), matched_answer=None, matched_form=None
    )


def dictation_words(text: str) -> list[str]:
    """听写比较用的词序列（规范化 + 补回漏写的撇号：dont → do not）。"""
    _check_len(text)
    return _dictation(text)


def dictation_word_edits(expected_words: list[str], *, given_words: list[str]) -> int:
    """把 ``expected_words`` 变成 ``given_words`` 需要增 / 删 / 改的词数。"""
    return _edits(list(expected_words), list(given_words))


def score_dictation_words(given: str, *, expected: str) -> DictationScore:
    """听写按词评分：空作答 0；编辑数 ≤1 记 1.0（一处小失误不扣分）；否则序列相似度 ×0.9。"""
    _check_len(given)
    _check_len(expected)
    want, got = _dictation(expected), _dictation(given)
    edits = _edits(want, got)
    if not got:
        score = 0.0
    elif edits <= 1:
        score = 1.0
    else:
        score = round(difflib.SequenceMatcher(None, want, got).ratio() * 0.9, 2)
    return DictationScore(
        expected_words=want, given_words=got, edits=edits, score=score, ok=bool(got) and edits <= 1
    )


def english_word_forms(word: str) -> list[str]:
    """一个词及其屈折形式（规则词尾 + 常用不规则形式），排序返回。"""
    if not word or len(word) > 40:
        raise ValueError("词为空或过长")
    return sorted(_word_forms(word))


def pattern_fixed_parts(pattern: str) -> list[str]:
    """句型中 ``___`` 空位之间的固定部分（去两端标点）：
    ``"Could you ___, please?"`` → ``["could you", "please"]``。"""
    return _fixed_parts(_check_pattern(pattern))


def contains_pattern(sentence: str, *, pattern: str) -> bool:
    """句型固定部分是否按序原样出现在句中（不区分大小写，不做屈折）。"""
    _check_len(sentence)
    s, at = _norm_space(sentence), 0
    for part in _fixed_parts(_check_pattern(pattern)):
        i = s.find(part, at)
        if i < 0:
            return False
        at = i + len(part)
    return True


def uses_pattern(sentence: str, *, pattern: str) -> bool:
    """学生句子是否用了该句型：固定部分按序出现，词可屈折（"moves the goalposts"、
    "put it off" → "put ___ off"），缩写按展开形式（"I am afraid" = "I'm afraid"），忽略标点。"""
    _check_len(sentence)
    tokens = _words(sentence)
    at = 0
    for part in _fixed_parts(_check_pattern(pattern)):
        want = _words(part)
        if not want:
            continue
        end = _match(tokens, want, at)
        if end is None:
            return False
        at = end
    return True
