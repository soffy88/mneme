"""scripts/backfill_vocab_phonetics.py 的解析与查表回归测试。

存在的理由：一个真实且**静默**的 bug。CMUdict 解析最初写成
`line.rsplit(' ', 1)`（按最后一个空格切），把音标截到只剩最后一个音素、并把
前面的音素并进「词」里。结果不是报错，而是「几乎全部查不到」——核心范围命中
0.1% 而不是 81.7%。若没有测试，这个数字看起来就像「CMUdict 覆盖不了核心词」
的结论，会导致放弃音标这一步。

所以这里直接钉住：多音素词必须完整解析、查表大小写无关、英式变体可用。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "backfill_vocab_phonetics.py"
    spec = importlib.util.spec_from_file_location("backfill_vocab_phonetics", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()

SAMPLE = """\
;;; # CMUdict sample
apple AE1 P AH0 L
africa AE1 F R AH0 K AA0
escape IH0 S K EY1 P
# a comment
read R EH1 D
"""


@pytest.fixture()
def cmudict(tmp_path: Path) -> dict[str, str]:
    p = tmp_path / "cmudict.dict"
    p.write_text(SAMPLE, encoding="latin-1")
    return mod.load_cmudict(p)


# ── 解析：整个音标串必须保留 ────────────────────────────────────────────────


def test_multi_phoneme_pronunciation_is_kept_whole(cmudict):
    """这是 rsplit bug 的核心断言：音素一个都不能丢。"""
    assert cmudict["apple"] == "AE1 P AH0 L"
    assert cmudict["africa"] == "AE1 F R AH0 K AA0"
    assert len(cmudict["africa"].split()) == 6


def test_rsplit_would_have_corrupted_the_dict(cmudict):
    """反向证明：按最后一个空格切会产出什么样的垃圾，作为 bug 的可读说明。"""
    line = "africa AE1 F R AH0 K AA0"
    bad_word, bad_pron = line.rsplit(" ", 1)
    assert bad_pron == "AA0"                      # 只剩最后一个音素
    assert "africa" not in bad_word.lower() or bad_word != "africa"
    assert bad_pron != cmudict["africa"]


def test_comments_and_blank_lines_skipped(cmudict):
    assert not any(k.startswith(";") for k in cmudict)
    assert "" not in cmudict


def test_single_phoneme_word_parses(cmudict):
    assert cmudict["read"] == "R EH1 D"


# ── 查表 ──────────────────────────────────────────────────────────────────


def test_lookup_is_case_insensitive(cmudict):
    """核心范围里是 Africa / April 这种大写专名，CMUdict 全小写。"""
    assert mod.lookup("Africa", cmudict) == ("AE1 F R AH0 K AA0", "direct")
    assert mod.lookup("AFRICA", cmudict)[1] == "direct"


def test_lookup_direct_hit(cmudict):
    pron, how = mod.lookup("escape", cmudict)
    assert pron == "IH0 S K EY1 P"
    assert how == "direct"


def test_lookup_miss_returns_none(cmudict):
    assert mod.lookup("nonexistentword", cmudict) == (None, "none")


def test_lookup_empty_word(cmudict):
    assert mod.lookup("   ", cmudict) == (None, "none")


# ── 英式变体：显式映射，且必须能审计 ──────────────────────────────────────


def test_british_variant_resolves_via_explicit_map():
    d = {"airplane": "EH1 R P L EY2 N"}
    pron, how = mod.lookup("aeroplane", d)
    assert pron == "EH1 R P L EY2 N"
    assert how == "variant:airplane", "变体命中必须自报来源，便于审计"


def test_variant_not_applied_when_target_absent(cmudict):
    """映射表里的词若 CMUdict 也没有，必须判 miss 而不是给错音。"""
    pron, how = mod.lookup("colourful", cmudict)
    assert pron is None and how == "none"


def test_variant_map_has_no_identity_entries():
    """映射表里不该有无意义的恒等项——那会让报告里的 variant 计数虚高。"""
    for british, american in mod.BRITISH_TO_AMERICAN.items():
        assert british != american, f"恒等映射无意义: {british}"
        assert british == british.lower() and american == american.lower()


def test_variant_map_targets_exist_in_cmudict_when_file_present():
    """若 CMUdict 在仓库里，每个变体目标都应真的查得到（防止映射写错/词典换版）。"""
    path = mod.DEFAULT_DICT
    if not path.exists():
        pytest.skip("CMUdict 未下载到 data/external/，跳过")
    d = mod.load_cmudict(path)
    missing = [am for am in mod.BRITISH_TO_AMERICAN.values() if am not in d]
    assert not missing, f"映射目标不在 CMUdict 中: {missing}"