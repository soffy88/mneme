"""铜匠实验室事实表方法 + lesson catalog 契约（Mneme 干净重写）。

方法来源：Tongjiang Lab（lab.tongjiang.app，作者“铜匠十点睡觉”），
许可证 CC BY-NC 4.0，署名 "Tongjiang Lab"，非商业使用、改编允许。
本模块只学方法（事实表 A/B 分栏、逐步依据标注、预期读数、课堂提问
带教材依据；catalog.json 课→章节→步骤→提问契约），**未复制对方
任何课文、HTML、代码或数据**；示例事实表为自编的合成演示，不是
教材原文。Mneme 按 Soffy 定调不商用，与 CC BY-NC 4.0 相容；一旦
Mneme 收费或作商业获客，须先与原作者另谈授权。

事实表（fact table）：
- A 栏：教材事实，每条带页码级出处（textbook ref + page），是唯一
  可被步骤/提问引为依据的来源。
- B 栏：课件设定——为教学所选的数值/公式，档位只能是 illustrative
  或 calculation，绝不能标 source_fact；每条须引至少一条 A 事实。
- 步骤：每步引 A 事实、带预期读数（TaggedNumber，note 写公式与假设）。
- 提问：每问有答案，依据只能是 A 事实（不能只引 B 设定）。

catalog（B 类）：课 → 教材章节 → 步骤 → 提问的契约；课须指到已验
事实表；物理平抛主题不得另起内容，须指到 Atlas 注册模型
projectile_motion（与 Atlas 平抛直接重复处不新增内容）。

本模块是纯函数，无 DB、无网络、无 LLM。零迁移：事实表与 catalog
走既有 JSONB/spec 契约层，不新增表。
"""

from __future__ import annotations

import re
from typing import Any, Callable, Collection, Mapping

from services.citation_check import check_citations
from services.teaching_figure import (
    NumberKind,
    TaggedNumber,
    ValidationIssue,
    ValidationResult,
)

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")
_A_ID_RE = re.compile(r"^A\d+\.\d+$")
_B_ID_RE = re.compile(r"^B\d+$")
_STEP_ID_RE = re.compile(r"^S\d+$")
_QUESTION_ID_RE = re.compile(r"^Q\d+$")
_B_MENTION_RE = re.compile(r"\bB\d+\b")
_SUBJECTS = ("physics", "chemistry", "biology", "geography", "mathematics")
_PROJECTILE_TERMS = ("平抛", "projectile")

LedgerCheck = Callable[[Mapping[str, Any]], Any]


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _tagged(raw: object) -> TaggedNumber | None:
    try:
        return TaggedNumber.from_dict(raw)
    except (TypeError, ValueError):
        return None


def _check_basis(
    basis: object,
    a_ids: set[str],
    field: str,
    issues: list[ValidationIssue],
) -> None:
    """依据栏：非空、只引 A 事实、引用的 A 事实必须存在。"""
    if not isinstance(basis, list) or not basis:
        issues.append(
            ValidationIssue(field, "basis_required",
                            f"{field} must cite at least one A fact")
        )
        return
    for ref in basis:
        if not isinstance(ref, str):
            issues.append(
                ValidationIssue(field, "bad_basis_ref",
                                "basis entries must be A fact ids")
            )
        elif _B_ID_RE.match(ref):
            issues.append(
                ValidationIssue(
                    field, "basis_uses_setting",
                    f"basis must cite A facts, not courseware setting {ref!r}",
                )
            )
        elif ref not in a_ids:
            issues.append(
                ValidationIssue(field, "unknown_a_fact",
                                f"basis cites unknown A fact {ref!r}")
            )


