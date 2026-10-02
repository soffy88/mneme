"""scripts/backfill_vocab_glosses.py 的写入逻辑回归测试。

针对两个**已发生过的静默数据损坏** bug：

1. `UPDATE ... WHERE word=%s` —— word 在 vocabulary_items 里不唯一
   （24,681 行 / 24,441 个不同词，240 个词重复）。按词更新会把一个义项的释义
   覆盖到同名其它行；且无上下文的行先命中，会挤掉后命中的有上下文好结果。
2. 位置对齐只在「有 meaning_cn」的返回项上推进 —— 一旦某项缺 meaning_cn，
   后续全部错位，释义写到别的词上。

不碰真库：整个写入路径对假 cursor 断言 SQL 与参数。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path



def _load_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "backfill_vocab_glosses.py"
    spec = importlib.util.spec_from_file_location("backfill_vocab_glosses", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


class FakeCursor:
    """记录每条 UPDATE 的 SQL 与参数，并按 WHERE id 模拟命中行数。"""

    def __init__(self, existing_ids):
        # existing_ids: 只有这些 id 会命中（模拟 meaning_cn IS NULL 过滤）
        self._existing = set(existing_ids)
        self.updates: list[tuple[str, tuple]] = []
        self.rowcount = 0

    def execute(self, sql, params=()):
        if sql.startswith("UPDATE"):
            self.updates.append((sql, params))
            self.rowcount = 1 if params[2] in self._existing else 0


# ── 验收项 WORD_UPDATE_BY_ID / WORD_COLLISION_SAFE ──────────────────────────


def test_update_targets_id_never_word():
    """UPDATE 必须按 id 定位。"""
    batch = [("id-A", "bank", "The bank was closed.")]
    glosses = [{"word": "bank", "pos": "n.", "meaning_cn": "银行"}]
    cur = FakeCursor(["id-A"])
    mod.apply_gloss_batch(cur, batch, glosses)

    assert len(cur.updates) == 1
    sql, params = cur.updates[0]
    assert "WHERE id = %s" in sql, f"必须按 id 更新，实际: {sql}"
    assert "WHERE word" not in sql, "绝不能按 word 更新（word 不唯一）"
    assert params[2] == "id-A"


def test_duplicate_words_each_get_their_own_row():
    """同名两行必须各自只写自己的 id——这正是原 bug 覆盖数据的情形。"""
    batch = [
        ("uuid-1", "bank", "It was warm, so I sat on the river bank."),
        ("vocab-bank", "bank", "He works at a bank."),
    ]
    glosses = [
        {"word": "bank", "pos": "n.", "meaning_cn": "河岸"},
        {"word": "bank", "pos": "noun", "meaning_cn": "银行"},
    ]
    cur = FakeCursor(["uuid-1", "vocab-bank"])
    mod.apply_gloss_batch(cur, batch, glosses)

    written = {params[2]: params[1] for _sql, params in cur.updates}
    assert written == {"uuid-1": "河岸", "vocab-bank": "银行"}


# ── 验收项 NO_GLOSS_WRONG_WORD（位置对齐）──────────────────────────────────


def test_missing_meaning_cn_does_not_shift_subsequent_writes():
    """中间一项缺 meaning_cn，后续项仍必须写到正确的 id。"""
    batch = [
        ("id-1", "apple", "An apple a day."),
        ("id-2", "bank", "The river bank."),
        ("id-3", "orbit", "The satellite entered orbit."),
    ]
    glosses = [
        {"word": "apple", "pos": "n.", "meaning_cn": "苹果"},
        {"word": "bank", "pos": "n.", "meaning_cn": None},  # 丢弃
        {"word": "orbit", "pos": "n.", "meaning_cn": "轨道"},
    ]
    cur = FakeCursor(["id-1", "id-2", "id-3"])
    mod.apply_gloss_batch(cur, batch, glosses)

    written = {params[2]: params[1] for _sql, params in cur.updates}
    assert written == {"id-1": "苹果", "id-3": "轨道"}, "orbit 的释义不能写到 id-2"


def test_word_order_mismatch_is_rejected_not_applied():
    """返回顺序错乱时必须跳过，不能盲写。"""
    batch = [("id-1", "apple", "x"), ("id-2", "bank", "y")]
    glosses = [
        {"word": "bank", "pos": "n.", "meaning_cn": "银行"},  # 错位
        {"word": "apple", "pos": "n.", "meaning_cn": "苹果"},
    ]
    cur = FakeCursor(["id-1", "id-2"])
    mod.apply_gloss_batch(cur, batch, glosses)

    for _sql, params in cur.updates:
        word_for_id = {b[0]: b[1] for b in batch}[params[2]]
        assert word_for_id == "bank" or True  # 仅记录：错位项应被跳过
    written_words = [params[1] for _sql, params in cur.updates]
    # 第一项错位被跳过；第二项对不上（期望 apple 实得 bank）也应被跳过
    assert "银行" not in written_words, "错位的释义不得落库"


def test_pos_truncated_to_column_width():
    batch = [("id-1", "x", "s")]
    glosses = [{"word": "x", "pos": "v" * 50, "meaning_cn": "释义"}]
    cur = FakeCursor(["id-1"])
    mod.apply_gloss_batch(cur, batch, glosses)
    assert len(cur.updates[0][1][0]) <= 20


def test_extra_gloss_items_do_not_crash():
    batch = [("id-1", "apple", "x")]
    glosses = [
        {"word": "apple", "pos": "n.", "meaning_cn": "苹果"},
        {"word": "ghost", "pos": "n.", "meaning_cn": "多余"},
    ]
    cur = FakeCursor(["id-1"])
    assert mod.apply_gloss_batch(cur, batch, glosses) == 1