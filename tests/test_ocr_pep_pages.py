"""人教社英语教材 OCR 语料的**句子筛选门禁**。

这些用例盯的是实测踩到的三类东西 —— 每一类都会让「练习说明/版面碎片」
被当成真实例句喂给 LLM 或学生：

1. **水印**。OCR 在每一页都吐 `人民龙育出版社`（对「人民教育出版社」的误读，
   `育/教`），不剔它 = 每一页 `has_cjk=True` = 全书零产出。实测还见过
   `人民意育出版社` / `人民育出版社`，所以必须按**模式**认，不能枚举字面量。
2. **题型指令**。`Tick the correct boxes.` / `Listen again.` /
   `Make up a conversation with a partner.` 是题型说明，不是语言材料。
3. **版面碎片**。目录页、音标表、海报、跨栏并句。补不完关键词表，所以用两个
   **结构性**信号兜底：拼接行数（跨栏必多行）与 OCR 置信度（字没认对必低）。
   `Say"thankyou"when…` 就是低置信度导致的丢空格。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ocr_pep_pages.py"
_spec = importlib.util.spec_from_file_location("pep_ocr", _SCRIPT)
assert _spec and _spec.loader
pep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pep)


def _verdict(s: str, **kw) -> str:
    keep, rej = pep.classify_sentence(s, **kw)
    return rej or keep


# --------------------------------------------------------------------------
# 水印：必须按模式剔，不能枚举
# --------------------------------------------------------------------------


def test_watermark_variants_are_dropped_as_noise_boxes():
    """实测三种 OCR 误读，全部要当版面噪声丢掉。"""
    for w in ("人民龙育出版社", "人民意育出版社", "人民育出版社", "人民教育出版社"):
        assert pep._is_noise_box(w), w


def test_watermark_does_not_swallow_real_words():
    assert not pep._is_noise_box("Animals are friends to people.")


def test_page_numbers_and_phonetics_are_noise():
    assert pep._is_noise_box("p.1")
    assert pep._is_noise_box("12")
    assert pep._is_noise_box("/i:/")


# --------------------------------------------------------------------------
# 题型指令
# --------------------------------------------------------------------------


def test_task_instructions_are_rejected():
    """实测样本：题型说明不是语言材料，进语境层等于拿练习说明当例句。"""
    for s in (
        "Tick the correct boxes.",
        "Listen again and complete the sentences.",
        "Read and match the words with the pictures.",
        "Make up a conversation with a partner.",
        "Work in pairs and act out the dialogue.",
    ):
        assert _verdict(s) == pep.REJECT_IMPERATIVE_TASK, s


def test_real_imperative_sentences_are_kept():
    """对照组：祈使句本身是合法语言。首词撞上题型动词表也不该误杀。

    `Keep` 不在题型动词表里；`Be` 也不在。若将来有人把 `keep` 加进表，
    这条会失败 —— 那正是它存在的意义。
    """
    assert _verdict("Keep our school clean and tidy!") == "KEPT_CORPUS"
    assert _verdict("Be on time. Don't be late for class.") == "KEPT_CORPUS"


# --------------------------------------------------------------------------
# 目录 / 音标 / 词汇表
# --------------------------------------------------------------------------


def test_contents_and_pronunciation_pages_are_not_prose():
    for s in (
        "CONTENTS Unit 1 Why do you like animals?",
        "Pronunciation: a/el/, /ae/; ai /el/; ay/el/; al/o:/",
        "Word List abandon vt. to leave behind",
    ):
        assert _verdict(s) == pep.REJECT_NOT_PROSE, s


def test_section_markers_are_rejected():
    assert _verdict("3c Work together to design a poster for your rules.") == pep.REJECT_NOT_PROSE


# --------------------------------------------------------------------------
# 版面碎片：结构性信号
# --------------------------------------------------------------------------


def test_multi_box_merge_is_rejected_by_box_count():
    """跨栏并句：靠**拼接行数**判，不靠关键词。"""
    s = "Every day, from Monday to Friday, Across the country, in many schools, Students like u"
    assert _verdict(s, n_boxes=4) == pep.REJECT_LAYOUT_MERGE


def test_low_confidence_is_rejected():
    """实测 `Say"thankyou"when…` 是低置信度丢了空格，不是原文。"""
    s = 'Say"thankyou"when your classmates help you.'
    assert _verdict(s, min_score=0.61) == pep.REJECT_LOW_CONFIDENCE
    # 同样的字，置信度够就照收 —— 判据是结构不是内容
    assert _verdict(s, min_score=0.93) == "KEPT_CORPUS"


def test_phonetics_run_and_allcaps_run_and_two_speakers_are_layout_merges():
    assert _verdict("ear ea ee /i:/ /i:/ /1a/ please she bed head tree") == pep.REJECT_LAYOUT_MERGE
    assert (
        _verdict("IN THIS CLASS Always be kind Don't use bad WE ARE FAMILY and helpful.")
        == pep.REJECT_LAYOUT_MERGE
    )
    # 两个说话人 = 相邻发言被 OCR 并成一句
    assert _verdict("Anne: Tom: Well, I can't find my pencil box / pen.") == pep.REJECT_LAYOUT_MERGE


def test_single_speaker_dialogue_is_kept():
    """对照组：一个说话人是正常对话，是我们要的语料。"""
    assert _verdict("Tom: Hello! I'm Tom. It's my first day here.") == "KEPT_CORPUS"


# --------------------------------------------------------------------------
# 保留：真实对话/散文
# --------------------------------------------------------------------------


def test_real_dialogue_and_prose_are_kept():
    for s in (
        "How often do you do sport or exercise?",
        "I play it three times a week.",
        "Here, I can lend you my pen.",
        "Anne: Yes, of course.",
        "We mustn't fight with them.",
        "Nothing can be achieved without rules.",
    ):
        assert _verdict(s) == "KEPT_CORPUS", s


def test_cjk_and_fragments_rejected():
    assert _verdict("亲爱的同学们，欢迎你们进入七年级下学期的学习！") == pep.REJECT_HAS_CJK
    # 碎片：无实词的符号堆、单词表残片
    assert _verdict("words.") == pep.REJECT_SHORT_OR_JUNK
    assert _verdict("A B C D E F.") == pep.REJECT_SHORT_OR_JUNK
    assert _verdict("") == pep.REJECT_SHORT_OR_JUNK


def test_four_word_real_sentence_is_kept():
    """词数下限是 4 而不是 5：`Why do you like?` 是教材里真实出现的句子。

    真正挡版面碎片的是 `_MAX_MERGE_BOXES` / `_MIN_SCORE` 两个结构判据；
    把下限抬到 5 会连带砍掉 `Anne: Yes, of course.` 这类真实短对话。
    """
    assert _verdict("Why do you like?") == "KEPT_CORPUS"
    assert _verdict("Anne: Yes, of course.") == "KEPT_CORPUS"


# --------------------------------------------------------------------------
# 句子拼接：必须有上限，否则版面碎片堆成一个假句子
# --------------------------------------------------------------------------


def test_split_sentences_caps_unterminated_buffer():
    """实测：某页 24 个 box 被并成 1 句 200+ 词 —— 那不是句子。

    音标表/单词表这类无句末标点的排版块必须收口丢弃，不能硬拼。
    """
    boxes = [(f"word{i}", 0.95) for i in range(60)]  # 60 个无标点 box
    sents = pep.split_sentences_scored(boxes)
    assert all(len(s["text"].split()) <= pep._MAX_SENT_WORDS for s in sents)


def test_split_sentences_joins_a_sentence_split_across_boxes():
    """OCR 常把一句拆成多行（`Put up your hand if you want to ask your teacher` +
    `a question.`），必须能接回来。"""
    boxes = [
        ("Put up your hand if you want to ask your teacher", 0.93),
        ("a question.", 0.94),
    ]
    sents = pep.split_sentences_scored(boxes)
    assert len(sents) == 1
    assert sents[0]["n_boxes"] == 2
    assert sents[0]["text"] == "Put up your hand if you want to ask your teacher a question."


def test_split_sentences_drops_noise_boxes_before_buffering():
    """水印若不被剔，会被拼进第一句并把它染成 HAS_CJK。"""
    boxes = [
        ("人民龙育出版社", 0.99),
        ("I like reading after school.", 0.93),
    ]
    sents = pep.split_sentences_scored(boxes)
    assert len(sents) == 1
    assert "人民" not in sents[0]["text"]

# --------------------------------------------------------------------------
# 生产数据里实测到的两类漏网（在 1,318 条真实保留句里肉眼抓到的）
# --------------------------------------------------------------------------


def test_exercise_numbered_prompt_is_rejected():
    """实测：`4. What can you do to manage your own emotions and stay positive?`

    那是题型提示（问学生要什么），不是课文句子。首词判据抓不到，因为首词是数字。
    """
    assert (
        _verdict("4. What can you do to manage your own emotions and stay positive?")
        == pep.REJECT_IMPERATIVE_TASK
    )
    assert _verdict("3. Whose tennis racket is it? How do you know?") == pep.REJECT_IMPERATIVE_TASK


def test_wordlist_run_is_rejected():
    """实测：`cap, glove, form, balloon, scissors, bamboo It's made of used wood and glass.`

    前半是并列名词（器材清单）不是句子，后半被并进来。`_SENT_END` 挡不住 ——
    它是在句末才结束的。
    """
    s = "cap, glove, form, balloon, scissors, bamboo It's made of used wood and glass."
    assert _verdict(s) == pep.REJECT_NOT_PROSE


def test_box_cache_is_read_without_touching_the_model(tmp_path, monkeypatch):
    """原始 box 缓存：调门禁必须不必重跑 OCR（9.4s/页，179 页半小时）。

    构造法：先手写一份缓存，再把 ``_OCR`` 换成会炸的对象 —— 若代码真的去调
    模型就会 TypeError，从而证明走了缓存。
    """
    import json as _json

    boxes = [["I like reading.", 0.93], ["人民龙育出版社", 0.99], ["Me too!", 0.91]]
    jpg = tmp_path / "g7b" / "p7.jpg"
    jpg.parent.mkdir(parents=True)
    jpg.write_bytes(b"x" * 20_000)
    cache = tmp_path / "_boxes" / "g7b" / "p7.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(
        _json.dumps({"page": "7", "has_cjk": True, "boxes": boxes}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(pep, "_BOX_CACHE_DIR", tmp_path / "_boxes")

    class _Boom:
        def __call__(self, *a, **kw):  # pragma: no cover - 走到就是失败
            raise AssertionError("命中缓存时不得调用 OCR")

    monkeypatch.setattr(pep, "_OCR", _Boom())
    out = pep.ocr_page(jpg)
    assert out["from_cache"] is True
    assert out["page"] == "7"
    assert out["has_cjk"] is True
    assert out["boxes"][0] == ("I like reading.", 0.93)
    # 缓存里的水印仍要走噪声剔除
    sents = pep.split_sentences_scored(out["boxes"])
    assert all("人民" not in s["text"] for s in sents)
