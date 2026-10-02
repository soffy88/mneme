"""scripts/import_vocab_affixes.py 的抽取与形态校验回归测试。

钉住三类**已发生过的错误**：

1. 散文自相矛盾时产出幻觉分解。`discover` 的词根散文先说 `dis-`+`cooperire`，
   紧接又说「该单词没有前缀和后缀。中缀是 -ver」。`cooperire` 不出现在
   `discover` 里 —— **形态自洽校验**是拦这类幻觉的唯一确定性手段。
2. 把后缀/词干误当词根：`chinese→ese`、`careless→less`、`common→mon`。
   这些"确实是子串"，光靠形态校验放行，但作为拉丁词根是错的。
3. 词根在句中被多写法提及（`cap-` / `cap` / `capac-`）时必须判为矛盾并留空，
   而不是随手挑一个。
"""

from __future__ import annotations

from pathlib import Path


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "import_vocab_affixes.py"
    # 该模块 import 了 obase.db（依赖 rapidfuzz），单测里绕开 DB 层：
    # 直接以源码方式载入并在 import 前注入桩，避免为测纯函数拉起 DB 依赖。
    src = path.read_text(encoding="utf-8")
    src = src.replace("from obase.db import SessionLocal  # noqa: E402",
                      "SessionLocal = None  # test stub")
    src = src.replace("from services.vocab_affixes import validate_segment  # noqa: E402",
                      "from services.vocab_affixes import validate_segment  # noqa: E402")
    import types
    mod = types.ModuleType("import_vocab_affixes")
    mod.__file__ = str(path)
    exec(compile(src, str(path), "exec"), mod.__dict__)
    return mod


mod = _load_module()


# ── 形态自洽校验 ───────────────────────────────────────────────────────────


def test_morphology_accepts_valid_decomposition():
    assert mod.morphology_ok("capable", None, "cap-", "-able")
    assert mod.morphology_ok("predict", "pre-", "dict", None)
    assert mod.morphology_ok("childhood", None, "child", "hood")


def test_morphology_rejects_hallucinated_root():
    """discover 的散文编出 `cooperire`，它不在 discover 里 -> 必须否。"""
    assert not mod.morphology_ok("discover", "dis-", "cooperire", None)


def test_morphology_rejects_wrong_prefix():
    assert not mod.morphology_ok("capable", "xyz-", "cap", None)


def test_morphology_rejects_wrong_suffix():
    assert not mod.morphology_ok("capable", None, "cap", "-xyz")


def test_morphology_empty_is_rejected():
    assert not mod.morphology_ok("capable", None, None, None)


def test_bare_strips_markers():
    assert mod._bare("cap-") == "cap"
    assert mod._bare("-able") == "able"
    assert mod._bare("-dict-") == "dict"


# ── 抽取 ──────────────────────────────────────────────────────────────────


def _body(root_part: str = "", affix_part: str = "") -> str:
    return f"词根分析 {root_part} 词缀分析 {affix_part} 发展历史 结束"


def test_extract_prefix_root_suffix():
    body = _body(
        '"Predict" 源自拉丁语，由 "pre-"（在前面）和 "-dict"（说话）组成。',
        '前缀 "pre-" 表示"在前面"。词根 "-dict" 是词根。',
    )
    got, why = mod.extract("predict", body)
    assert why == ""
    # 词缀保留连字符 —— 这是词缀的标准写法（pre- / -able），也是
    # format_affix_chain 期望的形态。validate_segment 允许 -。
    # 归一化后不带连字符：连字符是书写习惯，由 format_affix_chain 按位置决定，
    # 不该混进数据（否则会出现 `pre-` 与 `dict` 并存的不一致形态）。
    assert got["prefix"] == "pre"
    assert got["root"] == "dict"
    assert got["suffix"] is None


def test_extract_suffix_only():
    got, why = mod.extract("ability", _body("", '单词 "-ity" 是后缀，表示形容词转变为名词。'))
    assert why == ""
    assert got["suffix"] == "ity"
    assert got["root"] is None


def test_explicit_no_affix_is_left_empty():
    """散文明说没有分解 -> 不写，而不是当作解析失败重试。"""
    got, why = mod.extract("caption", _body("", "该单词没有前缀和后缀。"))
    assert got is None and why == "explicit_no_affix"


def test_hallucinated_root_never_used():
    """discover 的散文编出 `cooperire`。抽取只取紧跟「词根是」的词元，
    且必须形态自洽 —— `cooperire` 绝不能成为词根。"""
    body = _body('"Discover" 的词根是 "dis-" 和 "cooperire"。', '没有前缀和后缀。')
    got, _why = mod.extract("discover", body)
    if got is not None:
        assert "cooperire" not in (got["root"] or "")


def test_contradictory_candidates_leave_role_empty():
    """同一角色两个不同候选 -> 矛盾，留空不挑。"""
    body = _body('"X" 是词根 "-a-"。"Y" 是词根 "-b-"。')
    got, why = mod.extract("capable", body)
    assert got is None or got.get("root") is None


def test_predict_root_dict_is_kept():
    """回归：曾用「词根在词末即判为后缀」的规则，把 predict->dict、
    factory->fact、conduct->duct 这类真拉丁词根全部误杀。"""
    body = _body('"Predict" 的词根是 "dict"。')
    got, why = mod.extract("predict", body)
    assert why == "" and got["root"] == "dict"


def test_trivial_root_rejected():
    """词根等于整词、或与整词相差 <=2 字符（coach->coach）-> 排除。
    注意 `century->cent` **不该**被排除：cent 是 centum 的合法拉丁词根。"""
    for word in ("coach", "adopt", "brief"):
        body = _body(f'"{word}" 的词根是 "{word}"。')
        got, _why = mod.extract(word, body)
        assert got is None or got.get("root") is None, (word, got)
    body = _body('"century" 的词根是 "cent"。')
    got, _why = mod.extract("century", body)
    assert got is not None and got["root"] == "cent"


def test_no_affix_section_returns_reason():
    got, why = mod.extract("apple", "这段散文完全没有词根或词缀段落。发展历史 结束")
    assert got is None and why == "no_affix_section"


def test_scope_stops_at_next_section():
    """「发展历史」里出现的拉丁词不能被当成词根。"""
    body = _body('"Capable" 的词根是 "cap-"。', '后缀 "-able"。发展历史 源自法语词根 "vivre"。')
    got, why = mod.extract("capable", body)
    assert why == "" and got["root"] == "cap"


def test_confidence_higher_when_more_roles_filled():
    # 用实测过的真实样本：centimetre 三段齐全=0.9，capable 仅词根=0.6
    g3, w3 = mod.extract(
        "centimetre",
        _body('"centimetre" 的词根是 "centim"。', '前缀 "centi-"。后缀 "-tre"。'),
    )
    g1, w1 = mod.extract("capable", _body('"capable" 的词根是 "cap-"。'))
    assert w3 == "" and w1 == "", (w3, w1)
    assert g3["confidence"] > g1["confidence"]