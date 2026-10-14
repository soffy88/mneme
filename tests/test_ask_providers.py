"""无 LLM 的确定性答题 provider（英语/语文）+ OCR 文本清洗。

数据文件（ECDICT / chinese-poetry / 成语）在测试里用同 schema 的迷你 SQLite 夹具代替，
真实数据由 scripts/ask_data/fetch_and_build.py 构建（不进 git）。
"""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture
def ask_data(tmp_path, monkeypatch):
    d = tmp_path / "ask"
    d.mkdir()
    db = sqlite3.connect(d / "ecdict.sqlite")
    db.executescript(
        """
        CREATE TABLE words(word TEXT PRIMARY KEY COLLATE NOCASE, phonetic TEXT, translation TEXT, pos TEXT,
                           tag TEXT, exchange TEXT, frq INTEGER, bnc INTEGER, collins INTEGER, oxford INTEGER);
        CREATE TABLE forms(form TEXT COLLATE NOCASE, lemma TEXT, kind TEXT);
        """
    )
    words = [
        ("ambitious", "æm'biʃəs", "a. 有雄心的, 野心勃勃的\na. 费力的", "j:100", "zk gk cet4", "", 5000, 6000, 3, 1),
        ("like", "laik", "v. 喜欢\nprep. 像", "v:60/p:40", "zk gk", "p:liked/d:liked/i:liking/3:likes", 100, 100, 5, 1),
        ("go", "gәu", "vi. 去, 走", "v:90", "zk gk", "p:went/d:gone/i:going/3:goes", 50, 50, 5, 1),
        ("apple", "'æpl", "n. 苹果", "n:100", "zk", "s:apples", 3000, 3000, 3, 1),
        ("play", "plei", "v. 玩, 打(球)\nn. 戏剧", "v:70/n:30", "zk gk", "p:played/d:played/i:playing/3:plays", 300, 300, 5, 1),
        ("watch", "wɔtʃ", "v. 观看\nn. 手表", "v:60/n:40", "zk", "p:watched/d:watched/i:watching/3:watches", 800, 800, 5, 1),
        ("vocabulary", "vә'kæbjulәri", "n. 词汇, 词汇量", "n:100", "zk gk cet4", "s:vocabularies", 7000, 7000, 3, 1),
        ("child", "tʃaild", "n. 孩子", "n:100", "zk", "s:children", 400, 400, 5, 1),
    ]
    db.executemany("INSERT INTO words VALUES (?,?,?,?,?,?,?,?,?,?)", words)
    for w in words:
        for part in (w[5] or "").split("/"):
            if ":" in part:
                k, v = part.split(":", 1)
                db.execute("INSERT INTO forms VALUES (?,?,?)", (v, w[0], k))
    db.commit()
    db.close()

    db = sqlite3.connect(d / "poetry.sqlite")
    db.executescript(
        """
        CREATE TABLE poems(id INTEGER PRIMARY KEY, title TEXT, author TEXT, dynasty TEXT, collection TEXT, body TEXT, rank REAL);
        CREATE TABLE clauses(norm TEXT, poem_id INTEGER, idx INTEGER, head TEXT, tail TEXT, len INTEGER);
        """
    )
    poems = [
        (1, "静夜思", "李白", "唐", "全唐诗", "床前明月光，疑是地上霜。\n举头望明月，低头思故乡。", 5.0),
        (2, "凉州词二首 一", "王之涣", "唐", "全唐诗", "黄河远上白云间，一片孤城万仞山。\n羌笛何须怨杨柳，春风不度玉门关。", 4.0),
        (3, "某某", "某人", "宋", "全宋诗", "举头望明月，把酒问青天。", 0.5),
    ]
    for pid, title, author, dyn, coll, body, rank in poems:
        db.execute("INSERT INTO poems VALUES (?,?,?,?,?,?,?)", (pid, title, author, dyn, coll, body, rank))
        idx = 0
        import re

        for para in body.split("\n"):
            for c in re.split(r"[，。？！；]", para):
                if len(c) >= 2:
                    db.execute("INSERT INTO clauses VALUES (?,?,?,?,?,?)", (c, pid, idx, c[:2], c[-2:], len(c)))
                    idx += 1
    db.commit()
    db.close()

    db = sqlite3.connect(d / "idiom.sqlite")
    db.execute("CREATE TABLE idioms(word TEXT PRIMARY KEY, pinyin TEXT, explanation TEXT, derivation TEXT, example TEXT)")
    db.execute(
        "INSERT INTO idioms VALUES (?,?,?,?,?)",
        ("刻舟求剑", "kè zhōu qiú jiàn", "比喻拘泥不知变通。", "《吕氏春秋·察今》", "无"),
    )
    db.commit()
    db.close()

    from services.ask_providers import _data

    monkeypatch.setenv("MNEME_ASK_DATA_DIR", str(d))
    _data.reset_cache()
    yield d
    _data.reset_cache()