def verify_fact_table(
    table: object,
    *,
    known_ku_ids: Collection[str] | None = None,
    known_textbook_ids: Collection[str] | None = None,
    ledger_check: LedgerCheck | None = None,
) -> ValidationResult:
    """事实表验证门 f1–f8，全过才可用。ledger 未注入即不过（fail-closed）。"""
    issues: list[ValidationIssue] = []
    notes: list[str] = []
    gates: dict[str, bool] = {f"f{i}": True for i in range(1, 9)}

    def fail(gate: str, issue: ValidationIssue) -> None:
        gates[gate] = False
        issues.append(issue)

    if not isinstance(table, dict):
        fail("f1", ValidationIssue("$", "not_object", "fact table must be an object"))
        return ValidationResult(False, issues, notes, gates)

    # f1：schema 合法、id 唯一形态、必填齐全。
    table_id = table.get("id")
    if not isinstance(table_id, str) or not _ID_RE.match(table_id):
        fail("f1", ValidationIssue("id", "bad_id",
                                   "id must be a slug: [a-z0-9][a-z0-9_-]{0,99}"))
    for field_name in ("title", "subject", "facts", "settings", "steps",
                       "questions", "assertions"):
        if field_name not in table:
            fail("f1", ValidationIssue(field_name, "missing_field",
                                       f"missing required field {field_name!r}"))
    title = table.get("title")
    if "title" in table and (not isinstance(title, str) or not title.strip()):
        fail("f1", ValidationIssue("title", "bad_title",
                                   "title must be a non-empty string"))
    subject = table.get("subject")
    if "subject" in table and subject not in _SUBJECTS:
        fail("f1", ValidationIssue("subject", "bad_subject",
                                   f"subject must be one of {_SUBJECTS}"))

    # f2：A 栏事实非空、id 唯一、每条带页码级教材出处。
    a_ids: set[str] = set()
    facts = table.get("facts")
    if not isinstance(facts, list) or not facts:
        fail("f2", ValidationIssue("facts", "facts_required",
                                   "facts must be a non-empty list"))
        facts = []
    for idx, fact in enumerate(facts):
        base = f"facts[{idx}]"
        if not isinstance(fact, dict):
            fail("f2", ValidationIssue(base, "bad_fact", "fact must be an object"))
            continue
        fact_id = fact.get("id")
        if not isinstance(fact_id, str) or not _A_ID_RE.match(fact_id):
            fail("f2", ValidationIssue(f"{base}.id", "bad_a_id",
                                       "A fact id must look like A<chapter>.<n>"))
            continue
        if fact_id in a_ids:
            fail("f2", ValidationIssue(f"{base}.id", "duplicate_a_id",
                                       f"duplicate A fact id {fact_id!r}"))
        a_ids.add(fact_id)
        statement = fact.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            fail("f2", ValidationIssue(f"{base}.statement", "bad_statement",
                                       "statement must be a non-empty string"))
        source = fact.get("source")
        if not isinstance(source, dict):
            fail("f2", ValidationIssue(f"{base}.source", "bad_source",
                                       "source must be an object"))
            continue
        if source.get("kind") != "textbook":
            fail("f2", ValidationIssue(f"{base}.source.kind", "bad_source_kind",
                                       "A fact source kind must be 'textbook'"))
        if not isinstance(source.get("ref"), str) or not source["ref"].strip():
            fail("f2", ValidationIssue(f"{base}.source.ref", "bad_source_ref",
                                       "source ref must be a non-empty textbook id"))
        page = source.get("page")
        if not _is_int(page) or page <= 0:
            fail("f2", ValidationIssue(f"{base}.source.page", "bad_page",
                                       "source page must be a positive integer"))

    # f3：B 栏设定——档位绝不能是 source_fact，每条须引已存在的 A 事实。
    settings = table.get("settings")
    if not isinstance(settings, list):
        fail("f3", ValidationIssue("settings", "bad_settings",
                                   "settings must be a list"))
        settings = []
    b_ids: set[str] = set()
    for idx, setting in enumerate(settings):
        base = f"settings[{idx}]"
        if not isinstance(setting, dict):
            fail("f3", ValidationIssue(base, "bad_setting", "setting must be an object"))
            continue
        setting_id = setting.get("id")
        if not isinstance(setting_id, str) or not _B_ID_RE.match(setting_id):
            fail("f3", ValidationIssue(f"{base}.id", "bad_b_id",
                                       "setting id must look like B<n>"))
            continue
        if setting_id in b_ids:
            fail("f3", ValidationIssue(f"{base}.id", "duplicate_b_id",
                                       f"duplicate setting id {setting_id!r}"))
        b_ids.add(setting_id)
        if not isinstance(setting.get("name"), str) or not setting["name"].strip():
            fail("f3", ValidationIssue(f"{base}.name", "bad_name",
                                       "setting name must be a non-empty string"))
        tagged = _tagged(setting.get("value"))
        if tagged is None:
            fail("f3", ValidationIssue(f"{base}.value", "bad_value",
                                       "setting value must be a tagged number"))
        elif tagged.kind == NumberKind.SOURCE_FACT:
            fail("f3", ValidationIssue(
                f"{base}.value", "setting_claims_source_fact",
                "courseware settings are chosen for teaching, never source facts"))
        _check_basis(setting.get("basis"), a_ids, f"{base}.basis", issues)
        if any(i.field == f"{base}.basis" for i in issues):
            gates["f3"] = False

    # f4：步骤非空、每步引 A 事实、带预期读数。
    steps = table.get("steps")
    if not isinstance(steps, list) or not steps:
        fail("f4", ValidationIssue("steps", "steps_required",
                                   "steps must be a non-empty list"))
        steps = []
    step_ids: set[str] = set()
    for idx, step in enumerate(steps):
        base = f"steps[{idx}]"
        if not isinstance(step, dict):
            fail("f4", ValidationIssue(base, "bad_step", "step must be an object"))
            continue
        step_id = step.get("id")
        if not isinstance(step_id, str) or not _STEP_ID_RE.match(step_id):
            fail("f4", ValidationIssue(f"{base}.id", "bad_step_id",
                                       "step id must look like S<n>"))
            continue
        if step_id in step_ids:
            fail("f4", ValidationIssue(f"{base}.id", "duplicate_step_id",
                                       f"duplicate step id {step_id!r}"))
        step_ids.add(step_id)
        if not isinstance(step.get("title"), str) or not step["title"].strip():
            fail("f4", ValidationIssue(f"{base}.title", "bad_step_title",
                                       "step title must be a non-empty string"))
        _check_basis(step.get("basis"), a_ids, f"{base}.basis", issues)
        if any(i.field == f"{base}.basis" for i in issues):
            gates["f4"] = False
        reading = _tagged(step.get("expected_reading"))
        if reading is None:
            fail("f4", ValidationIssue(f"{base}.expected_reading", "bad_reading",
                                       "expected_reading must be a tagged number"))
        elif not reading.note.strip():
            fail("f4", ValidationIssue(f"{base}.expected_reading", "reading_note_required",
                                       "expected_reading note must state the formula"))

    # f5：提问非空、每问有答案、依据只能是 A 事实。
    questions = table.get("questions")
    if not isinstance(questions, list) or not questions:
        fail("f5", ValidationIssue("questions", "questions_required",
                                   "questions must be a non-empty list"))
        questions = []
    question_ids: set[str] = set()
    for idx, question in enumerate(questions):
        base = f"questions[{idx}]"
        if not isinstance(question, dict):
            fail("f5", ValidationIssue(base, "bad_question",
                                       "question must be an object"))
            continue
        question_id = question.get("id")
        if not isinstance(question_id, str) or not _QUESTION_ID_RE.match(question_id):
            fail("f5", ValidationIssue(f"{base}.id", "bad_question_id",
                                       "question id must look like Q<n>"))
            continue
        if question_id in question_ids:
            fail("f5", ValidationIssue(f"{base}.id", "duplicate_question_id",
                                       f"duplicate question id {question_id!r}"))
        question_ids.add(question_id)
        if not isinstance(question.get("prompt"), str) or not question["prompt"].strip():
            fail("f5", ValidationIssue(f"{base}.prompt", "bad_prompt",
                                       "prompt must be a non-empty string"))
        if not isinstance(question.get("answer"), str) or not question["answer"].strip():
            fail("f5", ValidationIssue(f"{base}.answer", "bad_answer",
                                       "answer must be a non-empty string"))
        _check_basis(question.get("basis"), a_ids, f"{base}.basis", issues)
        if any(i.field == f"{base}.basis" for i in issues):
            gates["f5"] = False

    # f6：A/B 严格分离——A 事实陈述中不得出现 B 设定编号。
    for idx, fact in enumerate(facts):
        if not isinstance(fact, dict):
            continue
        statement = fact.get("statement")
        if isinstance(statement, str) and _B_MENTION_RE.search(statement):
            fail("f6", ValidationIssue(
                f"facts[{idx}].statement", "a_fact_mentions_setting",
                "textbook facts must not reference courseware settings"))
    if not settings:
        notes.append("settings is empty: no courseware settings to separate")

    # f7：出处断言过 citation_check（textbook/KU 须在已知集内，fail-closed）。
    assertions = table.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        fail("f7", ValidationIssue("assertions", "assertions_required",
                                   "assertions must be a non-empty list"))
    else:
        checked = check_citations(
            assertions,
            known_ku_ids=set(known_ku_ids) if known_ku_ids is not None else None,
            known_textbook_ids=(
                set(known_textbook_ids) if known_textbook_ids is not None else None
            ),
        )
        if not checked["passed"]:
            for segment in checked["segments"]:
                for item in segment["issues"]:
                    fail("f7", ValidationIssue(
                        f"assertions[{segment['index']}]", item["code"],
                        item["message"]))
            if checked["issues"]:
                for item in checked["issues"]:
                    fail("f7", ValidationIssue("assertions", item["code"],
                                               item["message"]))

    # f8：出处台账门禁（注入式；未注入即不过，与 interactive_page g10 同口径）。
    if ledger_check is None:
        fail("f8", ValidationIssue("ledger", "ledger_gate_unavailable",
                                   "source-ledger gate was not injected"))
    else:
        try:
            result = ledger_check(table)
            ok = result is True or (
                isinstance(result, Mapping) and result.get("passed") is True
            )
        except Exception as exc:  # noqa: BLE001 - 门禁异常不放行，只记录
            fail("f8", ValidationIssue("ledger", "ledger_check_error",
                                       f"ledger gate raised: {exc}"))
            ok = False
        if not ok and not any(i.code == "ledger_check_error" for i in issues):
            fail("f8", ValidationIssue("ledger", "ledger_failed",
                                       "source-ledger gate rejected the fact table"))

    _CODE_TO_GATE = {
        "not_object": "f1", "bad_id": "f1", "missing_field": "f1",
        "bad_title": "f1", "bad_subject": "f1",
        "facts_required": "f2", "bad_fact": "f2", "bad_a_id": "f2",
        "duplicate_a_id": "f2", "bad_statement": "f2", "bad_source": "f2",
        "bad_source_kind": "f2", "bad_source_ref": "f2", "bad_page": "f2",
        "bad_settings": "f3", "bad_setting": "f3", "bad_b_id": "f3",
        "duplicate_b_id": "f3", "bad_name": "f3", "bad_value": "f3",
        "setting_claims_source_fact": "f3",
        "steps_required": "f4", "bad_step": "f4", "bad_step_id": "f4",
        "duplicate_step_id": "f4", "bad_step_title": "f4",
        "bad_reading": "f4", "reading_note_required": "f4",
        "questions_required": "f5", "bad_question": "f5",
        "bad_question_id": "f5", "duplicate_question_id": "f5",
        "bad_prompt": "f5", "bad_answer": "f5",
        # basis_* codes are NOT mapped here: _check_basis is shared by f3/f4/f5
        # and each caller sets its own gate explicitly after the call.
        "a_fact_mentions_setting": "f6",
        "assertions_required": "f7",
        "ledger_gate_unavailable": "f8", "ledger_failed": "f8",
        "ledger_check_error": "f8",
    }
    for issue in issues:
        gate = _CODE_TO_GATE.get(issue.code)
        if gate is not None:
            gates[gate] = False

    return ValidationResult(passed=not issues, issues=issues, notes=notes,
                            gates=gates)


