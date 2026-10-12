"""
英语 he / she 指代错误的规则检查（oprim 层）
=============================================

中文的“他 / 她”读音都是 tā，口语里不分，中国学生写英语时最常见的错误之一就是
he / she 混用（"Tell me about your sister." → "He is a teacher."）。本检查是确定性的：
学生用了某一性别的代词，而在它之前（上下文或学生自己的文字里）只出现过另一性别的人
（mother / brother / Mrs …），就判为错误，并给出改法。

为避免误报（误报比漏报更糟）：一旦提到性别未知的人（my friend / a teacher / 人名），
之后的 he / she 可能指他们，不再标错；学生自己前后一致使用的代词也视为指代对象。
人名判断：句中（非句首、非介词 in/at/to… 之后）首字母大写且不是常见英语专有词的词，
或含非 ASCII 字母的词（如“张伟”）。

3O 范式 oprim 约束：
- 每个公开函数是一次原子计算，公开函数之间互不调用（只共享 ``_`` 私有工具）
- 纯函数：无 IO、无全局状态、无随机；纯计算故为同步函数
- 签名：≤1 个核心位置参数，其余 keyword-only

来源：派生自 recepyagmur/EnglishPractice ``app/backend/pronoun_check.py``（find_errors、
apply，commit 040d95546f7ffa1ef439ee66f9e8a3cbc7323072）。改动：改写为 3O oprim 形态；
去掉土耳其语说明分支，改为中文提示；无离线词典，人名改用大写启发式；
新增 Pydantic 结果模型与位置信息。

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

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

MAX_TEXT_LEN = 4000

FEMALE_NOUNS = frozenset(
    {
        "mother",
        "mom",
        "mum",
        "mommy",
        "sister",
        "wife",
        "daughter",
        "aunt",
        "grandmother",
        "grandma",
        "granny",
        "girlfriend",
        "girl",
        "woman",
        "lady",
        "niece",
        "queen",
        "actress",
        "waitress",
        "mrs",
        "ms",  # 不含 "miss"：也是动词（I miss him）
    }
)
MALE_NOUNS = frozenset(
    {
        "father",
        "dad",
        "daddy",
        "brother",
        "husband",
        "son",
        "uncle",
        "grandfather",
        "grandpa",
        "boyfriend",
        "boy",
        "man",
        "gentleman",
        "nephew",
        "king",
        "actor",
        "waiter",
        "mr",
    }
)
FEMALE_PRONOUNS = frozenset({"she", "her", "hers", "herself"})
MALE_PRONOUNS = frozenset({"he", "him", "his", "himself"})

# 代词 → 另一性别；"her" 视后词而定（her car → his car，love her → him）
_SWAP = {
    "he": "she",
    "she": "he",
    "him": "her",
    "himself": "herself",
    "herself": "himself",
    "hers": "his",
    "his": "her",
}
# "her" 之后出现这些词时它是宾格（love her and …），否则是物主（her new car → his）。
_NOT_A_NOUN_AFTER = frozenset(
    {
        "and",
        "or",
        "but",
        "to",
        "for",
        "with",
        "at",
        "in",
        "on",
        "very",
        "so",
        "too",
        "a",
        "an",
        "the",
        "about",
        "from",
        "that",
        "because",
        "when",
        "if",
        "yesterday",
        "today",
        "now",
        "again",
        "back",
        "up",
        "out",
        "of",
        "every",
        "last",
        "this",
        "much",
        "lot",
        "is",
        "was",
        "will",
        "can",
    }
)
# 性别未知的人：提到（作为新人物，而不是 "she is a teacher" 的表语）后，之后的 he/she 可能指他们。
NEUTRAL_PERSONS = frozenset(
    {
        "friend",
        "colleague",
        "coworker",
        "co-worker",
        "boss",
        "manager",
        "teacher",
        "doctor",
        "neighbour",
        "neighbor",
        "cousin",
        "customer",
        "client",
        "partner",
        "student",
        "classmate",
        "roommate",
        "flatmate",
        "engineer",
        "nurse",
        "person",
        "someone",
        "somebody",
        "child",
        "kid",
        "baby",
        "parent",
        "director",
        "assistant",
        "guest",
        "teammate",
        "supervisor",
        "employee",
        "lawyer",
        "dentist",
        "driver",
        "owner",
        "officer",
        "relative",
        "sibling",
        "spouse",
        "chef",
        "cook",
        "secretary",
        "receptionist",
        "developer",
        "designer",
        "accountant",
        "author",
        "writer",
        "artist",
        "deskmate",
        "headteacher",
        "principal",
        "monitor",
        "tutor",
        "pen-pal",
        "penpal",
    }
)
_PREDICATE_BEFORE = frozenset(
    {"is", "was", "are", "were", "am", "be", "been", "as", "becomes", "became"}
)
_PLACE_BEFORE = frozenset(
    {"in", "at", "to", "from", "near", "into", "around", "visit", "visited", "visiting", "of"}
)
# 无词典时，句中大写但不是人名的常见英语词（星期、月份、语言 / 国籍、节日、科目等）。
_NOT_NAMES = frozenset(
    {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "english",
        "chinese",
        "french",
        "german",
        "japanese",
        "korean",
        "spanish",
        "russian",
        "american",
        "british",
        "math",
        "maths",
        "physics",
        "chemistry",
        "biology",
        "history",
        "christmas",
        "easter",
        "spring",
        "festival",
        "new",
        "year",
        "day",
        "mid-autumn",
        "national",
        "internet",
        "tv",
        "ok",
        "okay",
        "god",
        "mr",
        "mrs",
        "ms",
        "dr",
        "miss",
        "sir",
        "madam",
    }
)

# Unicode 字母：中文人名（“张伟”）保持为一个词。
_TOKEN = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")

_EXPLAIN = (
    "前面说的人是{who}（{noun}），这里应该用 “{right}”。"
    "中文的“他 / 她”读音都是 tā，英语里男性用 he / him / his，女性用 she / her。"
)
_EXPLAIN_BY_PRONOUN = (
    "前面一直用 “{noun}” 指这个人，说明是{who}，这里应该用 “{right}”。"
    "中文的“他 / 她”读音都是 tā，英语里要区分 he 和 she。"
)

Gender = Literal["female", "male"]


class PronounError(BaseModel):
    """一处 he / she 指代错误。"""

    model_config = ConfigDict(frozen=True)

    wrong: str  # 学生写的代词（原大小写，不含 's 等后缀）
    right: str  # 建议改成
    start: int  # 在 text 中的字符偏移
    end: int
    referent: str  # 引出该性别人物的词（sister / she …）
    referent_gender: Gender
    category: Literal["pronoun"] = "pronoun"
    explanation: str  # 中文说明


# ──────────────────────────────────────────────────────────────────────────────
# 私有工具
# ──────────────────────────────────────────────────────────────────────────────


def _gender(word: str) -> str | None:
    w = word.lower()
    if w in FEMALE_NOUNS or w + "s" in FEMALE_NOUNS:
        return "f"
    if w in MALE_NOUNS:
        return "m"
    if w.endswith("s") and (w[:-1] in FEMALE_NOUNS or w[:-1] in MALE_NOUNS):  # sisters, brothers
        return "f" if w[:-1] in FEMALE_NOUNS else "m"
    return None


def _is_name(tok: re.Match[str], text: str) -> bool:
    """句中首字母大写、又不是常见英语词的词：可能是人名。"""
    word = tok.group(0).split("'")[0]
    before = text[: tok.start()].rstrip()
    after_place = (
        bool(before) and before.split()[-1].lower() in _PLACE_BEFORE
    )  # in Beijing / to Shanghai：地名
    first = word[:1]
    if (
        not first.isupper() and not first.islower()
    ):  # 无大小写的文字（汉字“张伟”）：人名，除非是地名
        return not after_place
    if not first.isupper() or word == "I":
        return False
    if not before or before[-1] in '.!?:"“':  # 句首
        return False
    if after_place:
        return False
    if not word.isascii():
        return True
    low = word.lower()
    return low not in _NOT_NAMES and _gender(low) is None and low not in NEUTRAL_PERSONS


def _new_unknown_person(tokens: list[re.Match[str]], i: int, text: str) -> bool:
    """tokens[i] 是否提到一个性别未知的人（人名，或 "my friend"，但不是 "she is a teacher"）。"""
    m = tokens[i]
    low = m.group(0).lower().split("'")[0]
    if _is_name(m, text):
        return True
    noun = low[:-1] if low.endswith("s") and low[:-1] in NEUTRAL_PERSONS else low
    if noun not in NEUTRAL_PERSONS:
        return False
    prev = [t.group(0).lower() for t in tokens[max(0, i - 2) : i]]
    predicate = (
        len(prev) == 2
        and prev[1] in ("a", "an", "the", "my", "your", "our", "their")
        and prev[0].split("'")[-1] in _PREDICATE_BEFORE | {"s"}
    )
    return not predicate


def _match_case(word: str, like: str) -> str:
    return word.capitalize() if like[:1].isupper() else word


def _check_len(text: str) -> None:
    if len(text) > MAX_TEXT_LEN:
        raise ValueError(f"文本过长（>{MAX_TEXT_LEN} 字符）")


# ──────────────────────────────────────────────────────────────────────────────
# 公开原语
# ──────────────────────────────────────────────────────────────────────────────


def find_pronoun_errors(text: str, *, context: str = "") -> list[PronounError]:
    """学生文字 ``text`` 中的 he / she 指代错误（``context`` 为之前的题目 / 对话，可空）。

    Example:
        >>> errs = find_pronoun_errors("He is a teacher.", context="Tell me about your sister.")
        >>> [e.right for e in errs]
        ['She']
    """
    _check_len(text)
    _check_len(context or "")
    seen: dict[str, str | None] = {"f": None, "m": None}  # 性别 → 首个引出该性别的词
    unknown = False
    context = context or ""
    ctx_tokens = list(_TOKEN.finditer(context))
    for i, tok in enumerate(ctx_tokens):
        low = tok.group(0).lower().split("'")[0]
        g = _gender(low) or (
            "f" if low in FEMALE_PRONOUNS else "m" if low in MALE_PRONOUNS else None
        )
        if g and not seen[g]:
            seen[g] = low
        unknown = unknown or _new_unknown_person(ctx_tokens, i, context)
    errors: list[PronounError] = []
    tokens = list(_TOKEN.finditer(text))
    for i, m in enumerate(tokens):
        word = m.group(0).split("'")[0]  # "He's" → "He"
        low = word.lower()
        g = _gender(low)
        if g:
            seen[g] = seen[g] or low
            continue
        pron = "f" if low in FEMALE_PRONOUNS else "m" if low in MALE_PRONOUNS else None
        if not pron:
            unknown = unknown or _new_unknown_person(tokens, i, text)
            continue
        other = "m" if pron == "f" else "f"
        if seen[pron] or not seen[other] or unknown:
            seen[pron] = seen[pron] or low  # 学生前后一致使用的代词也是指代对象
            continue
        if low == "her":
            nxt = tokens[i + 1].group(0).lower() if i + 1 < len(tokens) else ""
            right = "his" if nxt and nxt not in _NOT_A_NOUN_AFTER else "him"
        else:
            right = _SWAP[low]
        right = _match_case(right, word)
        noun = seen[other] or ""
        who = "男性" if other == "m" else "女性"
        template = _EXPLAIN_BY_PRONOUN if noun in FEMALE_PRONOUNS | MALE_PRONOUNS else _EXPLAIN
        errors.append(
            PronounError(
                wrong=word,
                right=right,
                start=m.start(),
                end=m.start() + len(word),
                referent=noun,
                referent_gender="male" if other == "m" else "female",
                explanation=template.format(who=who, noun=noun, right=right),
            )
        )
    return errors


def apply_pronoun_fixes(text: str, *, errors: list[PronounError]) -> str:
    """把每处代词错误按顺序替换成建议写法（整词匹配）。"""
    _check_len(text)
    out: list[str] = []
    pos = 0
    for e in errors:
        m = re.compile(rf"\b{re.escape(e.wrong)}\b").search(text, pos)
        if not m:
            continue
        out.append(text[pos : m.start()] + e.right)
        pos = m.end()
    return "".join(out) + text[pos:]
