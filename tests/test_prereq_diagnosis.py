"""先修回溯诊断内核（mneme_core prereq_graph / prereq_judge / prereq_diagnosis）。

用例移植自上游 cn-math-taxonomy ``tests/test_engine.js``（CC BY-NC 4.0）；
内核与上游 engine.js 的逐位一致性另经差分脚本核对（300 个随机会话 + 45,650 条判题）。
纯函数测试，不碰 DB。
"""

from __future__ import annotations

import json
import os

import pytest

from mneme_core.domain.oprim import prereq_graph as PG
from mneme_core.domain.oprim.prereq_judge import judge_answer, judge_question, normalize_text
from mneme_core.domain.oskill import prereq_diagnosis as E

DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "cn_math_taxonomy")


def mk(i: str, **extra):
    t = {"id": i, "name": i, "external": False, "diagnostic_question": {"question": i + "?", "answer": "1"}}
    t.update(extra)
    return t


#   X(外部) <- F <- E <- C <-hard- T ; F <- D <-hard- T ; F <- B <-soft- T ; Z 无关
SMALL_T = [mk("X", external=True, diagnostic_question=None)] + [mk(x) for x in "FECDBTZ"]
SMALL_D = [
    {"topicId": "F", "prerequisiteId": "X", "strength": "hard"},
    {"topicId": "E", "prerequisiteId": "F", "strength": "hard"},
    {"topicId": "C", "prerequisiteId": "E", "strength": "hard"},
    {"topicId": "D", "prerequisiteId": "F", "strength": "hard"},
    {"topicId": "B", "prerequisiteId": "F", "strength": "hard"},
    {"topicId": "T", "prerequisiteId": "B", "strength": "soft"},
    {"topicId": "T", "prerequisiteId": "D", "strength": "hard"},
    {"topicId": "T", "prerequisiteId": "C", "strength": "hard"},
]
G = PG.build_graph(SMALL_T, SMALL_D)


def run(g, s, script):
    asked = []
    for _ in range(100):
        q = E.next_question(g, s)
        if not q:
            break
        asked.append(q)
        s = E.apply_answer(g, s, q, script[q])
    return s, asked


def test_ancestors_and_topo():
    assert sorted(PG.ancestors(G, "T")) == list("BCDEFX")
    assert sorted(PG.ancestors(G, "X")) == []
    nodes = PG.subgraph(G, ["T"])["nodes"]
    assert nodes[0] == "X" and nodes[-1] == "T" and sorted(nodes) == list("BCDEFTX")


def test_hard_before_soft():
    assert [p["id"] + ":" + p["strength"] for p in G.prereqs["T"]] == ["C:hard", "D:hard", "B:soft"]


def test_first_correct_masters_all_ancestors():
    s = E.apply_answer(G, E.create_session(G, ["T"]), "T", "correct")
    assert E.next_question(G, s) is None
    for i in "BCDEFXT":
        assert E.status_of(s, i) == "mastered"
    assert s["status"]["T"]["src"] == "direct" and s["status"]["F"]["src"] == "inferred"
    assert E.status_of(s, "Z") == "unknown"
    sm = E.summarize(G, s)
    assert sm["weak"] == [] and sm["roots"] == [] and sm["path"] == [] and sm["asked"] == 1


def test_wrong_backtracks_depth_first_hard_before_soft():
    s, asked = run(G, E.create_session(G, ["T"]), {"T": "wrong", "C": "wrong", "E": "correct", "D": "correct", "B": "correct"})
    assert asked == ["T", "C", "E", "D", "B"]
    assert E.next_question(G, s) is None
    sm = E.summarize(G, s)
    assert [r["id"] for r in sm["roots"]] == ["C"]
    assert [p["id"] for p in sm["path"]] == ["C", "T"]


def test_skip_equals_wrong():
    a, _ = run(G, E.create_session(G, ["T"]), {"T": "skip", "C": "skip", "E": "correct", "D": "correct", "B": "correct"})
    b, _ = run(G, E.create_session(G, ["T"]), {"T": "wrong", "C": "wrong", "E": "correct", "D": "correct", "B": "correct"})
    assert a["status"] == b["status"]


