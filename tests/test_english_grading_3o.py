"""英语确定性判分 3O 链路：oprim.english_grading / oprim.english_pronoun / oskill.english_answer_check_skill。

he/she 用例移植自 recepyagmur/EnglishPractice ``dev/tests/pronoun_rule_test.py``（MIT），
土耳其人名 / 地名换成中国学生常见的写法，判定期望（是否标错）保持不变。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from oprim.english_grading import (
    contains_pattern,
    dictation_word_edits,
    dictation_words,
    english_answer_forms,
    english_answers_equivalent,
    english_word_forms,
    normalize_english_answer,
    pattern_fixed_parts,
    score_dictation_words,
    uses_pattern,
)
from oprim.english_pronoun import PronounError, apply_pronoun_fixes, find_pronoun_errors
from oskill.english_answer_check_skill import EnglishCheckRequest, check_english_answer

# ── he / she：移植 pronoun_rule_test.CASES ────────────────────────────────────

PRONOUN_CASES = [  # (context, learner text, should be flagged)
    (
        "",
        "Yes, I have a sister. He is a teacher and his school is near our house.",
        True,
    ),
    ("", "My mother is a nurse. He works at night.", True),
    ("", "My father is very busy, she works every day.", True),
    ("", "I called my brother and talked to her for an hour.", True),
    ("", "My sister is a teacher. She loves her job.", False),
    ("", "My brother lives in Shanghai with his wife.", False),
    ("", "I met Wei yesterday. He told me about his new job.", False),
    ("Tell me about your sister.", "He's a teacher.", True),
    ("Tell me about your sister.", "He is a teacher.", True),
    ("What does your mother do?", "He is a doctor.", True),
    (
        "Do you have a brother?",
        "Yes, my brother is a manager. She works in Shenzhen.",
        True,
    ),
    ("What does your brother do?", "My brother is an engineer and she is happy.", True),
    ("", "I live in Beijing with my wife. He is a teacher.", True),
    # 提到了性别未知的人：不标错
    (
        "What does your father do?",
        "My father works with my friend Li Na and she is very kind.",
        False,
    ),
    (
        "What does your father do?",
        "He works with a colleague and she helps him a lot.",
        False,
    ),
    (
        "Is your sister married?",
        "Yes, her husband is a doctor. He is very nice.",
        False,
    ),
    ("", "My dad and Mrs Wang are neighbours. She is very old.", False),
]


@pytest.mark.parametrize(("context", "text", "expected"), PRONOUN_CASES)
def test_pronoun_rule_cases(context: str, text: str, expected: bool) -> None:
    assert bool(find_pronoun_errors(text, context=context)) is expected


def test_pronoun_fix_suggestions_and_case() -> None:
    errs = find_pronoun_errors("He is a teacher.", context="Tell me about your sister.")
    assert [(e.wrong, e.right, e.referent, e.referent_gender) for e in errs] == [
        ("He", "She", "sister", "female")
    ]
    assert errs[0].start == 0 and errs[0].end == 2
    assert "tā" in errs[0].explanation and "She" in errs[0].explanation
    assert apply_pronoun_fixes("He is a teacher.", errors=errs) == "She is a teacher."


def test_pronoun_her_object_vs_possessive() -> None:
    obj = find_pronoun_errors("I called my brother and talked to her for an hour.")
    assert [(e.wrong, e.right) for e in obj] == [("her", "him")]
    poss = find_pronoun_errors("My brother is tall. I like her new car.")
    assert [(e.wrong, e.right) for e in poss] == [("her", "his")]


def test_pronoun_multiple_errors_applied_in_order() -> None:
    text = "Yes, I have a sister. He is a teacher and his school is near our house."
    errs = find_pronoun_errors(text)
    assert [(e.wrong, e.right) for e in errs] == [("He", "She"), ("his", "her")]
    assert (
        apply_pronoun_fixes(text, errors=errs)
        == "Yes, I have a sister. She is a teacher and her school is near our house."
    )


def test_pronoun_referent_by_pronoun_explanation() -> None:
    errs = find_pronoun_errors("He is a doctor.", context="What does she do?")
    assert [(e.wrong, e.right, e.referent) for e in errs] == [("He", "She", "she")]
    assert "“she”" in errs[0].explanation


def test_pronoun_chinese_name_is_unknown_person() -> None:
    # 汉字人名（无大小写）视为性别未知的人：之后的 she 不标错
    assert (
        find_pronoun_errors(
            "My father works with 张伟 and he is kind. She is nice too."
        )
        == []
    )
    # 介词后的地名不算人名
    assert [
        e.right for e in find_pronoun_errors("My mother lives in 北京. He is kind.")
    ] == ["She"]


def test_pronoun_no_referent_no_error() -> None:
    assert find_pronoun_errors("He is a teacher.") == []
    assert find_pronoun_errors("") == []
    assert apply_pronoun_fixes("He is.", errors=[]) == "He is."


def test_pronoun_error_model_is_frozen() -> None:
    e = find_pronoun_errors("He is a doctor.", context="your mother")[0]
    assert isinstance(e, PronounError)
    with pytest.raises(ValidationError):
        e.right = "x"  # type: ignore[misc]


def test_pronoun_text_too_long() -> None:
    with pytest.raises(ValueError):
        find_pronoun_errors("a " * 3000)


# ── 答案等价（exams.normalize_answer / answer_forms / answer_ok / _order_key）──


def test_normalize_contractions_and_punctuation() -> None:
    assert normalize_english_answer("I can't go, sorry.") == "i can not go sorry"
    assert normalize_english_answer("“I’m fine!”") == "i am fine"
    assert normalize_english_answer("They won't come") == "they will not come"
    assert normalize_english_answer("We've cannot") == "we have can not"
    assert normalize_english_answer("It's 2 p.m.") == "it is 2 pm"
    assert normalize_english_answer("at 2pm") == normalize_english_answer("at 2 pm")
    assert normalize_english_answer("Mr. Li is here") == "mr li is here"


def test_order_key_ignores_inner_marks() -> None:
    assert (
        normalize_english_answer("I go to school. every day", mode="order")
        == "i go to school every day"
    )
    assert english_answers_equivalent(
        "What time is it ?", accepted=["What time is it?"], mode="order"
    ).ok


@pytest.mark.parametrize(
    ("given", "accepted", "ok"),
    [
        ("He's finished", "He has finished", True),
        ("He's a car", "He has a car", False),
        ("He's a teacher", "He is a teacher", True),
        ("She's just left", "She has just left", True),
        ("She's already eaten.", "She has already eaten", True),
        ("It's raining", "It is raining", True),
        ("I'd like some tea", "I would like some tea", True),
        ("You'd better go", "You had better go", True),
        ("They'd gone home", "They had gone home", True),
        ("I'd have come", "I would have come", True),
        ("He isn't here", "He is not here", True),
        ("He is here", "He is not here", False),
        ("", "anything", False),
    ],
)
def test_answer_equivalence(given: str, accepted: str, ok: bool) -> None:
    assert english_answers_equivalent(given, accepted=[accepted]).ok is ok


def test_answer_forms_readings() -> None:
    assert english_answer_forms("She's finished") == [
        "she has finished",
        "she is finished",
    ]
    assert english_answer_forms("He's a car") == ["he is a car"]
    assert english_answer_forms("You'd better hurry") == [
        "you had better hurry",
        "you would better hurry",
    ]


def test_answer_equivalence_reports_match() -> None:
    eq = english_answers_equivalent(
        "He's finished.", accepted=["Nope", "He has finished"]
    )
    assert (
        eq.ok
        and eq.matched_answer == "He has finished"
        and eq.matched_form == "he has finished"
    )
    assert "he has finished" in eq.given_forms


def test_answer_equivalence_validation() -> None:
    with pytest.raises(ValueError):
        english_answers_equivalent("x", accepted=[])
    with pytest.raises(ValueError):
        english_answers_equivalent("x", accepted=["a"] * 51)


# ── 听写（_NO_APOSTROPHE / _dictation_words / _word_edits / 评分）─────────────


def test_dictation_words_missing_apostrophe() -> None:
    assert dictation_words("I dont like it") == ["i", "do", "not", "like", "it"]
    assert dictation_words("She doesnt know") == dictation_words("She doesn't know.")
    assert dictation_words("I cant swim") == ["i", "can", "not", "swim"]


def test_dictation_word_edits() -> None:
    a = ["i", "like", "green", "tea"]
    assert dictation_word_edits(a, given_words=a) == 0
    assert dictation_word_edits(a, given_words=["i", "like", "tea"]) == 1
    assert dictation_word_edits(a, given_words=["i", "love", "black", "tea"]) == 2
    assert dictation_word_edits(a, given_words=[]) == 4


def test_dictation_scoring() -> None:
    exact = score_dictation_words("I don't like it.", expected="I don't like it.")
    assert exact.edits == 0 and exact.score == 1.0 and exact.ok
    slip = score_dictation_words("I dont like it", expected="I don't like it.")
    assert slip.edits == 0 and slip.ok
    one = score_dictation_words("I like it", expected="I don't like it.")
    assert one.edits == 2 and not one.ok  # "do not" 展开后是两个词
    near = score_dictation_words(
        "We go to the park on Sunday", expected="We went to the park on Sunday."
    )
    assert near.edits == 1 and near.score == 1.0 and near.ok
    far = score_dictation_words(
        "We go to a zoo", expected="We went to the park on Sunday."
    )
    assert not far.ok and 0 < far.score < 0.9
    empty = score_dictation_words("", expected="Hello")
    assert empty.score == 0.0 and not empty.ok


def test_dictation_equivalence_mode() -> None:
    assert english_answers_equivalent(
        "I dont know", accepted=["I don't know."], mode="dictation"
    ).ok
    assert not english_answers_equivalent(
        "I know", accepted=["I don't know."], mode="dictation"
    ).ok


# ── 句型（patterns.fixed_parts / contains_pattern / uses_pattern / words.word_forms）──


def test_pattern_fixed_parts() -> None:
    assert pattern_fixed_parts("Could you ___, please?") == ["could you", "please"]
    assert pattern_fixed_parts("put ___ off") == ["put", "off"]
    assert pattern_fixed_parts("I'm afraid ___") == ["i'm afraid"]
    with pytest.raises(ValueError):
        pattern_fixed_parts("___")


def test_contains_pattern_literal_in_order() -> None:
    assert contains_pattern(
        "Could you help me, please?", pattern="Could you ___, please?"
    )
    assert not contains_pattern(
        "Please, could you help me?", pattern="Could you ___, please?"
    )
    assert contains_pattern("We put it off", pattern="put ___ off")


@pytest.mark.parametrize(
    ("sentence", "pattern", "used"),
    [
        ("We put the meeting off", "put ___ off", True),
        ("They put it off until Monday.", "put ___ off", True),
        ("She is putting the trip off", "put ___ off", True),
        ("We postponed the meeting", "put ___ off", False),
        ("I am afraid I can't come.", "I'm afraid ___", True),
        ("He keeps moving the goalposts", "move the goalposts", True),
        ("Not only did we finish but we also won", "not only ___ but also ___", True),
        ("He went to bed early", "go to bed", True),
        ("Off we put it", "put ___ off", False),
    ],
)
def test_uses_pattern(sentence: str, pattern: str, used: bool) -> None:
    assert uses_pattern(sentence, pattern=pattern) is used


def test_word_forms() -> None:
    forms = english_word_forms("stop")
    assert {"stop", "stops", "stopped", "stopping"} <= set(forms)
    assert {"studies", "studied"} <= set(english_word_forms("study"))
    assert {"making", "maked", "made"} <= set(english_word_forms("make"))
    assert {"went", "gone", "goes"} <= set(english_word_forms("go"))
    assert forms == sorted(forms)
    with pytest.raises(ValueError):
        english_word_forms("")


# ── oskill：组合批改 ──────────────────────────────────────────────────────────


def _check(**kw: object) -> dict[str, object]:
    return check_english_answer(EnglishCheckRequest(**kw)).model_dump(mode="json")  # type: ignore[arg-type]


def test_skill_fill_contraction_ok() -> None:
    v = _check(text="He's finished", accepted=["He has finished"])
    assert (
        v["ok"] is True
        and v["answer_ok"] is True
        and v["matched_answer"] == "He has finished"
    )
    assert "he has finished" in v["normalized_forms"]  # type: ignore[operator]
    assert (
        v["pronoun_errors"] == []
        and v["pattern_used"] is None
        and v["dictation_edits"] is None
    )


def test_skill_fill_contraction_not_ok() -> None:
    v = _check(text="He's a car", accepted=["He has a car"])
    assert v["ok"] is False and v["answer_ok"] is False and v["matched_answer"] is None


def test_skill_pronoun_only() -> None:
    v = _check(text="He is a teacher.", context="Tell me about your sister.")
    assert v["ok"] is False and v["answer_checked"] is False and v["answer_ok"] is None
    errs = v["pronoun_errors"]
    assert [(e["wrong"], e["right"]) for e in errs] == [("He", "She")]  # type: ignore[index,union-attr]
    assert v["corrected_text"] == "She is a teacher."


def test_skill_pattern_used() -> None:
    v = _check(text="We put the meeting off", pattern="put ___ off")
    assert (
        v["ok"] is True
        and v["pattern_used"] is True
        and v["pattern_fixed_parts"] == ["put", "off"]
    )
    miss = _check(text="We cancelled the meeting", pattern="put ___ off")
    assert miss["ok"] is False and miss["pattern_used"] is False


def test_skill_dictation() -> None:
    v = _check(
        text="I dont like apples", accepted=["I don't like apples."], type="dictation"
    )
    assert v["ok"] is True and v["dictation_edits"] == 0 and v["pronoun_errors"] == []
    bad = _check(
        text="I like apple", accepted=["I don't like apples."], type="dictation"
    )
    assert bad["ok"] is False and bad["dictation_edits"] == 3
    assert bad["dictation"]["score"] < 0.9  # type: ignore[index]


def test_skill_dictation_best_of_accepted() -> None:
    v = _check(
        text="We went home",
        accepted=["They left early.", "We went home."],
        type="dictation",
    )
    assert v["ok"] is True and v["matched_answer"] == "We went home."


def test_skill_order() -> None:
    v = _check(
        text="Where do you live ?", accepted=["Where do you live?"], type="order"
    )
    assert v["ok"] is True


def test_skill_answer_ok_but_pronoun_wrong() -> None:
    v = _check(
        text="He is a nurse.",
        accepted=["He is a nurse."],
        context="What does your mother do?",
    )
    assert v["answer_ok"] is True and v["ok"] is False and len(v["pronoun_errors"]) == 1  # type: ignore[arg-type]


def test_skill_pronoun_check_can_be_disabled() -> None:
    v = _check(
        text="He is a teacher.",
        context="Tell me about your sister.",
        check_pronouns=False,
    )
    assert v["pronoun_errors"] == [] and v["ok"] is True


def test_skill_empty_text() -> None:
    v = _check(text="", accepted=["Hello"])
    assert v["ok"] is False and v["normalized_forms"] == []
    assert _check(text="")["ok"] is False


def test_skill_request_validation() -> None:
    with pytest.raises(ValidationError):
        EnglishCheckRequest(text="x", accepted=[" "])
    with pytest.raises(ValidationError):
        EnglishCheckRequest(text="x", type="essay")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        EnglishCheckRequest(text="x", unknown=1)  # type: ignore[call-arg]


def test_skill_is_deterministic() -> None:
    req = EnglishCheckRequest(
        text="She's gone. He is my sister's friend.",
        accepted=["She has gone."],
        context="Where is your mother?",
        pattern="___ gone",
    )
    assert check_english_answer(req) == check_english_answer(req)
