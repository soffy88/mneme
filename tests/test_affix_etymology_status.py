"""词根词缀**可信档位**的分层契约。

为什么要有这层：库内 379 条分解的权威来源只是散文里「词根/前缀/后缀」的**标注**，
不是历史语言学。散文自身就常把词干/后缀写成「词根」（`careless→less`、
`chinese→ese`、`colour→col`）。按「单词深度记忆引擎 V2」自己的标准
（*"如果所谓'词根记忆法'只是人为联想，必须明确这是'记忆联想'，不是历史词源"*），
这些必须与已校验词源分层，**不得同屏同权**。

这里钉住两件事：
1. 展示层契约 —— 只有参考表佐证过的才能按词源讲；冲突项默认不展示。
2. 参考表角色判定踩过的三个坑（钉住防回退）：
   - `startswith` 当不出前缀：collection 的 collect 满足 startswith 但它是词根。
   - 长度启发式会判反：pardon 的 `par+don` 里 par 是前缀、don 是词根。
   - 要求「严格居内」会误弃：arrive 的 **rive 正在词尾**（拉丁词根大量落在词尾：
     arrive/rive、predict/dict、factory/fact）。
"""

from __future__ import annotations

from pathlib import Path

from services.vocab_affixes import (
    STATUS_DISPUTED,
    STATUS_MNEMONIC_ASSOCIATION,
    STATUS_REFERENCE_CONFIRMED,
    affix_payload,
    annotate_chain,
    is_source_bearing,
    should_display,
)


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "crossvalidate_affixes.py"
    src = path.read_text(encoding="utf-8")
    src = src.replace("    import services  # noqa: F401  (vendor sys.path shim)", "    pass")
    src = src.replace("    from obase.db import SessionLocal", "    SessionLocal = None  # test stub")
    src = src.replace("    from sqlalchemy import text", "    text = None  # test stub")
    import types

    mod = types.ModuleType("crossvalidate_affixes")
    mod.__file__ = str(path)
    exec(compile(src, str(path), "exec"), mod.__dict__)
    return mod


mod = _load_module()


# ---------- 展示层契约 ----------


def test_only_reference_confirmed_is_source_bearing():
    assert is_source_bearing(STATUS_REFERENCE_CONFIRMED) is True
    assert is_source_bearing(STATUS_MNEMONIC_ASSOCIATION) is False
    assert is_source_bearing(STATUS_DISPUTED) is False
    assert is_source_bearing(None) is False  # 缺档位按最保守处理


def test_disputed_is_hidden_by_default():
    """与参考表冲突时任何一方都可能错，默认不展示而不是挑一个显示。"""
    assert should_display(STATUS_DISPUTED) is False
    assert should_display(STATUS_MNEMONIC_ASSOCIATION) is True
    assert should_display(STATUS_REFERENCE_CONFIRMED) is True


def test_mnemonic_chain_is_labelled_but_confirmed_is_not():
    assert annotate_chain("care · less", STATUS_MNEMONIC_ASSOCIATION) == "care · less （记忆联想）"
    assert annotate_chain("pre · dict", STATUS_REFERENCE_CONFIRMED) == "pre · dict"
    assert annotate_chain("", STATUS_MNEMONIC_ASSOCIATION) == ""


def test_payload_defaults_to_mnemonic_when_status_missing():
    """老调用方不传档位时必须按最保守档处理，不能默认当成词源。"""
    p = affix_payload(prefix="pre", root="dict", suffix=None)
    assert p["etymology_status"] == STATUS_MNEMONIC_ASSOCIATION
    assert p["is_source_bearing"] is False
    assert p["should_display"] is True
    assert p["display_chain"] == "pre · dict （记忆联想）"


def test_payload_confirmed_has_clean_chain():
    p = affix_payload(prefix="ar", root="rive", suffix=None,
                      etymology_status=STATUS_REFERENCE_CONFIRMED)
    assert p["chain"] == "ar · rive"
    assert p["display_chain"] == "ar · rive"
    assert p["is_source_bearing"] is True


# ---------- 参考表角色判定：钉住三个踩过的坑 ----------


def test_stem_is_not_a_prefix_just_because_startswith():
    """collection 的 collect 满足 startswith，但它是词根不是前缀。"""
    out = mod.classify("collection", ["collect", "ion"])
    # 两段式角色有歧义，参考表只保留段位集合，角色留空 —— 但绝不能把 collect
    # 判成 prefix（那会让「按参考表背书」得出错误的角色）。
    assert out is not None
    assert out.get("prefix") is None


def test_equal_length_pair_is_not_decided_by_length():
    """pardon = par + don，par 是前缀、don 是词根；长度启发式会判反。"""
    out = mod.classify("pardon", ["par", "don"])
    assert out is not None
    assert out.get("prefix") is None  # 不猜


def test_root_at_word_end_is_not_dropped():
    """arrive 的 rive 正在词尾 —— 拉丁词根大量落在词尾，不能因「非严格居内」被弃。"""
    out = mod.classify("arrive", ["ar", "rive"])
    assert out is not None
    assert sorted(out["segments"]) == ["ar", "rive"]


def test_three_token_roles_are_positional():
    """三段式按位置判角色：首=前缀、尾=后缀、中=词根。"""
    out = mod.classify("centimetre", ["centi", "metre", "tre"])
    assert out == {"prefix": "centi", "root": "metre", "suffix": "tre"}