# ---- 题库图：每个知识点 4 题：q1 标准、q2 标准、q3 基础、q4 提高
DIFFS = {"s": "standard", "b": "basic", "a": "advanced"}


def mq(t, n, d):
    return {"id": f"{t}_q{n}", "topicId": t, "difficulty": DIFFS[d], "type": "numeric", "prompt": "?", "answer": "1"}


BT = [mk(i, diagnostic_question=None) for i in ["R", "P1", "P2", "T"]]
BD = [
    {"topicId": "P1", "prerequisiteId": "R", "strength": "hard"},
    {"topicId": "T", "prerequisiteId": "P1", "strength": "hard"},
    {"topicId": "T", "prerequisiteId": "P2", "strength": "hard"},
]
BQ = [q for i in ["R", "P1", "P2", "T"] for q in (mq(i, 1, "s"), mq(i, 2, "s"), mq(i, 3, "b"), mq(i, 4, "a"))]
G2 = PG.build_graph(BT, BD, BQ)


def run2(s, script):
    seq = []
    for _ in range(100):
        it = E.next_item(G2, s)
        if not it:
            break
        seq.append(f"{it['topicId']}#{it['attempt']}")
        s = E.apply_answer(G2, s, it["topicId"], script[it["topicId"]][it["attempt"] - 1])
    return s, seq


def test_bank_flags():
    assert G2.has_bank and not G.has_bank and G.bank["T"][0]["type"] == "legacy"


def test_wrong_wrong_weak_and_backtrack():
    s, seq = run2(E.create_session(G2, ["T"]), {"T": ["wrong", "skip"], "P1": ["wrong", "wrong"], "R": ["correct"], "P2": ["correct"]})
    assert seq == ["T#1", "T#2", "P1#1", "P1#2", "R#1", "P2#1"]
    assert E.status_of(s, "T") == "weak" and E.status_of(s, "P1") == "weak" and E.status_of(s, "R") == "mastered"
    assert [r["id"] for r in E.summarize(G2, s)["roots"]] == ["P1"]


def test_wrong_then_correct_is_shaky_no_backtrack():
    s, seq = run2(E.create_session(G2, ["T"]), {"T": ["wrong", "correct"]})
    assert seq == ["T#1", "T#2"]
    assert E.status_of(s, "T") == "shaky" and E.next_question(G2, s) is None
    assert all(E.status_of(s, i) == "unknown" for i in ["P1", "P2", "R"])
    assert E.summarize(G2, s)["shaky"] == ["T"]


def test_second_question_prefers_basic_and_first_avoids_advanced():
    for i in range(40):
        s1 = E.apply_answer(G2, E.create_session(G2, ["P2"], seed=f"k{i}"), "P2", "wrong")
        first = PG.question_by_id(G2, s1["answers"][0]["qid"])
        assert first["difficulty"] != "advanced"
        second = E.next_item(G2, s1)["question"]
        if first["difficulty"] == "standard":
            assert second["id"] == "P2_q3"


def test_seeded_and_replayable_and_json_roundtrip():
    def trace(seed):
        s, _ = run2(E.create_session(G2, ["T"], seed=seed), {k: ["wrong", "wrong"] for k in ["T", "P1", "R", "P2"]})
        return ",".join(a["qid"] for a in s["answers"])

    assert trace("abc") == trace("abc") and trace(42) == trace("42")
    assert len({trace(f"s{i}") for i in range(40)}) > 5
    s2, _ = run2(E.create_session(G2, ["T"], seed=9), {"T": ["wrong", "correct"]})
    assert E.replay(G2, ["T"], s2["answers"], seed=9) == s2
    assert json.loads(json.dumps(s2)) == s2


def test_limit_counts_questions_and_unconfirmed():
    s, seq = run2(E.create_session(G2, ["T"], limit=3), {k: ["wrong", "wrong"] for k in ["T", "P1", "R", "P2"]})
    assert seq == ["T#1", "T#2", "P1#1"]
    sm = E.summarize(G2, s)
    assert E.status_of(s, "P1") == "weak" and sm["unconfirmed"] == ["P1"] and sm["limitReached"]
    assert sorted(sm["untested"]) == ["P2", "R"]


