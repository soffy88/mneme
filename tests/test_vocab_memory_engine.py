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

import oprim._vocab_memory_generate as mg
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
                 xiangxing=None, anchor=(False, False), family=None, derived_gloss=None,
                 fam_candidates=None, fam_root_candidates=None, confusables=None,
                 dict_gloss=None):
        self.sentences = sentences if sentences is not None else []
        self.item = item
        self.affix = affix
        self.collocations = collocations if collocations is not None else []
        self.xiangxing = xiangxing
        self.anchor = anchor
        self.family = family if family is not None else []
        self.derived_gloss = derived_gloss
        self.fam_candidates = fam_candidates if fam_candidates is not None else []
        self.fam_root_candidates = (
            fam_root_candidates if fam_root_candidates is not None else []
        )
        self.confusables = confusables if confusables is not None else []
        self.dict_gloss = dict_gloss
        self.calls: list[tuple[str, dict]] = []

    @staticmethod
    def _cand(word: str, meaning_cn: str | None = None):
        return SimpleNamespace(id=f"id-{word}", word=word, meaning_cn=meaning_cn)

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        self.calls.append((sql, params))
        if "timed_sentences" in sql:
            return FakeResult(self.sentences)
        # 锚点 EXISTS 查询必须排在 vocabulary_affixes 之前，否则会走进 _affix 分支
        if "EXISTS(SELECT 1 FROM vocabulary_affixes" in sql:
            return FakeResult([SimpleNamespace(a=self.anchor[0], x=self.anchor[1])])
        # family_candidates 的**词根**查询也含 vocabulary_affixes，必须排在通用
        # `vocabulary_affixes` 分支前面，否则会返回 affix 命名空间（没有 .word）。
        if "FROM vocabulary_affixes a" in sql:
            return FakeResult(self.fam_root_candidates)
        if "LIKE :prefix" in sql:
            return FakeResult(self.fam_candidates)
        if "vocabulary_affixes" in sql:
            return FakeResult([self.affix] if self.affix else [])
        if "vocabulary_derived_glosses" in sql:
            return FakeResult([self.derived_gloss] if self.derived_gloss else [])
        # 词典来源释义（2026-10-05）。必须排在 derived 之前 —— 两张表名不同，
        # 但都出现在「非教材释义」的语义位上，顺序错了会让测试测错档位。
        if "vocabulary_dictionary_glosses" in sql:
            return FakeResult([self.dict_gloss] if self.dict_gloss else [])
        if "vocabulary_collocations" in sql:
            return FakeResult(self.collocations)
        if "vocabulary_xiangxing" in sql:
            return FakeResult([self.xiangxing] if self.xiangxing else [])
        if "SELECT v.id, v.word, v.pos, v.meaning_cn" in sql:
            return FakeResult([self.item] if self.item else [])
        # confusable_candidates 的查询没有编号/ANY 特征，用 length(...) BETWEEN 认
        if "length(v.word) BETWEEN" in sql:
            return FakeResult(self.confusables)
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
        "meaning": {
            "tier": "canonical",
            "kind": "gloss",
            "gloss": "放弃；抛弃",
            "source_column": "meaning_cn",
            "gloss_source": "meaning_cn",
            "primary_sense": {"order": 0, "pos": "verb", "raw_pos": "vt.", "text": "放弃；抛弃"},
            "primary_sense_reason": "fixture",
        },
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
        "confusables": [],
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


def test_oprim_reports_truncation_distinctly_from_bad_json(monkeypatch):
    """推理模型被 max_tokens 截断时，失败原因必须写成 truncated_by_max_tokens。

    不区分的后果很具体：Agents-A1 在 8192 下返回 HTTP 200 + 半截 JSON，
    表现得像「模型格式不对」，于是会有人去调 prompt，而真因是预算不足。
    """
    mod = _load_oprim()

    class _Resp:
        def __init__(self, text, stop_reason):
            self.text = text
            self.stop_reason = stop_reason

    def _run(monkeypatch, raw, stop_reason):
        async def _fake_complete(*_a, **kw):
            return _Resp(raw, stop_reason)

        monkeypatch.setattr("oprim.llm.llm_complete", _fake_complete)
        return asyncio.run(
            mod.generate_memory_nodes([{"word": "abandon"}], caller=object())
        )

    entries = [{"word": "abandon"}]
    # 截断
    monkeypatch.setattr("oprim.llm.llm_complete",
                        lambda *a, **kw: _async(_Resp('[{"word": "abandon", "core_image": "x', "length")))
    out = _run(monkeypatch, '[{"word": "abandon", "core_image": "x', "length")
    assert out[0]["__failed__"] is True
    assert out[0]["reason"] == "truncated_by_max_tokens"
    assert out[0]["stop_reason"] == "length"
    # 合法 JSON 但字段缺失
    out2 = _run(monkeypatch, '[{"word": "abandon"}]', "stop")
    assert out2[0]["__failed__"] is True
    assert out2[0]["reason"] == "missing_or_invalid_fields"
    # 坏 JSON
    out3 = _run(monkeypatch, "not json at all", "stop")
    assert out3[0]["reason"].startswith("json_parse_error")
    assert entries  # 保底


