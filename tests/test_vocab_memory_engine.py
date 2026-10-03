"""词汇记忆引擎 P0 的门禁 / 阶梯 / Context Retriever 回归测试。

存在的理由同STATUS 里其它 vocab 测试：这个引擎的产物是**直接给学生背的内容**，
静默错误（把例句当记忆画面、回忆问里印着答案、把 disputed 词根当词源展示、
把无语境当通过）不会报错，只会一代一代教错。所以每条门禁都钉住，并且做了
变异验证（把判定改坏 → 对应测试必须失败）。

不依赖 test DB：`timed_sentences` 在 mneme_test 里**不存在**（既有漂移，见
STATUS 2026-10-02），故 Context Retriever 用假 db 打桩验证 SQL 之外的全部逻辑。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from services import vocab_context as vc
from services import vocab_memory as vm


# ---------------------------------------------------------------------------
# 打桩：Context Retriever 只依赖 db.execute(...) 的返回形状
# ---------------------------------------------------------------------------


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._rows[0] if self._rows else None


class FakeDB:
    """按 SQL 里出现的表名分派结果。记录调用以便断言排序/参数。"""

    def __init__(self, sentences=None, item=None, affix=None, collocations=None,
                 xiangxing=None, anchor=(False, False), family=None):
        self.sentences = sentences if sentences is not None else []
        self.item = item
        self.affix = affix
        self.collocations = collocations if collocations is not None else []
        self.xiangxing = xiangxing
        self.anchor = anchor
        self.family = family if family is not None else []
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        self.calls.append((sql, params))
        if "timed_sentences" in sql:
            return FakeResult(self.sentences)
        # 锚点 EXISTS 查询必须排在 vocabulary_affixes 之前，否则会走进 _affix 分支
        if "EXISTS(SELECT 1 FROM vocabulary_affixes" in sql:
            return FakeResult([SimpleNamespace(a=self.anchor[0], x=self.anchor[1])])
        if "vocabulary_affixes" in sql:
            return FakeResult([self.affix] if self.affix else [])
        if "vocabulary_collocations" in sql:
            return FakeResult(self.collocations)
        if "vocabulary_xiangxing" in sql:
            return FakeResult([self.xiangxing] if self.xiangxing else [])
        if "SELECT v.id, v.word, v.pos, v.meaning_cn" in sql:
            return FakeResult([self.item] if self.item else [])
        if "lower(v.word) = ANY" in sql:
            return FakeResult(self.family)
        raise AssertionError(f"未预期的 SQL: {sql[:120]}")


def _sent(n: int = 3):
    return [
        SimpleNamespace(
            id=f"s{i}",
            english_text=f"The team abandoned the project number {i}. " * 2,
            chinese_text=f"团队放弃了项目 {i}。",
            title=f"Lesson {i}",
        )
        for i in range(n)
    ]


def _memory_input(**over):
    base = {
        "vocabulary_id": "v1",
        "word": "abandon",
        "pos": "verb",
        "meaning_cn": "放弃；抛弃",
        "context": {
            "tier": vc.TIER_NCE,
            "tier_name": "NCE",
            "sentences": [
                {"text": "The team abandoned the project.", "source": "NCE",
                 "lesson": "Lesson 32", "sentence_id": "s0", "chinese_text": None}
            ],
            "textbook_tier_available": False,
            "unavailable_tiers": [],
            "degradation_reason": None,
        },
        "context_flat": "The team abandoned the project.",
        "affix": None,
        "tier": "B",
    }
    base.update(over)
    return base


def _good_node(**over):
    base = {
        "word": "abandon",
        "core_image": "船长松开缆绳弃船逃离",
        "semantic_core": {"image": "船长松手", "meaning": "放手不再负责",
                          "logic": "放手→失去控制→放弃"},
        "scene": "暴风雨中船长松开缆绳，独自跳上救生艇",
        "family": [{"word": "abandoned", "meaning_cn": "被遗弃的"}],
        "sound_hook": "啊·班等——放弃",
        "spelling_hook": "a-ban-don，ban 是班级，don 是.done",
        "recall_question": "船长松开缆绳弃船是什么动作？",
        "answer": "abandon",
        "image_prompt": "A captain letting go of the ship ropes in a storm, cartoon educational style",
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# oprim 契约
# ---------------------------------------------------------------------------


def _load_oprim():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "vendor" / "oprim" / "_vocab_memory_generate.py"
    spec = importlib.util.spec_from_file_location("_vocab_memory_generate", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_oprim_contract_has_no_etymology_field():
    """词源**不能**出现在生成契约里 —— 这是防幻觉的结构性手段，不是事后门禁。

    变异验证：把 etymology 加回 _REQUIRED_KEYS → 本测试失败。
    """
    mod = _load_oprim()
    assert not any("etym" in k for k in mod._REQUIRED_KEYS)
    assert "etymology" not in json.dumps(mod._SYSTEM, ensure_ascii=False)


def test_oprim_validates_nested_semantic_core():
    mod = _load_oprim()
    assert mod._valid(_good_node()) is True
    broken = _good_node()
    broken["semantic_core"] = {"image": "x", "meaning": "", "logic": "y"}
    assert mod._valid(broken) is False
    broken2 = _good_node()
    broken2["family"] = [{"meaning_cn": "没有 word 字段"}]
    assert mod._valid(broken2) is False


def test_oprim_degrades_whole_word_on_any_missing_field():
    """任一必填字段缺失 → **整个词**为 None，不返回半成品。

    半成品会被下游质量门当成可用记忆，比没有更坏。
    """
    mod = _load_oprim()
    for key in ("core_image", "recall_question", "answer", "image_prompt"):
        broken = _good_node()
        del broken[key]
        assert mod._valid(broken) is False, key


# ---------------------------------------------------------------------------
# 9 条质量门禁
# ---------------------------------------------------------------------------


def _report(node, memory_input=None, family_resolved=None):
    return vm.verify_memory_node(
        node,
        memory_input=memory_input or _memory_input(),
        family_resolved=[{"word": "abandoned", "vocabulary_item_id": "v2"}]
        if family_resolved is None
        else family_resolved,
    )


def test_all_nine_gates_pass_on_a_clean_node():
    rep = _report(_good_node())
    assert rep.failed_gates == []
    assert rep.score == 1.0
    assert rep.to_payload()["verified"] is True


def test_gate_core_image_length_bounds():
    """太短撑不起记忆，太长是整段叙文 —— 两端都拒。"""
    assert "HAS_ONE_CORE_IMAGE" in _report(_good_node(core_image="")).failed_gates
    assert "HAS_ONE_CORE_IMAGE" in _report(_good_node(core_image="短")).failed_gates
    too_long = _report(_good_node(core_image="很长" * 40)).failed_gates
    assert "HAS_ONE_CORE_IMAGE" in too_long


def test_seven_character_core_images_are_accepted():
    """回归：下限曾是 8，把模型「凝练七字」的风格全误杀了。

    100 词真实试跑里 4/4 个 HAS_ONE_CORE_IMAGE 拒收都是 7 字好画面
    （`real`→「火烧假花露真蕊」、`each`→「老师逐个发糖果」、
    `stand`→「脚生根顶住狂风」、`wet`→「拧湿毛巾水滴答」）—— 10 次拒收里 4 次是误杀。
    """
    for seven in ["火烧假花露真蕊", "老师逐个发糖果", "脚生根顶住狂风", "拧湿毛巾水滴答"]:
        assert len(seven) == 7
        assert "HAS_ONE_CORE_IMAGE" not in _report(_good_node(core_image=seven)).failed_gates


def test_gate_recall_hook_requires_a_question():
    assert "HAS_RECALL_HOOK" in _report(
        _good_node(recall_question="船长松开缆绳弃船是什么动作")
    ).failed_gates


def test_gate_answer_must_match_word():
    """答案不是这个词 = 卡片答非所问。"""
    assert "ANSWER_MATCHES_WORD" in _report(_good_node(answer="leave")).failed_gates
    # 大小写/标点差异不算错（学生端输入不规范是常态）
    assert _report(_good_node(answer="Abandon.")).failed_gates == []


def test_gate_no_answer_leak():
    """回忆问里印着答案 = 主动回忆直接作废。原 spec 未列这条。"""
    rep = _report(_good_node(recall_question="abandon 是什么意思？"))
    assert "NO_ANSWER_LEAK" in rep.failed_gates
    # 多词短语按整串比，不因命中其中一段就误判
    mi = _memory_input(word="a bit of")
    node = _good_node(answer="a bit of", recall_question="这是哪一课学的？")
    rep2 = vm.verify_memory_node(node, memory_input=mi, family_resolved=[])
    assert "NO_ANSWER_LEAK" not in rep2.failed_gates


def test_gate_no_echo_of_evidence():
    """核心画面复制真实句 = 「记忆」退化成抄课文。"""
    rep = _report(_good_node(core_image="The team abandoned the project."))
    assert "NO_ECHO_OF_EVIDENCE" in rep.failed_gates


def test_gate_has_context_marks_degraded_not_pass():
    """无语境必须记 DEGRADED 且 verified=False —— 绝不记 PASS。

    假绿会让「教材优先」这条产品承诺静默消失。
    """
    mi = _memory_input(
        context={
            "tier": vc.TIER_NONE,
            "tier_name": "NONE",
            "sentences": [],
            "textbook_tier_available": False,
            "unavailable_tiers": [],
            "degradation_reason": "无语料源",
        },
        context_flat=None,
        tier="C",
    )
    rep = _report(_good_node(), memory_input=mi)
    payload = rep.to_payload()
    assert "HAS_CONTEXT" in payload["failed_gates"]
    assert payload["degraded"] is True
    assert payload["verified"] is False
    assert payload["gates"][0]["passed"] is True  # 其余门禁仍正常判定


def test_gate_family_unresolved_is_not_trusted():
    """family 未解析 = 未验证 = 不可信，不能因为「有 family」就放行。"""
    rep = vm.verify_memory_node(
        _good_node(), memory_input=_memory_input(), family_resolved=None
    )
    assert "FAMILY_TRACEABLE" in rep.failed_gates


def test_gate_family_all_hallucinated_is_rejected():
    rep = _report(_good_node(), family_resolved=[])
    assert "FAMILY_TRACEABLE" in rep.failed_gates


def test_gate_disputed_source_blocks_display():
    """disputed（与参考表冲突）不得进记忆卡展示面。"""
    mi = _memory_input(
        affix={"prefix": None, "root": "cooperire", "suffix": None,
               "etymology_status": "disputed", "should_display": False}
    )
    assert "NOT_DISPUTED_SOURCE" in _report(_good_node(), mi).failed_gates
    # mnemonic_association 允许进（只是不能当词源讲）
    mi2 = _memory_input(
        affix={"prefix": None, "root": "less", "suffix": None,
               "etymology_status": "mnemonic_association", "should_display": True}
    )
    assert "NOT_DISPUTED_SOURCE" not in _report(_good_node(), mi2).failed_gates


def test_gate_no_false_root_detects_contradiction_only():
    """只在拼写钩子**明确在讲拆解**时核对，且只判「否定存储里有的段位」。"""
    affix = {"prefix": "pre", "root": "dict", "suffix": None,
             "etymology_status": "reference_confirmed"}
    mi = _memory_input(affix=affix)
    conflict = _good_node(spelling_hook="这个词没有前缀，直接读就好")
    assert "NO_FALSE_ROOT" in _report(conflict, mi).failed_gates
    ok = _good_node(spelling_hook="pre·dict：预测，先记住念法")
    assert "NO_FALSE_ROOT" not in _report(ok, mi).failed_gates
    # 普通记忆句不该被当词根叙述审
    plain = _good_node(spelling_hook="想象一只拒绝帮助的猫，很好记")
    assert "NO_FALSE_ROOT" not in _report(plain, mi).failed_gates


def test_every_gate_name_is_covered_by_the_report():
    assert len(vm.ALL_GATES) == 9
    assert len({g.name for g in _report(_good_node()).gates}) == 9


# ---------------------------------------------------------------------------
# 装配
# ---------------------------------------------------------------------------


def test_build_row_persists_evidence_as_ids_not_copied_text():
    """context_evidence 存 sentence_id；句子文本留在 timed_sentences。

    复制文本会读到旧句 —— 课文改了记忆卡还引着旧句。
    """
    rep = _report(_good_node())
    row = vm.build_memory_node(
        _good_node(), memory_input=_memory_input(), report=rep,
        family_resolved=[{"word": "abandoned", "vocabulary_item_id": "v2"}],
        generation_model="test-model",
    )
    assert [e["sentence_id"] for e in row["context_evidence"]] == ["s0"]
    assert row["generation_model"] == "test-model"
    assert row["verified"] is True


def test_build_row_requires_absence_reason_when_no_context():
    """tier=5 时 context_absence_reason 必填（DB CHECK 也强制）。"""
    mi = _memory_input(
        context={"tier": vc.TIER_NONE, "sentences": [],
                 "degradation_reason": "无语料源", "unavailable_tiers": []},
        context_flat=None, tier="C",
    )
    rep = _report(_good_node(), mi)
    row = vm.build_memory_node(
        _good_node(), memory_input=mi, report=rep, family_resolved=[],
        generation_model="m",
    )
    assert row["context_tier"] == 5
    assert row["context_absence_reason"] == "无语料源"
    assert row["verified"] is False


def test_animation_candidate_only_for_tier_a():
    """B 级连词根/象形锚点都没有，动画只会把凭空的画面做得更可信。"""
    def _row(tier):
        mi = _memory_input(tier=tier)
        rep = _report(_good_node(), mi)
        return vm.build_memory_node(
            _good_node(), memory_input=mi, report=rep, family_resolved=[],
            generation_model="m",
        )

    assert _row("A")["animation_candidate"] is True
    assert _row("B")["animation_candidate"] is False
    assert _row("C")["animation_candidate"] is False


def test_build_row_does_not_silently_repair_failed_node():
    """门禁不过也落库，但 verified=False 且保留现场 —— 不悄悄修成合格的。"""
    rep = _report(_good_node(recall_question="这不是问句"))
    row = vm.build_memory_node(
        _good_node(recall_question="这不是问句"), memory_input=_memory_input(),
        report=rep, family_resolved=[], generation_model="m",
    )
    assert row["verified"] is False
    assert row["recall_question"] == "这不是问句"
    assert 0 < row["quality_score"] < 1


# ---------------------------------------------------------------------------
# FSRS 复习阶梯
# ---------------------------------------------------------------------------


def _node_row():
    return {
        "vocabulary_item_id": "v1",
        "core_image": "船长松开缆绳弃船逃离",
        "semantic_core": {"image": "x", "meaning": "y", "logic": "z"},
        "scene": "暴风雨",
        "recall_question": "船长松开缆绳弃船是什么动作？",
        "context_evidence": [{"sentence_id": "s0", "text": "The team abandoned the project."}],
    }


def test_first_exposure_shows_everything():
    """人决策：第一次最重要，目标是完全理解，所以首次**不做下拉折叠**。"""
    out = vm.render_review_ladder(_node_row(), stage=vm.STAGE_LEARNING)
    assert out["hidden_count"] == 0
    assert out["all_shown"] is True
    assert [ly["key"] for ly in out["layers"]] == list(vm.LAYER_ORDER)


def test_late_review_hides_context_sentence_until_answer():
    out = vm.render_review_ladder(_node_row(), stage=vm.STAGE_REVIEW_LATE)
    assert "context_sentence" in out["hidden_layers"]
    # 回忆问必须始终可见 —— 否则没法作答
    assert any("recall_question" in str(ly["content"]) for ly in out["layers"])


def test_expanded_reveals_more_without_changing_schedule():
    """「再看一层」只影响露出多少，不改 FSRS 状态。"""
    base = vm.render_review_ladder(_node_row(), stage=vm.STAGE_REVIEW_LATE)
    more = vm.render_review_ladder(_node_row(), stage=vm.STAGE_REVIEW_LATE, expanded=2)
    assert more["hidden_count"] < base["hidden_count"]
    assert more["stage"] == base["stage"]


def test_disputed_word_origin_never_renders():
    facts = {"word_origin": {"chain": "dis·cover", "should_display": False}}
    out = vm.render_review_ladder(_node_row(), stage=vm.STAGE_LEARNING, facts=facts)
    origin_layer = next(ly for ly in out["layers"] if ly["key"] == "word_origin")
    assert origin_layer["content"]["word_origin"] is None


# 下面的卡片形状**取自生产 kc_mastery.fsrs_card_json 真实行**（2026-10-03 查询），
# 不是编的：py-fsrs 的 Card 只有 card_id/state/step/stability/difficulty/due/last_review，
# **没有 reps**，且 state 是 int（State.Learning=1 / Review=2 / Relearning=3）。
# 第一版 resolve_stage 按字符串 state + card["reps"] 写，只对自己编的 fixture 成立，
# 接到真卡上直接 AttributeError —— 这个测试就是为钉住它而改的。
_REAL_CARD_LEARNING = {
    "due": "2026-07-18T18:02:07.195494+00:00",
    "step": 0,
    "state": 1,
    "card_id": 1784397667197,
    "stability": 0.212,
    "difficulty": 6.4133,
    "last_review": "2026-07-18T18:01:07.195494+00:00",
}


def _card_review(interval_days: float) -> dict:
    import datetime as dt

    last = dt.datetime(2026, 7, 18, 18, 1, 7, tzinfo=dt.timezone.utc)
    due = last + dt.timedelta(days=interval_days)
    return {**_REAL_CARD_LEARNING, "state": 2, "due": due.isoformat()}


@pytest.mark.parametrize(
    "card,expected",
    [
        (None, vm.STAGE_LEARNING),
        ({}, vm.STAGE_LEARNING),
        (_REAL_CARD_LEARNING, vm.STAGE_LEARNING),
        ({**_REAL_CARD_LEARNING, "state": 3}, vm.STAGE_LEARNING),  # Relearning
        (_card_review(0.4), vm.STAGE_REVIEW_EARLY),
        (_card_review(10.0), vm.STAGE_REVIEW_MID),
        (_card_review(120.0), vm.STAGE_REVIEW_LATE),
    ],
)
def test_stage_resolution_from_real_fsrs_card(card, expected):
    assert vm.resolve_stage(card) == expected


def test_resolve_stage_accepts_json_string_and_string_states():
    """列是 JSONB，但历史/导入数据可能是字符串；state 也可能是字符串。"""
    import json

    assert vm.resolve_stage(json.dumps(_REAL_CARD_LEARNING)) == vm.STAGE_LEARNING
    # 注意展开顺序：** 必须在前面，否则会把后面的 state 覆盖掉（第一版就踩了这个）
    assert vm.resolve_stage({**_REAL_CARD_LEARNING, "state": "2"}) == vm.STAGE_REVIEW_EARLY
    assert vm.resolve_stage({"state": "learning"}) == vm.STAGE_LEARNING
    assert vm.resolve_stage("not json") == vm.STAGE_LEARNING


def test_resolve_stage_never_raises_on_odd_state():
    """状态端点/渲染路径不能因为一张奇怪的卡就 500。"""
    for weird in [{"state": None}, {"state": True}, {"state": []}, {"state": 2.5},
                  {"state": 2, "due": "x", "last_review": "y"}, {"state": 99}]:
        assert vm.resolve_stage(weird) in (
            vm.STAGE_LEARNING,
            vm.STAGE_REVIEW_EARLY,
            vm.STAGE_REVIEW_MID,
            vm.STAGE_REVIEW_LATE,
        ), weird


def test_kc_naming_matches_vocab_service_convention():
    from services.vocab_service import _kp

    assert vm.vocab_kc("v1") == _kp("v1") == "vocab-v1"


# ---------------------------------------------------------------------------
# Context Retriever
# ---------------------------------------------------------------------------


def test_retriever_falls_back_to_nce_tier():
    db = FakeDB(sentences=_sent(3))
    bundle = asyncio.run(vc.retrieve_context(db, "v1"))
    assert bundle.tier == vc.TIER_NCE
    assert bundle.has_context is True
    assert bundle.best.source == "NCE"
    assert bundle.best.lesson == "Lesson 0"


def test_retriever_reports_textbook_tier_as_unavailable():
    """tier 1/2 今天没有源，必须**显式**说明，否则「教材优先」静默消失。"""
    db = FakeDB(sentences=_sent(1))
    bundle = asyncio.run(vc.retrieve_context(db, "v1"))
    payload = bundle.to_payload()
    assert payload["textbook_tier_available"] is False
    tiers = {u["tier"] for u in payload["unavailable_tiers"]}
    assert vc.TIER_CURRENT_LESSON in tiers
    assert vc.TIER_CURRENT_BOOK in tiers
    assert all(u["reason"] for u in payload["unavailable_tiers"])


def test_retriever_no_context_is_explicit_degradation():
    db = FakeDB(sentences=[])
    bundle = asyncio.run(vc.retrieve_context(db, "v1"))
    payload = bundle.to_payload()
    assert bundle.tier == vc.TIER_NONE
    assert bundle.has_context is False
    assert payload["degradation_reason"]


def test_retriever_prefers_sentences_in_readable_length_band():
    """句长偏好必须落在 SQL 的 ORDER BY 里（不在 Python 里二次排序）。"""
    db = FakeDB(sentences=_sent(1))
    asyncio.run(vc.retrieve_context(db, "v1", limit=2))
    sql, params = db.calls[0]
    assert "CASE WHEN length" in sql
    assert params["limit"] == 2
    assert params["lo"] == vc._SENTENCE_MIN_LEN
    assert params["hi"] == vc._SENTENCE_MAX_LEN


def test_retriever_rejects_zero_limit():
    with pytest.raises(ValueError):
        asyncio.run(vc.retrieve_context(FakeDB(), "v1", limit=0))


@pytest.mark.parametrize(
    "anchor,has_ctx,expected",
    [
        ((True, False), True, "A"),
        ((False, True), True, "A"),
        ((False, False), True, "B"),
        ((True, True), False, "C"),
    ],
)
def test_tier_assignment_is_deterministic_from_existing_tables(anchor, has_ctx, expected):
    db = FakeDB(sentences=_sent(1) if has_ctx else [], anchor=anchor)
    tier = asyncio.run(vc.assign_tier(db, "v1", has_context=has_ctx))
    assert tier == expected


def test_resolve_family_keeps_only_real_words():
    db = FakeDB(
        family=[SimpleNamespace(id="v2", word="abandoned", meaning_cn="被遗弃的")]
    )
    out = asyncio.run(vc.resolve_family(db, ["abandoned", "nonexistentword"]))
    assert [f["word"] for f in out] == ["abandoned"]
    assert out[0]["vocabulary_item_id"] == "v2"


def test_resolve_family_empty_input_does_not_query():
    db = FakeDB()
    assert asyncio.run(vc.resolve_family(db, [])) == []
    assert db.calls == []


def test_load_memory_input_falls_back_to_example_sentence():
    """occurrence 关联丢失时，example_sentence 是唯一退路（同一批确定性抽取）。"""
    item = SimpleNamespace(
        id="v1", word="abandon", pos="verb", meaning_cn="放弃",
        phonetic_arpabet="AH0 B AE1 N D AH0 N",
        example_sentence="He abandoned his plan.",
        canonical_meaning=None,
    )
    db = FakeDB(sentences=[], item=item)
    out = asyncio.run(vc.load_memory_input(db, "v1"))
    assert out["context"]["tier"] == vc.TIER_NCE
    assert out["context_flat"] == "He abandoned his plan."


def test_load_memory_input_never_hands_a_phonetic_to_the_llm():
    """CME-P1.5：Context Retriever 绝不能把读音当释义喂给 LLM。

    生产里 canonical_meaning 混着 9,844 条真音标；若直接透传，模型会拿
    `[ˈeərən]` 去编中文释义，然后那个释义就被当成教材权威展示给学生。
    """
    item = SimpleNamespace(
        id="v1", word="Aaron", pos=None, meaning_cn=None,
        phonetic_arpabet="EH1 R AH0 N", example_sentence=None,
        canonical_meaning="[ˈeərən]",
    )
    db = FakeDB(sentences=[], item=item)
    out = asyncio.run(vc.load_memory_input(db, "v1"))
    assert out["meaning_cn"] is None, "音标被当成释义传下去了"
    assert out["llm_entry"]["meaning_cn"] is None
    assert out["meaning"]["kind"] == "phonetic"
    assert out["meaning"]["tier"] == "unusable"
    # 读音仍有正确去处（ARPAbet 独立列），不是把音标丢掉就完了
    assert out["phonetic_arpabet"] == "EH1 R AH0 N"


def test_load_memory_input_prefers_meaning_cn_over_polluted_canonical():
    """meaning_cn 可信时优先用它，即使 canonical_meaning 是音标。"""
    item = SimpleNamespace(
        id="v1", word="abandon", pos="verb", meaning_cn="放弃；抛弃",
        phonetic_arpabet=None, example_sentence=None,
        canonical_meaning="[əˈbændən]",
    )
    db = FakeDB(sentences=[], item=item)
    out = asyncio.run(vc.load_memory_input(db, "v1"))
    assert out["meaning_cn"] == "放弃；抛弃"
    assert out["meaning"]["tier"] == "canonical"
    assert out["meaning"]["source_column"] == "meaning_cn"


def test_load_memory_input_marks_labelled_gloss_as_legacy_not_unusable():
    """`[法] 法案` 是带义项标签的释义 —— 可用，但标为 legacy 让人知道未派生。"""
    item = SimpleNamespace(
        id="v1", word="bill", pos=None, meaning_cn=None,
        phonetic_arpabet=None, example_sentence=None,
        canonical_meaning="[法] 法案；广告；账单",
    )
    db = FakeDB(sentences=[], item=item)
    out = asyncio.run(vc.load_memory_input(db, "v1"))
    assert out["meaning_cn"] == "[法] 法案；广告；账单"
    assert out["meaning"]["tier"] == "legacy"


def test_load_memory_input_raises_on_unknown_id():
    db = FakeDB(sentences=[], item=None)
    with pytest.raises(KeyError):
        asyncio.run(vc.load_memory_input(db, "nope"))