def test_apply_answer_does_not_mutate():
    s0 = E.create_session(G2, ["T"], seed=5)
    snap = json.dumps(s0, sort_keys=True)
    s1 = E.apply_answer(G2, s0, "T", "wrong", "42")
    assert json.dumps(s0, sort_keys=True) == snap and s1["answers"][0]["text"] == "42"


def test_submit_judges_and_manual_does_not_advance():
    s = E.create_session(G2, ["T"], seed=1)
    out = E.submit(G2, s, "1")
    assert out["applied"] and out["result"] == "correct"
    q = {"id": "M_q1", "topicId": "M", "type": "short", "answer": "y=2x+1"}
    gm = PG.build_graph([mk("M", diagnostic_question=None)], [], [q])
    sm = E.create_session(gm, ["M"])
    o2 = E.submit(gm, sm, "y=1+2x")
    assert not o2["applied"] and o2["needs_self_assessment"] and o2["session"] == sm
    assert E.submit(gm, sm, result="correct")["applied"]


def test_prng_matches_js():
    f = E.mulberry32(123)
    xs = [f() for _ in range(100)]
    assert all(0 <= x < 1 for x in xs)
    assert E.mulberry32(0)() == pytest.approx(0.26642920868471265, abs=0)


# ---------------------------------------------------------------- 判题

def j(q, u):
    return judge_question(q, u)["verdict"]


def test_judge_by_type():
    ch = {"type": "choice", "answer": "B", "choices": [{"key": "A", "text": "1/2"}, {"key": "B", "text": "-3"}, {"key": "C", "text": "相切"}]}
    for u, v in [("B", "correct"), (" b ", "correct"), ("(B)", "correct"), ("B.", "correct"), ("A", "wrong"),
                 ("-3", "correct"), ("－３", "correct"), ("1/2", "wrong"), ("E", "manual"), ("", "manual")]:
        assert j(ch, u) == v, u
    num = {"type": "numeric", "answer": "-1/2"}
    assert j(num, "-0.5") == "correct" and j(num, "1/2") == "wrong"
    ordq = {"type": "numeric", "answer": "3，-2"}
    assert j(ordq, "3, -2") == "correct" and j(ordq, "-2，3") == "wrong" and j(ordq, "3") == "wrong"
    unord = {"type": "numeric", "answer": "3，-2", "unordered": True}
    assert j(unord, "-2 和 3") == "correct" and j(unord, "-2，4") == "wrong"
    sh = {"type": "short", "answer": "y=2x+1", "accept": ["2x+1", "f(x)=2x+1"]}
    assert j(sh, "Y＝2X+1") == "correct" and j(sh, "f(x)=2x+1") == "correct" and j(sh, "y=1+2x") == "manual"
    assert j({"type": "self", "answer": "略"}, "略") == "manual"
    assert j({"type": "legacy", "answer": "3"}, "3.0") == "correct"


@pytest.mark.parametrize("u,r,v", [
    ("１/２", "0.5", "correct"), ("1/3", "0.333", "wrong"), ("1又1/2", "3/2", "correct"), ("1 1/2", "1.5", "correct"),
    ("50%", "1/2", "correct"), ("3/5", "5/3", "wrong"), ("90 度", "90°", "correct"), ("50°", "60°", "wrong"),
    ("-3 和 -1/2", "-1/2，-3", "correct"), ("-3", "-3 和 -1/2", "wrong"), ("x=3 或 x=2", "x=2 或 x=3", "correct"),
    ("3，2", "x=3，y=2", "correct"), ("x=2，y=3", "x=3，y=2", "wrong"), ("12米", "12 m", "correct"),
    ("12 cm", "12 m", "wrong"), ("25 平方米", "25 m²", "correct"), ("1,000", "1000", "correct"),
    ("（１，２）", "(1,2)", "correct"), ("(2,1)", "(1,2)", "wrong"), ("相离", "相切", "manual"),
    ("2x+3", "y=2x+3", "correct"), ("(x-2)^2-1", "y=(x-2)²-1", "correct"), ("", "3", "manual"),
])
def test_judge_answer_cases(u, r, v):
    assert judge_answer(u, r)["verdict"] == v