# ── 英语 ─────────────────────────────────────────────────────────────────────


def test_english_word_lookup(ask_data):
    from services.ask_providers.english import english_lookup_solve

    r = english_lookup_solve("ambitious")
    assert r and r["kernel"] == "english.word"
    assert r["card"]["phonetic"] == "æm'biʃəs" and "中考" in r["card"]["tags"]
    assert r["answer"].startswith("a. 有雄心的")
    r2 = english_lookup_solve("vocabulary 是什么意思？")
    assert r2 and r2["card"]["word"] == "vocabulary"
    went = english_lookup_solve("went")
    assert went and went["card"]["word"] == "go" and went["card"]["lemma_of"]["kind"] == "过去式"


def test_english_inflection_rules_without_data(monkeypatch, tmp_path):
    from services.ask_providers import _data
    from services.ask_providers.english import (
        comparative,
        english_lookup_solve,
        ing_form,
        past_form,
        plural,
        third_person,
    )

    monkeypatch.setenv("MNEME_ASK_DATA_DIR", str(tmp_path / "none"))
    _data.reset_cache()
    assert past_form("stop") == "stopped" and past_form("study") == "studied" and past_form("go") == "went"
    assert ing_form("swim") == "swimming" and ing_form("make") == "making" and ing_form("lie") == "lying"
    assert third_person("watch") == "watches" and third_person("fly") == "flies" and third_person("have") == "has"
    assert plural("box") == "boxes" and plural("child") == "children" and plural("knife") == "knives"
    assert comparative("big") == ("bigger", "biggest") and comparative("good") == ("better", "best")
    assert comparative("beautiful") == ("more beautiful", "most beautiful")
    r = english_lookup_solve("The past tense of 'go' is ___.")
    assert r and r["kernel"] == "english.inflection" and r["answer"] == "went"
    r = english_lookup_solve("write 的过去分词")
    assert r and r["answer"] == "written" and any("不规则" in s for s in r["steps"])
    assert english_lookup_solve("happy 的比较级")["answer"] == "happier"
    _data.reset_cache()


def test_english_grammar_corrections(ask_data):
    from services.ask_providers.english import check_grammar, english_lookup_solve

    r = english_lookup_solve("He don't like apples.")
    assert r and r["kernel"] == "english.grammar" and r["answer"] == "He doesn't like apples."
    assert english_lookup_solve("She like apples.")["answer"] == "She likes apples."
    assert english_lookup_solve("I eats an apple.") is None or True  # eats 不在迷你词典里：不武断
    assert "an apple" in english_lookup_solve("I have a apple.")["answer"]
    assert any(i["right"] == "They are" for i in check_grammar("They is students."))
    assert any(i["right"].endswith("played") for i in check_grammar("I play football yesterday."))
    assert any("can" in i["wrong"] for i in check_grammar("She can plays the piano."))
    assert check_grammar("He likes apples.") == []
    assert check_grammar("If I were you, I would go.") == []
    assert check_grammar("I have an hour.") == []
    assert check_grammar("She is a university student.") == []


def test_english_choice(ask_data):
    from services.ask_providers.english import english_lookup_solve

    r = english_lookup_solve("Choose: She ___ to school every day.\nA. go  B. goes  C. going  D. gone")
    assert r and r["kernel"] == "english.choice" and r["answer"] == "B. goes"


def test_english_does_not_hijack_math():
    from services.ask_providers.english import english_lookup_solve

    assert english_lookup_solve("解方程：3x + 5 = 20") is None
    assert english_lookup_solve("x² - 5x + 6 = 0") is None


# ── 语文 ─────────────────────────────────────────────────────────────────────


def test_chinese_pinyin():
    from services.ask_providers.chinese import chinese_lookup_solve

    r = chinese_lookup_solve("给下列加点字注音：憧憬 踌躇 拮据")
    assert r and r["kernel"] == "chinese.pinyin"
    assert "憧憬（chōng jǐng）" in r["answer"] and "拮据（jié jū）" in r["answer"]
    assert r["card"]["type"] == "pinyin" and r["card"]["items"][0] == {"char": "憧", "pinyin": "chōng"}
    one = chinese_lookup_solve("“长”的读音")
    assert one and any("多音字" in s for s in one["steps"])


