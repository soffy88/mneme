"""答案自动判定（确定性 oprim）。

选择题(A-D)与规范化后可精确匹配的短答 → 直接判对/错；
自由作答/长答案/无法可靠比对 → 返回 'unsure'，由调用方走"对照答案自评"兜底。
原则：宁可 unsure，绝不误判（误判比自评更伤信任）。
"""
from __future__ import annotations

import re

_FULL2HALF = str.maketrans("０１２３４５６７８９ＡＢＣＤａｂｃｄ", "0123456789ABCDabcd")


def _norm(s: str) -> str:
    s = (s or "").strip().translate(_FULL2HALF)
    s = s.replace("$", "").replace("\\", "").replace(" ", "").replace("　", "")
    s = s.replace("，", ",").replace("；", ";").replace("（", "(").replace("）", ")")
    return s.upper()


def _choice_set(s: str) -> str:
    letters = re.findall(r"[A-D]", (s or "").upper())
    return "".join(sorted(set(letters))) if letters else ""


def judge_answer(student: str, correct: str, question_type: str = "") -> dict:
    """student vs correct → {'verdict': 'correct'|'wrong'|'unsure'}。"""
    if not student or not student.strip() or not correct or not correct.strip():
        return {"verdict": "unsure"}
    sn, cn = _norm(student), _norm(correct)

    # 1) 选择题：参考答案规范化后只含 A-D（单选/多选）
    if re.fullmatch(r"[A-D]{1,4}", cn):
        if len(sn) <= 6:                      # 学生也得是"选项形态"，长答交自评
            sc = _choice_set(student)
            if sc:
                return {"verdict": "correct" if sc == cn else "wrong"}
        return {"verdict": "unsure"}

    # 2) 规范化完全相等
    if sn == cn:
        return {"verdict": "correct"}

    # 3) 短数值/符号：剥掉非关键字符后相等
    if len(cn) <= 8 and len(sn) <= 12:
        keep = lambda x: re.sub(r"[^0-9A-Z./=+\-]", "", x)
        c2, s2 = keep(cn), keep(sn)
        if c2 and s2 == c2:
            return {"verdict": "correct"}

    # 4) 自由作答/长答案 → 交自评
    return {"verdict": "unsure"}


__all__ = ["judge_answer"]
