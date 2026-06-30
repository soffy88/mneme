"""items 11/12：苏格拉底自适应脚手架 + 真实历史续接。无 DB，用录制 caller。"""
from pathlib import Path

import pytest

from omodul.socratic_session_workflow import (
    SocraticConfig,
    SocraticInput,
    socratic_session_workflow,
)

_OUT = Path("/tmp/claude-1000/mneme-test/socratic")


class RecordingCaller:
    def __init__(self):
        self.calls: list[dict] = []

    async def __call__(self, **kw):
        self.calls.append(kw)
        return {"content": "继续想想，这一步怎么来的？", "usage": {"input_tokens": 0, "output_tokens": 0}}


async def _run(history, new_msgs, base_hint=1):
    caller = RecordingCaller()
    res = await socratic_session_workflow(
        config=SocraticConfig(mode="deep", max_turns=20, hint_level=base_hint),
        input_data=SocraticInput(
            question_text="解方程 x+1=3",
            correct_answer="2",
            student_messages=new_msgs,
            conversation_history=history,
        ),
        output_dir=_OUT,
        caller=caller,
    )
    return res, caller


@pytest.mark.asyncio
async def test_history_seeded_processes_only_new_message():
    history = [
        {"role": "assistant", "content": "这道题在考什么？"},
        {"role": "user", "content": "解一元一次方程"},
        {"role": "assistant", "content": "下一步呢？"},
        {"role": "user", "content": "移项"},
    ]
    res, caller = await _run(history, ["x = 2 吗"])
    # 只处理 1 条新消息（不重算历史）
    assert len(res["turns"]) == 1
    # turn_count = 历史 user 轮(2) + 本轮(1)
    assert res["turn_count"] == 3
    # 模型看到真实历史：caller 收到的 messages 含历史 4 条 + 本轮 1 条
    assert len(caller.calls[0]["messages"]) >= 5


@pytest.mark.asyncio
async def test_hint_escalates_with_turns():
    # 空历史首轮 → 温和提示（level 1）
    _res, c1 = await _run([], ["不知道怎么开始"])
    assert "温和提示" in c1.calls[0]["system"]

    # 在同一题停留很久（历史 6 个 user 轮）→ 升到明确提示（level 3）
    long_hist = []
    for i in range(6):
        long_hist.append({"role": "user", "content": f"尝试{i}"})
        long_hist.append({"role": "assistant", "content": f"再想想{i}"})
    _res2, c2 = await _run(long_hist, ["还是不会"])
    assert "明确提示" in c2.calls[0]["system"]