def _async(resp):
    async def _f(*_a, **_kw):
        return resp

    return _f


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


def _report(node, memory_input=None, family_resolved=None, confusable_candidates=None):
    return vm.verify_memory_node(
        node,
        memory_input=memory_input or _memory_input(),
        family_resolved=[{"word": "abandoned", "vocabulary_item_id": "v2"}]
        if family_resolved is None
        else family_resolved,
        confusable_candidates=confusable_candidates or [],
    )


def test_all_gates_pass_on_a_clean_node():
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
    """改判据后：**含疑问词但漏问号**的问句必须放过（那是 `spread` 的误杀）。

    原断言写的正是「漏问号即拒」，即旧契约本身。收紧到真陈述句才拒 ——
    见 `test_declarative_recall_text_is_still_rejected`。
    """
    assert "HAS_RECALL_HOOK" not in _report(
        _good_node(recall_question="船长松开缆绳弃船是什么动作")
    ).failed_gates
    assert "HAS_RECALL_HOOK" in _report(
        _good_node(recall_question="船长松开缆绳弃船逃离")
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
    assert len(vm.ALL_GATES) == 11
    assert len({g.name for g in _report(_good_node()).gates}) == len(vm.ALL_GATES)


def test_gate_meaning_authority_rejects_unusable_gloss():
    """无权威释义（纯音标/占位/空）→ 拒收。

    起因：20 词人工审查里 `title` 的 canonical 是纯音标 → unusable，
    节点却 verified=true。「语义核心由模型发明、无教材出处」与教材原文优先冲突。
    """
    mi = _memory_input(
        meaning={"tier": "unusable", "kind": "phonetic", "gloss": None,
                 "source_column": None, "gloss_source": None, "primary_sense": None}
    )
    assert "MEANING_AUTHORITY" in _report(_good_node(), mi).failed_gates


def test_gate_meaning_authority_rejects_absent_gloss_even_if_tier_looks_fine():
    """空 gloss 必须拒收 —— 哪怕 tier 字段写着 canonical。

    这条是**结构防御**：正常路径下 gloss 为空必然伴随 tier=unusable
    （classify_meaning_source 保证），但门禁不能依赖调用方守约。写之前
    做过变异验证：只把 `if not gloss` 那一支短路掉时，本测试是唯一能抓住的 ——
    另外两个分支（unusable / 无来源列）会各自把当时的用例挡住，掩盖这个漏洞。
    """
    mi = _memory_input(
        meaning={"tier": "canonical", "kind": "gloss", "gloss": None,
                 "source_column": "meaning_cn", "gloss_source": "meaning_cn",
                 "primary_sense": None}
    )
    assert "MEANING_AUTHORITY" in _report(_good_node(), mi).failed_gates


def test_gate_meaning_authority_rejects_untraceable_gloss():
    mi = _memory_input(
        meaning={"tier": "canonical", "kind": "gloss", "gloss": "放弃",
                 "source_column": None, "gloss_source": None, "primary_sense": None}
    )
    assert "MEANING_AUTHORITY" in _report(_good_node(), mi).failed_gates


def test_gate_meaning_authority_accepts_pos_selected_sense():
    mi = _memory_input(
        meaning={"tier": "legacy", "kind": "gloss", "gloss": "盲目的；瞎的",
                 "source_column": "canonical_meaning",
                 "gloss_source": "canonical_meaning(pos-selected sense)",
                 "primary_sense": {"order": 1, "pos": "adj", "raw_pos": "adj.",
                                   "text": "盲目的；瞎的"}}
    )
    assert "MEANING_AUTHORITY" not in _report(_good_node(), mi).failed_gates


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
        "confusables": [],
        "context_evidence": [{"sentence_id": "s0", "text": "The team abandoned the project."}],
    }


