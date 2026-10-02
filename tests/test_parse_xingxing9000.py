"""scripts/parse_xingxing9000.py 的归属判定回归测试。

钉住三类**真实发生过的错误**：

1. **象形体的分组错配**。象形9000 把形近/音近词编在一组，组头列多个词而其下
   只有一条详情块。纯靠「音标块上方同列最近的那个词」会把 `absent` 挂上
   `solitary` 的音标释义 —— 而 docx 版的例句 `There is a solitary figure`
   明示那条属于 `solitary`。行相邻不能当归属，必须由例句交叉验证。
2. **OCR 行末连字符与丢空格**：`atten- tion`、`Ihave faiththat` 会让朴素的
   单词边界匹配失效，把正确归属误判成错配。
3. **英语形态丢字母**：`ride` + `ing` -> `riding`、`carry` + `ies` -> `carries`。
   漏掉这条会把正确归属误判为存疑。

反向也钉一条：**不做 OCR 形近字容错**。`physicai` / `yeliow` / `vaiuable`
必须留在 `ownership_verified=False` 里等人工看 —— 放宽形近字会把真实错配
一起掩盖掉。
"""

from __future__ import annotations

from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "parse_xingxing9000.py"
    src = path.read_text(encoding="utf-8")
    # 该模块 import 了 obase.db（依赖 rapidfuzz），纯函数单测里绕开 DB 层。
    src = src.replace("    from obase.db import SessionLocal", "    SessionLocal = None  # test stub")
    src = src.replace(
        "    from services.models import VocabularyXiangxing",
        "    VocabularyXiangxing = None  # test stub",
    )
    import types

    mod = types.ModuleType("parse_xingxing9000")
    mod.__file__ = str(path)
    exec(compile(src, str(path), "exec"), mod.__dict__)
    return mod


mod = _load_module()


def _line(text: str, x0: int, y0: int, w: int = 90, h: int = 18):
    return {"text": text, "conf": 0.9, "x0": x0, "x1": x0 + w, "y0": y0, "y1": y0 + h}


def _page(lines):
    return {"pdf": "第一册  上[vxia.net].pdf", "page": 1, "low_conf": 0, "lines": lines}


def test_ownership_requires_example_mention():
    """组头相邻但例句不包含该词 -> 不确认归属。"""
    lines = [
        _line("absent", 100, 500),
        _line("solitary", 100, 530),
        _line("['sa:leteri] adj.单独的,孤独的", 100, 566),
        _line("There is a solitary figure off in the distance.", 100, 600),
        _line("远处有一个孤独的身影。", 100, 640),
    ]
    recs = mod.parse_page(_page(lines))
    by_word = {r["word"]: r for r in recs}
    assert "solitary" in by_word
    assert by_word["solitary"]["ownership_verified"] is True
    # absent 不该被这条详情块认领
    assert not by_word.get("absent", {}).get("ownership_verified")


def test_pos_not_in_whitelist_is_rejected():
    """OCR 把 `adj.` 读成 `adi.` —— 形近字必须被白名单挡住。"""
    lines = [
        _line("attack", 100, 500),
        _line("[et'ek] adi.攻击;袭击", 100, 566),
    ]
    assert mod.parse_page(_page(lines)) == []


def test_hyphenated_linebreak_still_verifies():
    """`atten- tion` 是同一个词的换行，不能因此判为错配。"""
    lines = [
        _line("attention", 100, 500),
        _line("[et'en6n] n.注意", 100, 566),
        _line("This sign requires your full atten-", 100, 600),
        _line("tion; there is danger ahead.", 100, 630),
    ]
    recs = mod.parse_page(_page(lines))
    assert len(recs) == 1
    assert recs[0]["word"] == "attention"
    assert recs[0]["ownership_verified"] is True


def test_lost_spaces_still_verifies():
    """OCR 丢空格（`Ihave faiththat`）不能导致误判。"""
    lines = [
        _line("faith", 100, 500),
        _line("[fei6] n.信仰", 100, 566),
        _line("Ihave faiththat the church will guide me", 100, 600),
    ]
    recs = mod.parse_page(_page(lines))
    assert recs[0]["ownership_verified"] is True


def test_e_drop_inflection_verifies():
    """ride + ing -> riding；carry + ies -> carries。"""
    assert mod.mentions("I am riding on a camel.", "ride") is True
    assert mod.mentions("He carries the bag.", "carry") is True
    assert mod.mentions("They are making noise.", "make") is True


def test_ocr_shape_noise_is_not_forgiven():
    """形近字不做容错：`physicai` 不是 `physical`，须留待人工。"""
    assert mod.mentions("Their relationship is quite physicai.", "physical") is False
    assert mod.mentions("Lemons are yeliow.", "yellow") is False


def test_missing_anchor_is_dropped():
    """音标块上方找不到同列词 -> 整条丢弃，而不是猜一个词挂上去。"""
    lines = [
        _line("orphan-ipa-block", 900, 566),
        _line("[something] n.某词", 900, 566),
    ]
    assert mod.parse_page(_page(lines)) == []


def test_leading_page_number_noise_is_stripped():
    """`5238750953135absent` 里的页码噪声要剥掉。"""
    assert mod.strip_leading_page_no("5238750953135absent") == "absent"
    assert mod.strip_leading_page_no("absence") == "absence"


def test_ipa_trailing_bracket_noise_cleaned():
    """OCR 常把右括号读成 `] ]`，清洗后不能把噪声留进 ipa。"""
    assert mod.clean_ipa("'erb         ]") == "'erb"
    assert mod.clean_ipa("e'bav") == "e'bav"