def test_normalize_and_no_crash():
    assert normalize_text("　１／２ ") == "1/2" and normalize_text("答：60°。") == "60°" and normalize_text("A、B；C") == "a,b;c"
    for u in ["", " ", "(", ")))", "1/0", "/", "--1", "1/2/3", "％", "😀", None, "１２３４５６７８９０/３"]:
        for r in ["3", "1/2", "相切", "x=2 或 x=3", "", "(1,2)"]:
            assert judge_answer(u, r)["verdict"] in ("correct", "wrong", "manual")


# ---------------------------------------------------------------- 真实数据

def _load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def RG():
    return PG.build_graph(_load("topics.json"), _load("dependencies.json"), _load("questions.json"))


def test_real_data_counts(RG):
    topics = _load("topics.json")
    assert len(topics) == 531 and len(_load("dependencies.json")) == 909
    assert sum(1 for t in topics if t["grade"] <= 6) == 216
    assert all(PG.is_testable(RG, t["id"]) for t in topics)


def test_cnm_221_backtracks_to_perfect_square_formula(RG):
    """演示目标 配方法：首问目标；两题都错 → 先问 hard 先修，答错到「完全平方公式」并成为根因。"""
    s = E.create_session(RG, ["cnm_221"], seed="demo")
    assert E.next_question(RG, s) == "cnm_221"
    # 先修 hard 两条：完全平方公式(cnm_148) 与 直接开平方法(cnm_220)，同为 hard 时按 topics 顺序
    assert [p["id"] for p in RG.prereqs["cnm_221"]] == ["cnm_148", "cnm_220"]
    s = E.apply_answer(RG, s, "cnm_221", "wrong")
    assert E.next_question(RG, s) == "cnm_221"  # 第二题
    s = E.apply_answer(RG, s, "cnm_221", "wrong")
    assert E.status_of(s, "cnm_221") == "weak"
    assert E.next_question(RG, s) == "cnm_148"
    assert RG.by_id["cnm_148"]["name"] == "完全平方公式"
    s = E.apply_answer(RG, s, "cnm_148", "wrong")
    s = E.apply_answer(RG, s, "cnm_148", "wrong")
    assert E.status_of(s, "cnm_148") == "weak"
    # 继续：完全平方公式的先修全部答对
    for _ in range(50):
        q = E.next_question(RG, s)
        if not q:
            break
        s = E.apply_answer(RG, s, q, "correct")
    sm = E.summarize(RG, s)
    assert [r["id"] for r in sm["roots"]] == ["cnm_148"]
    path = [p["id"] for p in sm["path"]]
    assert path[0] == "cnm_148" and path[-1] == "cnm_221"
    grades = [RG.by_id[i]["grade"] for i in path]
    assert grades == sorted(grades)


def test_real_correct_target_skips_all_ancestors(RG):
    s = E.apply_answer(RG, E.create_session(RG, ["cnm_221"]), "cnm_221", "correct")
    assert E.next_question(RG, s) is None
    anc = PG.ancestors(RG, "cnm_221")
    assert len(anc) > 30 and all(E.status_of(s, i) == "mastered" for i in anc)


def test_aliases_resolve_to_primary(RG):
    aliases = _load("id-aliases.json")["aliases"]
    assert len(aliases) == 18
    for key in aliases:
        ids = PG.resolve_targets([key], aliases)
        assert ids and all(RG.by_id[i]["grade"] <= 6 for i in ids)
    assert PG.resolve_targets(["nope"], aliases) == ["nope"]


def test_every_question_accepts_its_own_answer():
    bad = []
    for q in _load("questions.json"):
        if q["type"] == "self":
            continue
        ref = q["answer"] if q["type"] != "choice" else q["answer"]
        if judge_question(q, ref)["verdict"] != "correct":
            bad.append(q["id"])
    assert bad == []


def test_chapters_parse(RG):
    for t in RG.topics:
        assert PG.parse_chapter(t["chapter"])["volume"], t["chapter"]