def test_first_exposure_shows_everything():
    """人决策：第一次最重要，目标是完全理解，所以首次**不做下拉折叠**。

    断言写成「相对 LAYER_ORDER 的有序子集」而不是 `== list(vm.LAYER_ORDER)`：
    层数会随 spec §二 的连接补齐而变（已从 4 增到 7），而全空的层会被跳过
    （见 test_empty_layer_is_skipped_and_costs_no_reveal），所以要求逐项相等
    会在两种正常情况下误报。真正要守的是：**没��任何东西被藏起来，且顺序不乱**。
    """
    out = vm.render_review_ladder(_node_row(), stage=vm.STAGE_LEARNING)
    assert out["hidden_count"] == 0
    assert out["all_shown"] is True
    keys = [ly["key"] for ly in out["layers"]]
    assert keys == [k for k in vm.LAYER_ORDER if k in keys]
    assert [ly["layer"] for ly in out["layers"]] == list(range(1, len(keys) + 1))


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
    """disputed 档的词源**不出现在渲染结果的任何位置**。

    原来这条断言写成「找到 word_origin 层，再看它是 None」。加了「空层跳过」之后
    那种写法会因 StopIteration 失败 —— 但那不是泄漏，是整层没了。真正要守的性质
    是「disputed 内容不渲染」，所以这里直接查全量结果，与该层是否存在无关。
    这样以后再调层序也不会把保护弄丢。
    """
    facts = {"word_origin": {"chain": "dis·cover", "should_display": False}}
    out = vm.render_review_ladder(_node_row(), stage=vm.STAGE_LEARNING, facts=facts)
    assert "dis·cover" not in str(out["layers"])
    for ly in out["layers"]:
        if ly["key"] == "word_origin":
            assert ly["content"]["word_origin"] is None


def test_collocations_keep_the_origin_layer_alive_when_origin_is_disputed():
    """disputed 只该压住**词源**，不该连带压掉同一层的搭配。"""
    facts = {
        "word_origin": {"chain": "dis·cover", "should_display": False},
        "collocations": [{"phrase_en": "discover a method", "phrase_cn": "发现一种方法"}],
    }
    out = vm.render_review_ladder(_node_row(), stage=vm.STAGE_LEARNING, facts=facts)
    layer = next(ly for ly in out["layers"] if ly["key"] == "word_origin")
    assert layer["content"]["word_origin"] is None
    assert layer["content"]["collocations"][0]["phrase_en"] == "discover a method"


# --------------------------------------------------------------------------
# spec §二 的 7 个连接（2026-10-05 审计后补齐）
#
# 审计发现：sound_hook / spelling_hook / family_network **生成了、存了、API 也返回**，
# 但**不在 LAYER_ORDER 里** —— 学生永远看不到。而 spec 明说最终要形成
# 「单词→声音→画面→故事→词根→词族→含义」这条链，声音与词族两环实际断着。
# --------------------------------------------------------------------------

_HOOKED = {
    "sound_hook": "Wet 谐音\"伟特\"，伟人遇雨被淋湿",
    "spelling_hook": "w 像微波，e 像圆眼",
    "family_network": [{"word": "valleys", "meaning_cn": "山谷"}],
    "confusable_words": [{"word": "web", "meaning_cn": "网"}],
}


def test_all_seven_connections_reach_the_student():
    """spec §二 的连接齐全时，每一层都到达展示面（词源这层要有 facts 才不空）。

    层数已从 4 增到 8：core_image / semantic_core / sound_hook / spelling_hook /
    family_network / confusables / word_origin / context_sentence。
    """
    node = {**_node_row(), **_HOOKED}
    facts = {"word_origin": {"chain": "vale·ley", "should_display": True}}
    out = vm.render_review_ladder(node, stage=vm.STAGE_LEARNING, facts=facts)
    assert [ly["key"] for ly in out["layers"]] == list(vm.LAYER_ORDER)
    blob = str(out["layers"])
    for probe in ("Wet 谐音", "w 像微波", "valleys", "web"):
        assert probe in blob


def test_hooks_are_ordered_after_semantics_so_the_answer_is_not_leaked_early():
    """声音/拼写钩子**天然含目标单词**（实测输出形如「Wet 谐音…」）。

    `NO_ANSWER_LEAK` 门禁只检查 recall_question 内部有没有藏目标词，**管不到
    跨层泄漏** —— 声音钩子放在语义层之前，等于在学生作答前就把词念给它听了。
    """
    keys = list(vm.LAYER_ORDER)
    for hook in ("sound_hook", "spelling_hook"):
        assert keys.index(hook) > keys.index("semantic_core")