def verify_lesson_catalog(
    catalog: object,
    *,
    fact_tables: Mapping[str, Mapping[str, Any]] | None = None,
    known_atlas_models: Collection[str] | None = None,
) -> ValidationResult:
    """catalog 契约验证门 c1–c6，全过才可用。

    fact_tables：id → 事实表 dict；不传即 fact_table_id 无法核验，
    fail-closed。known_atlas_models：Atlas 注册模型名集；课指到 Atlas
    模型时才需要，同样 fail-closed。
    """
    issues: list[ValidationIssue] = []
    notes: list[str] = []
    gates: dict[str, bool] = {f"c{i}": True for i in range(1, 7)}

    def fail(gate: str, issue: ValidationIssue) -> None:
        gates[gate] = False
        issues.append(issue)

    if not isinstance(catalog, dict):
        fail("c1", ValidationIssue("$", "not_object", "catalog must be an object"))
        return ValidationResult(False, issues, notes, gates)

    lessons = catalog.get("lessons")
    if not isinstance(lessons, list) or not lessons:
        fail("c1", ValidationIssue("lessons", "lessons_required",
                                   "lessons must be a non-empty list"))
        return ValidationResult(False, issues, notes, gates)

    lesson_ids: set[str] = set()
    for idx, lesson in enumerate(lessons):
        base = f"lessons[{idx}]"
        if not isinstance(lesson, dict):
            fail("c1", ValidationIssue(base, "bad_lesson", "lesson must be an object"))
            continue
        lesson_id = lesson.get("id")
        if not isinstance(lesson_id, str) or not _ID_RE.match(lesson_id):
            fail("c1", ValidationIssue(f"{base}.id", "bad_id",
                                       "id must be a slug: [a-z0-9][a-z0-9_-]{0,99}"))
            continue
        if lesson_id in lesson_ids:
            fail("c1", ValidationIssue(f"{base}.id", "duplicate_lesson_id",
                                       f"duplicate lesson id {lesson_id!r}"))
        lesson_ids.add(lesson_id)
        for field_name in ("title", "subject", "textbook_chapter",
                           "fact_table_id", "step_ids", "question_ids"):
            if field_name not in lesson:
                fail("c1", ValidationIssue(f"{base}.{field_name}", "missing_field",
                                           f"missing required field {field_name!r}"))
        if not isinstance(lesson.get("title"), str) or not lesson["title"].strip():
            fail("c1", ValidationIssue(f"{base}.title", "bad_title",
                                       "title must be a non-empty string"))

        # c4：学科与教材章节。
        if lesson.get("subject") not in _SUBJECTS:
            fail("c4", ValidationIssue(f"{base}.subject", "bad_subject",
                                       f"subject must be one of {_SUBJECTS}"))
        chapter = lesson.get("textbook_chapter")
        if not isinstance(chapter, str) or not chapter.strip():
            fail("c4", ValidationIssue(f"{base}.textbook_chapter", "bad_chapter",
                                       "textbook_chapter must be a non-empty string"))

        # c2/c3：指到的事实表必须存在，步骤/提问须在该表内。
        table_id = lesson.get("fact_table_id")
        table: Mapping[str, Any] | None = None
        if not isinstance(table_id, str) or not table_id:
            fail("c2", ValidationIssue(f"{base}.fact_table_id", "bad_fact_table_id",
                                       "fact_table_id must be a non-empty string"))
        elif fact_tables is None:
            fail("c2", ValidationIssue(f"{base}.fact_table_id", "fact_tables_unchecked",
                                       "fact table references cannot be verified"))
        elif table_id not in fact_tables:
            fail("c2", ValidationIssue(f"{base}.fact_table_id", "unknown_fact_table",
                                       f"fact table {table_id!r} does not exist"))
        else:
            table = fact_tables[table_id]
        if table is not None:
            known_steps = {
                s.get("id") for s in table.get("steps", [])
                if isinstance(s, dict)
            }
            known_questions = {
                q.get("id") for q in table.get("questions", [])
                if isinstance(q, dict)
            }
            for field_name, known in (("step_ids", known_steps),
                                      ("question_ids", known_questions)):
                refs = lesson.get(field_name)
                if not isinstance(refs, list) or not refs:
                    fail("c3", ValidationIssue(
                        f"{base}.{field_name}", "refs_required",
                        f"{field_name} must be a non-empty list"))
                    continue
                for ref in refs:
                    if ref not in known:
                        fail("c3", ValidationIssue(
                            f"{base}.{field_name}", "unknown_ref",
                            f"{field_name} cites {ref!r}, not in fact table "
                            f"{table_id!r}"))
        elif fact_tables is not None:
            # 事实表不存在时步骤/提问无从核验，c3 同样不过。
            gates["c3"] = False
            issues.append(ValidationIssue(
                f"{base}", "refs_unchecked",
                "step/question references cannot be checked without the fact table"))

        # c5：Atlas 重叠——平抛主题不得另起内容，须指到 projectile_motion。
        keywords = lesson.get("topic_keywords") or []
        title = lesson.get("title") or ""
        haystack = " ".join([title] + [str(k) for k in keywords if isinstance(k, str)])
        is_projectile = any(t in haystack for t in _PROJECTILE_TERMS)
        atlas_ref = lesson.get("atlas_model_ref")
        if is_projectile and atlas_ref != "projectile_motion":
            fail("c5", ValidationIssue(
                f"{base}.atlas_model_ref", "atlas_overlap_unresolved",
                "projectile-motion lessons must reference Atlas model "
                "'projectile_motion' instead of duplicating its content"))
        elif atlas_ref is not None:
            if known_atlas_models is None:
                fail("c5", ValidationIssue(f"{base}.atlas_model_ref",
                                           "atlas_models_unchecked",
                                           "Atlas model reference cannot be verified"))
            elif atlas_ref not in known_atlas_models:
                fail("c5", ValidationIssue(f"{base}.atlas_model_ref",
                                           "unknown_atlas_model",
                                           f"Atlas model {atlas_ref!r} is not registered"))

        # c6：主题关键词形态（有则须为非空字符串列表）。
        if "topic_keywords" in lesson:
            if not isinstance(keywords, list) or not keywords or not all(
                isinstance(k, str) and k.strip() for k in keywords
            ):
                fail("c6", ValidationIssue(f"{base}.topic_keywords",
                                           "bad_topic_keywords",
                                           "topic_keywords must be a non-empty list of strings"))

    _CODE_TO_GATE = {
        "not_object": "c1", "lessons_required": "c1", "bad_lesson": "c1",
        "bad_id": "c1", "duplicate_lesson_id": "c1", "missing_field": "c1",
        "bad_title": "c1",
        "bad_fact_table_id": "c2", "fact_tables_unchecked": "c2",
        "unknown_fact_table": "c2",
        "refs_required": "c3", "unknown_ref": "c3", "refs_unchecked": "c3",
        "bad_subject": "c4", "bad_chapter": "c4",
        "atlas_overlap_unresolved": "c5", "atlas_models_unchecked": "c5",
        "unknown_atlas_model": "c5",
        "bad_topic_keywords": "c6",
    }
    for issue in issues:
        gate = _CODE_TO_GATE.get(issue.code)
        if gate is not None:
            gates[gate] = False

    return ValidationResult(passed=not issues, issues=issues, notes=notes,
                            gates=gates)


