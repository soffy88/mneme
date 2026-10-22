"""AetherViz 测验答案键 sympy 核验：cnm_148 Q2 双正确项事故必须被抓到；判不了的题不冒充已核验。"""

from __future__ import annotations

import ast
import pathlib

import pytest

from services import viz_quiz_verify as vq

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 线上 cnmath:cnm_148 课（2026-10-20 生成）的原题，逐字
CNM148 = [
    {
        "id": "q1",
        "prompt": "计算 \\((x + 3)^2\\) 的结果是？",
        "choices": ["\\(x^2 + 9\\)", "\\(x^2 + 6x + 9\\)", "\\(x^2 + 3x + 9\\)", "\\(x^2 + 6x + 3\\)"],
        "answer": 1,
    },
    {
        "id": "q2",
        "prompt": "下列式子中，计算正确的是？",
        "choices": [
            "\\((a - b)^2 = a^2 - b^2\\)",
            "\\((-a - b)^2 = a^2 + 2ab + b^2\\)",
            "\\((2x + 1)^2 = 4x^2 + 2x + 1\\)",
            "\\((a - 2b)^2 = a^2 - 4ab + 4b^2\\)",
        ],
        "answer": 3,
    },
    {
        "id": "q3",
        "prompt": "若 \\(x^2 + kx + 25\\) 是一个完全平方式，则 \\(k\\) 的值是？",
        "choices": ["\\(10\\)", "\\(\\pm 10\\)", "\\(5\\)", "\\(\\pm 5\\)"],
        "answer": 1,
    },
]


def test_cnm148_q2_two_correct_options_is_a_defect():
    r = vq.verify_item(CNM148[1])
    assert r["status"] == "defect" and r["mode"] == "identity" and r["correct"] == [1, 3], r


def test_cnm148_q1_verified_q3_unverifiable():
    r1, _, r3 = vq.verify_quiz(CNM148)
    assert r1["status"] == "verified" and r1["mode"] == "value" and r1["correct"] == [1], r1
    assert r3["status"] == "unverifiable", r3


def test_wrong_key_and_no_correct_option_are_defects():
    assert vq.verify_item({**CNM148[0], "answer": 2})["status"] == "defect"
    q = {**CNM148[1], "choices": [c for i, c in enumerate(CNM148[1]["choices"]) if i not in (1, 3)] + ["$x=x+1$"]}
    q["answer"] = 0
    r = vq.verify_item(q)
    assert r["status"] == "defect" and r["correct"] == [], r


def test_identity_single_correct_verified():
    q = {**CNM148[1], "choices": [*CNM148[1]["choices"][:1], "$(-a-b)^2=a^2-2ab+b^2$", *CNM148[1]["choices"][2:]]}
    assert vq.verify_item(q) == {"status": "verified", "mode": "identity", "negated": False, "correct": [3]}


def test_negated_prompt_inverts():
    q = {
        "id": "q",
        "prompt": "下列计算错误的是",
        "choices": ["$(a+b)^2=a^2+2ab+b^2$", "$(a-b)^2=a^2-b^2$", "$(a+1)^2=a^2+2a+1$"],
        "answer": 1,
    }
    r = vq.verify_item(q)
    assert r["status"] == "verified" and r["negated"] is True and r["correct"] == [1]


@pytest.mark.parametrize(
    ("prompt", "choices", "answer"),
    [
        ("$(a-b)^2=$", ["$a^2-b^2$", "$a^2-2ab+b^2$", "$a^2+b^2$"], 1),
        ("当 $x=2$ 时，$x^2+2x+1$ 的值是", ["8", "9", "$10$"], 1),
        ("计算 $\\frac{1}{2}\\times 4 + 3^2$", ["$11$", "$\\frac{22}{2}+1$", "13"], 0),
        ("计算 $(\\sqrt{2}+1)^2$", ["$3+2\\sqrt{2}$", "$3$", "$2\\sqrt2+1$"], 0),
        ("计算 $102^2$", ["$10404$", "$10204$", "$1044$"], 0),
        ("$(2x)^2 \\cdot x$ 等于", ["$4x^3$", "$2x^3$", "$4x^2$"], 0),
    ],
)
def test_value_questions_verified(prompt, choices, answer):
    r = vq.verify_item({"id": "q", "prompt": prompt, "choices": choices, "answer": answer})
    assert r["status"] == "verified", r


@pytest.mark.parametrize(
    ("prompt", "choices"),
    [
        ("方程 $x^2-5x+6=0$ 的解是", ["$x=2$", "$x=3$", "$x=2$ 或 $x=3$"]),
        ("因式分解 $x^2-9$", ["$(x+3)(x-3)$", "$x^2-9$", "$(x-3)^2$"]),
        ("下列说法正确的是", ["平方差公式适用于任何两数", "完全平方公式有三项", "以上都不对"]),
        ("若 $a+b=5$，则下列正确的是", ["$a=5-b$", "$b=5-a$", "$a=b$"]),
        ("$x^{100}$ 的系数", ["1", "100", "0"]),
        ("比较大小", ["$a>b$", "$a<b$", "$a=b$"]),
    ],
)
def test_unsupported_types_are_unverifiable(prompt, choices):
    r = vq.verify_item({"id": "q", "prompt": prompt, "choices": choices, "answer": 0})
    assert r["status"] == "unverifiable", r


def test_parser_never_calls_eval_or_sympify():
    tree = ast.parse((ROOT / "services/viz_quiz_verify.py").read_text(encoding="utf-8"))
    bare = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not bare & {"eval", "exec", "compile", "__import__"}
    assert not attrs & {"sympify", "parse_expr", "parse_latex"}