def test_empty_layer_is_skipped_and_costs_no_reveal():
    """全空的层不该占掉一次「再看一层」—— 揭示预算比内容更贵。"""
    node = {**_node_row(), "sound_hook": None, "spelling_hook": None, "family_network": []}
    out = vm.render_review_ladder(node, stage=vm.STAGE_LEARNING)
    keys = [ly["key"] for ly in out["layers"]]
    assert "sound_hook" not in keys and "spelling_hook" not in keys
    assert out["hidden_count"] == 0, "跳过的层不该被算成「隐藏」"
    # 层号必须连续，不能因为跳过而留空洞
    assert [ly["layer"] for ly in out["layers"]] == list(range(1, len(keys) + 1))


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
    """`[法] 法案` 是带义项标签的释义 —— 可用，但标为 legacy 让人知道未派生。

    义项选择会**剥掉方括号领域标签**再喂给 LLM：`[法]` 是词性/领域标注，不是释义的
    一部分，留着只会干扰模型。原文仍完整保留在 `canonical_meaning` 里，可追溯。
    """
    item = SimpleNamespace(
        id="v1", word="bill", pos=None, meaning_cn=None,
        phonetic_arpabet=None, example_sentence=None,
        canonical_meaning="[法] 法案；广告；账单",
    )
    db = FakeDB(sentences=[], item=item)
    out = asyncio.run(vc.load_memory_input(db, "v1"))
    assert out["meaning_cn"] == "法案；广告；账单"
    assert out["meaning"]["tier"] == "legacy"
    assert out["meaning"]["gloss_source"] == "canonical_meaning(pos-selected sense)"


def test_load_memory_input_prefers_pos_selected_sense_over_truncated_meaning_cn():
    """CME-P1.6 的核心修复：`blind` 的 meaning_cn 只截了首义项（百叶窗）。

    `canonical_meaning` 有 adj. 义项、`pos` 列是 adj（默写表的策展值）→ 喂给 LLM 的
    必须是「盲目的；瞎的」，否则记忆卡会锚在**百叶窗**上。
    """
    item = SimpleNamespace(
        id="v1", word="blind", pos="adj", meaning_cn="掩饰，借口；百叶窗",
        phonetic_arpabet=None, example_sentence=None,
        canonical_meaning=(
            "n. 掩饰，借口；百叶窗\nadj. 盲目的；瞎的\n"
            "vt. 使失明；使失去理智\nadv. 盲目地；看不见地"
        ),
    )
    db = FakeDB(sentences=[], item=item)
    out = asyncio.run(vc.load_memory_input(db, "v1"))
    assert out["meaning_cn"] == "盲目的；瞎的"
    assert out["llm_entry"]["meaning_cn"] == "盲目的；瞎的"
    assert out["meaning"]["primary_sense"]["pos"] == "adj"
    # meaning_cn 本身**不被改写** —— 它是「教材原文可追溯」的载体
    assert item.meaning_cn == "掩饰，借口；百叶窗"


def test_load_memory_input_raises_on_unknown_id():
    db = FakeDB(sentences=[], item=None)
    with pytest.raises(KeyError):
        asyncio.run(vc.load_memory_input(db, "nope"))

def test_load_memory_input_falls_back_to_derived_gloss_when_textbook_has_only_ipa():
    """CME-P1.12：`diet` 的真实库内状态（meaning_cn 空 + canonical 是 `[ˈdaɪət]`）。

    有派生释义时，引擎拿到的应是 `derived_from_corpus` 档，而不是「没有释义」。
    没有它，第 10 条门禁 MEANING_AUTHORITY 会把这些词全部拒收（实测 16/100）。
    """
    item = SimpleNamespace(
        id="v1", word="diet", pos=None, meaning_cn=None,
        phonetic_arpabet="DA1 AY2 AH0 T", example_sentence=None,
        canonical_meaning="[ˈdaɪət]",
    )
    db = FakeDB(
        sentences=[],
        item=item,
        derived_gloss=SimpleNamespace(gloss="饮食；节食", source_sentence_id="s7"),
    )
    out = asyncio.run(vc.load_memory_input(db, "v1"))
    assert out["meaning_cn"] == "饮食；节食"
    assert out["llm_entry"]["meaning_cn"] == "饮食；节食"
    assert out["meaning"]["tier"] == "derived_from_corpus"
    # 出处可回溯到具体某一句
    assert out["derived_gloss"]["source_sentence_id"] == "s7"
    # 音标仍有正确去处，不是把读音丢掉就完了
    assert out["phonetic_arpabet"] == "DA1 AY2 AH0 T"


