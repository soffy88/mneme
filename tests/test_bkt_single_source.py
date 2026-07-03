"""BKT 单源 fork 守卫（P2-11，审计指出 mneme 侧缺此守卫）。

内核契约：`oprim.bkt` 是指向 `oprim._cognitive`（canonical）的纯别名层，不得再各自定义
一份 BKT 实现（历史上曾双份、默认先验不一致）。本测试断言二者导出的是**同一对象**，
未来若有人在 bkt.py 重新贴一份实现，CI 立即变红。
"""

import oprim._cognitive as cognitive
import oprim.bkt as bkt

# bkt.py 对外暴露、且 _cognitive 也有的核心符号——必须逐一同源
_SHARED = ["bkt_update", "KCState"]


def test_bkt_symbols_are_aliases_of_cognitive():
    for name in _SHARED:
        assert hasattr(bkt, name), f"oprim.bkt 缺符号 {name}"
        assert hasattr(cognitive, name), f"oprim._cognitive 缺符号 {name}"
        assert getattr(bkt, name) is getattr(cognitive, name), (
            f"oprim.bkt.{name} 与 oprim._cognitive.{name} 不是同一对象——BKT 被重新 fork 了"
        )


def test_bkt_update_is_single_callable():
    """再保险：两条 import 路径拿到的 bkt_update 是同一函数（值语义等价的最强形式）。"""
    from oprim import bkt_update as top_level

    assert top_level is cognitive.bkt_update
    assert bkt.bkt_update is top_level