def example_fact_table() -> dict[str, Any]:
    """合成演示事实表（单摆周期；非教材原文，仅演示 A/B 分栏形状）。"""
    return {
        "id": "demo-pendulum-fact-table",
        "title": "单摆周期",
        "subject": "physics",
        "facts": [
            {
                "id": "A1.1",
                "statement": "单摆周期公式为 T=2π√(L/g)，周期由摆长与重力加速度决定。",
                "source": {"kind": "textbook", "ref": "demo-textbook", "page": 42},
            },
            {
                "id": "A1.2",
                "statement": "摆角小于 5° 时，单摆运动可近似为简谐运动。",
                "source": {"kind": "textbook", "ref": "demo-textbook", "page": 43},
            },
            {
                "id": "A2.1",
                "statement": "单摆周期与摆球质量无关。",
                "source": {"kind": "textbook", "ref": "demo-textbook", "page": 42},
            },
        ],
        "settings": [
            {
                "id": "B1",
                "name": "演示摆角",
                "value": {"value": 5, "unit": "°", "kind": "illustrative",
                          "note": "为教学所选的演示摆角，取小角度条件上限"},
                "basis": ["A1.2"],
            },
            {
                "id": "B2",
                "name": "演示摆长",
                "value": {"value": 1.0, "unit": "m", "kind": "illustrative",
                          "note": "为教学所选的演示摆长"},
                "basis": ["A1.1"],
            },
        ],
        "steps": [
            {
                "id": "S1",
                "title": "固定摆长 1.0m，测单摆周期",
                "basis": ["A1.1"],
                "expected_reading": {
                    "value": 2.0, "unit": "s", "kind": "calculation",
                    "note": "T=2π√(L/g)，L=1.0m，g=9.8m/s²，约 2.0s",
                },
            },
            {
                "id": "S2",
                "title": "测 10 次全振动总时间",
                "basis": ["A1.1", "A2.1"],
                "expected_reading": {
                    "value": 20.0, "unit": "s", "kind": "calculation",
                    "note": "10×T，T 约 2.0s",
                },
            },
        ],
        "questions": [
            {
                "id": "Q1",
                "prompt": "单摆周期与哪些量有关，与摆球质量有关吗？",
                "answer": "与摆长和重力加速度有关，与摆球质量无关。",
                "basis": ["A1.1", "A2.1"],
            },
            {
                "id": "Q2",
                "prompt": "实验中为什么要求摆角小于 5°？",
                "answer": "摆角小于 5° 时单摆运动才可近似为简谐运动，周期公式才成立。",
                "basis": ["A1.2"],
            },
        ],
        "assertions": [
            {
                "text": "单摆周期公式为 T=2π√(L/g)",
                "refs": [{"kind": "textbook", "id": "demo-textbook"}],
            },
        ],
    }


def example_catalog() -> dict[str, Any]:
    """合成演示 catalog：单摆课指到示例事实表与 Atlas 单摆模型（不另起内容）。"""
    return {
        "lessons": [
            {
                "id": "demo-pendulum-lesson",
                "title": "单摆周期",
                "subject": "physics",
                "textbook_chapter": "选择性必修1 第2章",
                "fact_table_id": "demo-pendulum-fact-table",
                "step_ids": ["S1", "S2"],
                "question_ids": ["Q1", "Q2"],
                "atlas_model_ref": "pendulum_small_angle",
                "topic_keywords": ["单摆", "简谐运动"],
            },
        ],
    }


__all__ = [
    "LedgerCheck",
    "example_catalog",
    "example_fact_table",
    "verify_fact_table",
    "verify_lesson_catalog",
]