def test_textbook_gloss_still_wins_over_derived():
    """教材两列能给出释义时，派生释义**不参与**（派生档位低于 canonical/legacy）。

    注意实际生效的是**义项选择**：`canonical_meaning` 有 `n. 饮食` 且 pos=n →
    主义项就是「饮食」，它连 `meaning_cn` 都会盖过（义项选择优先于 meaning_cn，
    见 `test_load_memory_input_prefers_pos_selected_sense_over_truncated_meaning_cn`）。
    这里要钉的是「派生释义没被用上」这一条。
    """
    item = SimpleNamespace(
        id="v1", word="diet", pos="n", meaning_cn="饮食；食物",
        phonetic_arpabet=None, example_sentence=None, canonical_meaning="n. 饮食",
    )
    db = FakeDB(
        sentences=[], item=item,
        derived_gloss=SimpleNamespace(gloss="节食", source_sentence_id="s7"),
    )
    out = asyncio.run(vc.load_memory_input(db, "v1"))
    assert out["meaning"]["tier"] in ("canonical", "legacy")
    assert out["meaning"]["gloss_source"] == "canonical_meaning(pos-selected sense)"
    assert "节食" not in (out["meaning_cn"] or "")


# ── LLM 不可用时的失败形态（2026-10-04）─────────────────────────────────
# 实测 28 个上游只剩 space-bunny-free 间歇可用（gmi 402 / opencode-go 403+429 /
# nvidia-nim 超时）。此时必须**快速失败并说清缺什么**，而不是抛栈里的 oprim 异常
# 或用桩数据顶替。


def test_llm_unavailable_is_translated_into_an_actionable_error():
    """生成链路上的 LLM 故障 → LlmUnavailableError（503），带候选名单与处置提示。"""
    import services.mcp_router as mr
    from services.errors import LlmUnavailableError

    class _Boom:
        models = ["a", "b"]

        model = "a"

    class _Reg:
        @staticmethod
        def get():
            class _P:
                @staticmethod
                def llm(_name=None):
                    return _Boom()

            return _P()

    import obase.provider_registry as pr
    import services.providers.setup as ps
    orig_reg, orig_cfg = pr.ProviderRegistry, ps.configure_llm_providers
    pr.ProviderRegistry = _Reg
    ps.configure_llm_providers = lambda: None
    import oprim._vocab_memory_generate as mg

    async def _boom(entries, **kw):
        raise RuntimeError("all VEYA_MODEL candidates failed: a: x | b: y")

    orig_gen = mg.generate_memory_nodes
    mg.generate_memory_nodes = _boom
    try:
        import asyncio as _a
        from types import SimpleNamespace as _SN

        item = _SN(
            id="v1", word="abandon", pos="v", meaning_cn="放弃",
            phonetic_arpabet=None, example_sentence="They abandoned it.",
            canonical_meaning="vt. 放弃",
        )
        db = FakeDB(sentences=[_SN(
            id="s0", english_text="They abandoned it.", chinese_text=None, title="L1"
        )], item=item)

        with pytest.raises(LlmUnavailableError) as ei:
            _a.run(mr.tool_generate_memory_node(db, "v1"))
        assert ei.value.status_code == 503
        assert "['a', 'b']" in ei.value.detail
        assert "health/providers" in ei.value.detail, "必须告诉运维去哪儿看"
        assert ei.value.candidates == ["a", "b"]
    finally:
        pr.ProviderRegistry = orig_reg
        ps.configure_llm_providers = orig_cfg
        mg.generate_memory_nodes = orig_gen


def test_generate_route_maps_llm_unavailable_to_503(monkeypatch):
    """路由层必须把 LlmUnavailableError 映射成 **503**（不是 500）。

    这条单列是因为上一条只测了 tool 层：把路由里的
    `except LlmUnavailableError` 改成别的异常，tool 层测试**照样全绿**
    （变异验证时确实漏了一次）。而 503 与 500 的处置完全不同 ——
    503 表示「上游没有可用模型，别重试」，500 会让人以为是代码 bug。
    """
    import services.mcp_router as mr
    from fastapi import HTTPException
    from services.errors import LlmUnavailableError

    async def _raise(*_a, **_kw):
        raise LlmUnavailableError("没有可用模型", candidates=["x"])

    monkeypatch.setattr(mr, "tool_generate_memory_node", _raise)
    # 只需要一个带 id 的对象；_ensure_student_access 不会被调用（persist=false）
    user = SimpleNamespace(id=None)
    req = mr.GenerateMemoryNodeReq(vocabulary_item_id="v1", persist=False)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(mr.mcp_generate_memory_node(req, db=object(), current_user=user))
    assert ei.value.status_code == 503
    assert "没有可用模型" in ei.value.detail