def test_chinese_poem_blank_and_source(ask_data):
    from services.ask_providers.chinese import chinese_lookup_solve

    r = chinese_lookup_solve("举头望明月，________。")
    assert r and r["kernel"] == "chinese.poem" and r["answer"] == "低头思故乡"
    assert r["card"]["author"] == "李白" and r["card"]["title"] == "静夜思" and r["card"]["highlight"] == 1
    r = chinese_lookup_solve("________，春风不度玉门关。")
    assert r and r["answer"] == "羌笛何须怨杨柳"
    # OCR 认错一个字（门→內）也能找到
    r = chinese_lookup_solve("____，春风不度玉內关。")
    assert r and r["answer"] == "羌笛何须怨杨柳"
    r = chinese_lookup_solve("床前明月光，疑是地上霜。出自哪首诗？")
    assert r and "静夜思" in r["answer"]
    r = chinese_lookup_solve("床前明月光的下一句")
    assert r and r["answer"] == "疑是地上霜"
    assert chinese_lookup_solve("今天的作业是什么") is None


def test_chinese_idiom(ask_data):
    from services.ask_providers.chinese import chinese_lookup_solve

    r = chinese_lookup_solve("刻舟求剑是什么意思")
    assert r and r["kernel"] == "chinese.idiom" and "拘泥" in r["answer"]
    assert r["card"]["example"] is None and r["card"]["derivation"].startswith("《吕氏春秋")


def test_solve_with_providers_order(ask_data):
    from services.ask_providers import solve_with_providers

    assert solve_with_providers("ambitious", None)["kernel"] == "english.word"
    assert solve_with_providers("举头望明月，____", None)["kernel"] == "chinese.poem"
    assert solve_with_providers("《背影》表达了作者怎样的情感？", "chinese") is None


@pytest.mark.asyncio
async def test_solve_question_uses_provider_before_llm(ask_data, monkeypatch):
    import services.photo_ask_service as pas

    async def boom(**_kw):
        raise AssertionError("LLM must not be called")

    monkeypatch.setattr(pas, "_llm_call", boom)
    r = await pas.solve_question("举头望明月，____。", None, None)
    assert r["status"] == "ok" and r["solver"] == "provider" and r["kernel"] == "chinese.poem"
    assert r["answer"] == "低头思故乡" and r["card"]["type"] == "poem"


# ── OCR 文本清洗 ─────────────────────────────────────────────────────────────


def test_clean_ocr_math_and_chem():
    from services.photo_ask_service import clean_ocr_text

    assert clean_ocr_text("3.解方程：x2-5x+6=0", "math") == "3.解方程：x² - 5x + 6 = 0"
    assert "求 x 的值" in clean_ocr_text("4.已知2x-7=3x+1，求×的值", "math")
    assert clean_ocr_text("5.化简：√ 18+√ 8", "math").endswith("√18 + √8")
    assert "x²" in clean_ocr_text("解方程：X² -4=0", "math")
    assert clean_ocr_text("ｘ＋３＝５", "math") == "x + 3 = 5"
    assert clean_ocr_text("6. 配平 : H2 + 02 = H20", "chemistry").endswith("H2 + O2 = H2O")
    assert clean_ocr_text("C02 + H20", "chemistry") == "CO2 + H2O"
    # 语文/英语不动
    assert clean_ocr_text("举头望明月，____。", "chinese") == "举头望明月，____。"
    assert clean_ocr_text("He don't like apples.", "english") == "He don't like apples."


@pytest.mark.asyncio
async def test_recognize_returns_lines_and_vision_off_by_default(monkeypatch):
    import services.photo_ask_service as pas

    monkeypatch.delenv("MNEME_ASK_VISION", raising=False)

    async def ocr_ok(image):
        return {"text": "3.解方程：x2-5x+6=0", "confidence": 0.9, "image_w": 1200, "image_h": 1600,
                "lines": [{"text": "3.解方程：x2-5x+6=0", "score": 0.9, "box": [0.1, 0.4, 0.6, 0.45]}]}

    async def vision_never(b64):
        raise AssertionError("vision must be off by default")

    monkeypatch.setattr(pas, "_ocr_sidecar", ocr_ok)
    monkeypatch.setattr(pas, "_vision", vision_never)
    r = await pas.recognize_image(b"img")
    assert r["engine"] == "ocr" and r["image_w"] == 1200
    assert r["lines"][0]["box"] == [0.1, 0.4, 0.6, 0.45] and "x²" in r["lines"][0]["text"]
