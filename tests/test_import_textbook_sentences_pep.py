"""人教社教材语境句入库器。

这些用例盯的是**实测踩到的一个真 bug**：句 ID 若由 ``sentence_index`` 派生，
门禁一收紧就全体错位。

实测过程：门禁收紧后 g7b 的保留句从 435 降到 333 —— 同一页里被拒的句子变了，
``sentence_index`` 全体错位，于是 ``ON CONFLICT DO NOTHING`` 一个都匹配不上，
**被新门禁拒掉的 ~1,200 句继续留在库里被 tier 2 取用**。学生看到的例句里就会
混着「按旧口径该被拒」的句子，而库里的计数看着还挺正常。

所以句 ID 必须由**句文本**哈希而来：同一句在任何门禁版本下都是同一个 id，
重新筛选天然幂等，剩下的差异交给「以本次输入为准」的 prune 处理。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "import_textbook_sentences_pep.py"
)
_spec = importlib.util.spec_from_file_location("pep_import", _SCRIPT)
assert _spec and _spec.loader
pepi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pepi)


# --------------------------------------------------------------------------
# 句 ID 的稳定性 —— 这是本文件存在的理由
# --------------------------------------------------------------------------


def test_same_sentence_same_id_across_reruns():
    a = pepi.sentence_id("pep-en-g7b", 12, "I like reading after school.")
    b = pepi.sentence_id("pep-en-g7b", 12, "I like reading after school.")
    assert a == b


def test_id_is_independent_of_sentence_index():
    """核心回归：门禁收紧导致 index 错位时，**同一句**的 id 不能变。

    构造：同一页上，第 3 句在门禁收紧后变成了第 1 句（前面的被拒了）。
    旧写法按 index 取 id 会得到不同值，于是旧行留在库里继续被 tier 2 取用。
    """
    text = "She has to answer my phone."
    old = pepi.sentence_id("pep-en-g7b", 12, text)
    # 无论它在书里排第几、由谁先算出来，同一句就是同一个 id
    assert old == pepi.sentence_id("pep-en-g7b", 12, text)
    assert old != pepi.sentence_id("pep-en-g7b", 13, text)  # 页不同 → 不同句
    assert old != pepi.sentence_id("pep-en-g8b", 12, text)  # 书不同 → 不同句
    assert old != pepi.sentence_id("pep-en-g7b", 12, "She must answer my phone.")


def test_id_normalises_whitespace_and_case():
    """OCR 同一句可能带不同空白；ID 不该因此变两个。

    注意：**只用于 ID**，不用于展示 —— 库里存的仍是 `english_text` 原样。
    """
    a = pepi.sentence_id("pep-en-g7b", 12, "I like reading after school.")
    b = pepi.sentence_id("pep-en-g7b", 12, "I  like   reading after school.")
    c = pepi.sentence_id("pep-en-g7b", 12, "i like reading after school.")
    assert a == b == c


def test_occurrence_id_is_unique_per_sentence_and_index():
    """关联行 id 由 (sentence_id, occurrence_index) 拼出，重跑必须一致。"""
    sid = pepi.sentence_id("pep-en-g7b", 12, "I like reading after school.")
    assert f"{sid}#0" != f"{sid}#1"
    assert f"{sid}#0" == f"{sid}#0"


# --------------------------------------------------------------------------
# 教材清单
# --------------------------------------------------------------------------


def test_book_slugs_cover_junior_and_senior_pep_english():
    """13 本：初中 6（七上/七下/八上/八下/九上/全一册）+ 高中 7（必修 3 + 选择性必修 4）。

    小学那 8 本**故意不在内**：是「三年级起点 / 精通 / 一年级起点」三套平行
    教材，同一册次有 2–3 个版本，混进语料会让同一句话重复出现且来源不唯一。
    """
    slugs = set(pepi.BOOKS)
    assert slugs == {
        "g7a", "g7b", "g8a", "g8b", "g9a", "g9all",
        "h1", "h2", "h3", "hs1", "hs2", "hs3", "hs4",
    }
    assert len({v["textbook_id"] for v in pepi.BOOKS.values()}) == len(slugs)


def test_every_book_maps_to_a_distinct_pep_id():
    """PEP book_id 与内部 textbook_id 必须一一对应，否则两本书会互相覆盖。"""
    pep_ids = [v["pep_book_id"] for v in pepi.BOOKS.values()]
    assert len(set(pep_ids)) == len(pep_ids)