# --------------------------------------------------------------------------
# family_candidates —— FAMILY_TRACEABLE 的输入侧（2026-10-04）
#
# 这批测试盯的是**两件实测踩到的事**，不是接口形状：
#   1. 剥 `y` 会让 `happy` 的词干变成 `happ`，把 `happen`/`happen to` 收成同族词；
#   2. 库里混着 `care about` 这类**短语**，不挡掉模型会挑中它们当派生词。
# 两条都各自钉一个回归用例，因为它们都是「看起来能跑、结果悄悄错了」的类型。
# --------------------------------------------------------------------------


def test_stem_keeps_y_because_it_is_part_of_the_root():
    """`happy` 剥掉 y → `happ` → 误收 `happen`（实测）。y 必须留着。"""
    assert vc._stem("happy") == "happy"
    assert vc._stem("valleys") == "valley"
    assert vc._stem("careful") == "care"
    assert vc._stem("quickly") == "quick"


def test_family_candidates_empty_word_never_queries():
    db = FakeDB()
    assert asyncio.run(vc.family_candidates(db, "")) == []
    assert db.calls == []


def test_family_candidates_short_stem_never_queries():
    """词干短于 4 的缩写（CD/DJ）没有前缀信号，别去查库。"""
    db = FakeDB()
    assert asyncio.run(vc.family_candidates(db, "CD")) == []
    assert db.calls == []


def test_family_candidates_excludes_phrases_and_self():
    """SQL 自身挡短语与自身；参数必须真的把 stem 传进去。"""
    db = FakeDB(fam_candidates=[FakeDB._cand("valleys", "山谷")])
    out = asyncio.run(vc.family_candidates(db, "valley"))
    assert [c["word"] for c in out] == ["valleys"]
    like_sql, like_params = next(
        (s, p) for s, p in db.calls if "LIKE :prefix" in s
    )
    assert like_params["prefix"] == "valley"
    assert like_params["target"] == "valley"
    # 短语过滤写在 SQL 里（库里 `care about` 这类混着）
    assert "!~ '\\s'" in like_sql or "!~ '\\\\s'" in like_sql


def test_family_candidates_merges_root_signal_deterministically():
    """词干前缀先入、词根信号后补；同词小写去重，顺序稳定。"""
    db = FakeDB(
        fam_candidates=[FakeDB._cand("valleys", "山谷")],
        fam_root_candidates=[FakeDB._cand("valleys", "重复"), FakeDB._cand("vale", "谷")],
    )
    out = asyncio.run(vc.family_candidates(db, "valley", vocabulary_item_id="v1"))
    assert [c["word"] for c in out] == ["valleys", "vale"], out


def test_family_candidates_respects_limit():
    db = FakeDB(fam_candidates=[FakeDB._cand(f"valley{i}") for i in range(9)])
    out = asyncio.run(vc.family_candidates(db, "valley", limit=4))
    assert len(out) == 4


def test_load_memory_input_hands_llm_real_family_candidates():
    """模型无从得知库里有哪些词 —— 候选必须由确定性算法喂进去。"""
    item = SimpleNamespace(
        id="v1", word="valley", pos="n.", meaning_cn="山谷",
        phonetic_arpabet=None, example_sentence="They walked down the valley.",
        canonical_meaning=None,
    )
    db = FakeDB(
        sentences=[], item=item,
        fam_candidates=[FakeDB._cand("valleys", "山谷（复数）")],
    )
    out = asyncio.run(vc.load_memory_input(db, "v1"))
    assert out["llm_entry"]["family_candidates"] == [
        {"word": "valleys", "meaning_cn": "山谷（复数）"}
    ]


def test_load_memory_input_gives_empty_family_list_for_proper_nouns():
    """专有名词本来就没有同族词，空清单是**合法输入**，交空数组才对。"""
    item = SimpleNamespace(
        id="v1", word="Canada", pos="n.", meaning_cn="加拿大",
        phonetic_arpabet=None, example_sentence="Canada is very cold.",
        canonical_meaning=None,
    )
    db = FakeDB(sentences=[], item=item, fam_candidates=[])
    out = asyncio.run(vc.load_memory_input(db, "v1"))
    assert out["llm_entry"]["family_candidates"] == []


def test_render_family_candidates_says_empty_loudly():
    """空清单渲染成「无」会诱导模型去猜；必须显式说明交空数组。"""
    assert "[]" in mg._render_family_candidates([])
    assert "空数组" in mg._render_family_candidates([])
    assert "valleys" in mg._render_family_candidates(
        [{"word": "valleys", "meaning_cn": "山谷"}]
    )


def test_prompt_forbids_inventing_family_words():
    """prompt 必须同时给出「只能从清单里挑」和「严禁编造清单外词」。"""
    assert "库内同族候选" in mg._SYSTEM
    assert "只能" in mg._SYSTEM
    assert "编造库内不存在的家族词" in mg._SYSTEM


