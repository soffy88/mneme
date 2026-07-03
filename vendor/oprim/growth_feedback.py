"""成长型思维反馈框架（Dweck；教育理念 05）。纯函数，确定性。

原则：过程表扬（努力/策略/进步）而非"聪明"；未掌握＝"还没(not yet)"；错误正常化
（错误是学习的一部分、大脑正在长）。据 (对错 × 错因 × 是否吃力) 选一句成长型措辞。
"""

from __future__ import annotations


def growth_message(
    *,
    is_correct: bool,
    error_type: str | None = None,
    struggled: bool = False,
) -> str:
    """返回一句成长型思维措辞（表扬过程、错误正常化、"还没"文化）。"""
    if is_correct:
        if struggled:
            # 表扬坚持/努力（desirable difficulty）——最该被强化的行为
            return "难点也啃下来了——这种'吃力但做对'最长本事，说明你在真正学。"
        return "做对了，你的方法在见效——保持这个节奏。"

    # 做错：错误正常化 + 归因于可改变的策略，而非能力
    if error_type == "careless":
        return "会做但错了——差的不是能力，是细心。慢一步、回头检查就稳了。"
    if error_type == "dontknow":
        return "这个点你'还没'掌握——大脑正是在这种地方长出来的。回讲解补一下再来一次。"
    return "错了很正常，错误是学习的一部分。看看差在哪，再试一次，你会更强。"


__all__ = ["growth_message"]