# --------------------------------------------------------------------------
# 易混词（spec §五 ⚠️易混点 / §九 学习者自报混淆词）—— 2026-10-05
#
# 核心命题与 FAMILY_TRACEABLE 同源：**模型不知道库里有哪些词**，凭英语世界
# 知识作答会去编「其实不混淆」的对照词，而学生会把那条规则记一辈子。
# 所以清单由确定性判据（形近：长度差 ≤1 且编辑距离 ≤2）算出，模型只在清单里挑。
# --------------------------------------------------------------------------

from types import SimpleNamespace as _SN  # noqa: E402


def _cand(word: str, meaning_cn: str | None = None, pos: str | None = None):
    return _SN(id=f"id-{word}", word=word, meaning_cn=meaning_cn, pos=pos)


def test_edit_distance_le_basics():
    assert vc._edit_distance_le("affect", "effect", 2) == 1
    assert vc._edit_distance_le("adapt", "adopt", 2) == 1
    assert vc._edit_distance_le("desert", "dessert", 2) == 1
    assert vc._edit_distance_le("wet", "wet", 2) == 0
    # 超过 cap 时提前返回 cap+1（不是精确距离）—— 只用于判「是否形近」
    assert vc._edit_distance_le("abc", "xyzxyz", 2) == 3
    # 长度差 > cap 直接出局，不必算
    assert vc._edit_distance_le("a", "abcdef", 2) == 3


def test_confusable_candidates_short_word_never_queries():
    """短于 4 的词没有可用形近信号，别去查库。"""
    db = FakeDB()
    assert asyncio.run(vc.confusable_candidates(db, "wet")) == []
    assert db.calls == []


def test_confusable_candidates_keeps_only_near_spelling_and_sorts_by_distance():
    """判据是**真算**编辑距离，不是「像不像」，且上限是 **1**。

    上限从 2 收到 1 是被 100 词试跑的数据逼的：距离=1 的易混对实测 100% 真，
    距离≥2 的多数是噪声（`offer`/`coffee`、`boss`/`Boys`）。

    `adapt`→`adopt`、`adapt`→`adept` 都是 1，必须收；`adapt`→`adult` 是 2、
    `adapt`→`alert` 是 3，都必须剔。同距离按字母序（`adept` 先于 `adopt`）——
    这是文档承诺的 tie-break，不是 bug。
    """
    db = FakeDB(confusables=[_cand("adopt"), _cand("adult"), _cand("adept"), _cand("alert")])
    out = asyncio.run(vc.confusable_candidates(db, "adapt"))
    words = [c["word"] for c in out]
    assert words == ["adept", "adopt"], words
    assert "adult" not in words, "距离 2 已超上限 1 —— 收进来就是噪声"
    assert "alert" not in words
    sql, params = db.calls[0]
    assert params["target"] == "adapt"
    assert params["lo"] == 4 and params["hi"] == 6, "长度差必须 ≤1"


def test_confusable_candidates_respects_limit():
    # `adapt0`..`adapt8` 对 `adapt` 的距离是 1（尾部多一个字符），都应收
    db = FakeDB(confusables=[_cand(f"adapt{i}") for i in range(9)])
    out = asyncio.run(vc.confusable_candidates(db, "adapt", limit=3))
    assert len(out) == 3
    assert [c["word"] for c in out] == ["adapt0", "adapt1", "adapt2"]


def test_gate_rejects_confusable_outside_the_candidate_list():
    """模型编了一个库内/候选外的对照词 → 拒收。"""
    mi = _memory_input(llm_entry={"confusable_candidates": [{"word": "effect"}]})
    node = {**_good_node(), "confusables": [{"word": "affect", "distinguish_cn": "…"}]}
    rep = _report(node, memory_input=mi, confusable_candidates=[{"word": "effect"}])
    assert vm.GATE_CONFUSABLES_GROUNDED in rep.failed_gates


def test_gate_accepts_confusable_inside_the_candidate_list():
    mi = _memory_input(llm_entry={"confusable_candidates": [{"word": "effect"}]})
    node = {**_good_node(), "confusables": [{"word": "effect", "distinguish_cn": "名=结果"}]}
    rep = _report(node, memory_input=mi, confusable_candidates=[{"word": "effect"}])
    assert vm.GATE_CONFUSABLES_GROUNDED not in rep.failed_gates
    assert rep.failed_gates == [], f"其余门禁也该过: {rep.failed_gates}"


def test_learner_declared_confusion_is_grounded_without_being_in_candidates():
    """spec §九：学习者自报的混淆词是**学生自己的经验**，不要求库内/候选内。"""
    mi = _memory_input(
        llm_entry={
            "confusable_candidates": [{"word": "adopt"}],
            "learner_confused_with": "effect",
        }
    )
    node = {**_good_node(), "confusables": [{"word": "effect", "distinguish_cn": "…"}]}
    rep = _report(node, memory_input=mi, confusable_candidates=[{"word": "adopt"}])
    assert vm.GATE_CONFUSABLES_GROUNDED not in rep.failed_gates


def test_gate_passes_when_no_confusables_offered():
    """没有易混对照词**不是缺陷** —— 库内无形近词时不该硬凑。"""
    rep = _report(
        {**_good_node(), "confusables": []},
        memory_input=_memory_input(llm_entry={"confusable_candidates": []}),
        confusable_candidates=[],
    )
    assert vm.GATE_CONFUSABLES_GROUNDED not in rep.failed_gates


def test_load_memory_input_gives_learner_confusion_to_the_llm():
    item = _SN(
        id="v1", word="affect", pos="v.", meaning_cn="影响",
        phonetic_arpabet=None, example_sentence="It will affect you.",
        canonical_meaning=None,
    )
    db = FakeDB(sentences=[], item=item, confusables=[_cand("effect", "结果")])
    out = asyncio.run(vc.load_memory_input(db, "v1", learner_confused_with="Effect"))
    entry = out["llm_entry"]
    assert entry["learner_confused_with"] == "Effect"
    assert [c["word"] for c in entry["confusable_candidates"]] == ["effect"]


def test_prompt_demands_confusables_come_from_the_list():
    assert "库内形近易混候选" in mg._SYSTEM
    assert "编造清单外的易混词" in mg._SYSTEM
    assert "confusables" in mg._SYSTEM
    # 空清单必须显式说明，否则模型会去猜
    assert "confusables 请输出空数组" in mg._render_confusable_candidates([])


def test_confusables_reach_the_student_as_their_own_layer():
    node = {**_node_row(), "confusable_words": [_cand("effect", "结果")]}
    facts = {"word_origin": {"chain": "a·ffect", "should_display": True}}
    out = vm.render_review_ladder(node, stage=vm.STAGE_LEARNING, facts=facts)
    keys = [ly["key"] for ly in out["layers"]]
    assert "confusables" in keys
    assert "effect" in str(out["layers"])


def test_empty_confusables_layer_does_not_cost_a_reveal():
    node = {**_node_row(), "confusable_words": []}
    out = vm.render_review_ladder(node, stage=vm.STAGE_LEARNING)
    assert "confusables" not in [ly["key"] for ly in out["layers"]]
    assert out["hidden_count"] == 0


# --------------------------------------------------------------------------
# HAS_RECALL_HOOK 误杀（2026-10-05 100 词试跑实测）
#
# 原判据只认 `？`/`?` 结尾，于是 `spread` 被拒 —— 它的问句是
# 「把画卷向两边拉展的动作叫什么」。那是个好问题，只是漏了问号。
# 与 `HAS_ONE_CORE_IMAGE` 下限 8（4/4 误杀，下限已降到 5）是同一类错误：
# **门禁在测格式，不是在测记忆质量**。
# --------------------------------------------------------------------------

_REAL_FALSE_KILL = "把画卷向两边拉展的动作叫什么"  # spread，逐字取自试跑报告


def test_recall_question_without_question_mark_still_passes():
    node = {**_good_node(), "recall_question": _REAL_FALSE_KILL}
    assert vm.GATE_HAS_RECALL_HOOK not in _report(node).failed_gates


def test_declarative_recall_text_is_still_rejected():
    """放松不等于放水：**真陈述句**仍必须被拒，否则这道门禁形同虚设。

    `什么动物在跑` 原本被我列进这里，但那是**臆想的断言**而不是实测数据 ——
    它也可以合理读成「什么动物在跑？」。含疑问词就放过，是有意的取舍：
    这道门禁守的是「有没有主动回忆问」，不是标点。
    """
    for text in ("这是弃船的画面", "记忆卡片", "船长松开缆绳弃船逃离", "你会记得吗"):
        node = {**_good_node(), "recall_question": text}
        assert vm.GATE_HAS_RECALL_HOOK in _report(node).failed_gates, text


def test_looks_like_question_covers_the_documented_tails():
    for text in (
        "把画卷向两边拉展的动作叫什么",
        "船长松开缆绳弃船是什么动作？",
        "这是哪一步",
        "他是谁",
        "发生了多少",
        "这是否弃船",
    ):
        assert vm._looks_like_question(text), text
    for text in ("这是弃船的画面", "记忆卡片", "", "你会记得吗"):
        assert not vm._looks_like_question(text), text
