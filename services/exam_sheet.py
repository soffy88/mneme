"""组卷打印闭环：ExamSheet 规格、拼装、导出与结果回填。

方法来源 wrong-notebook 只学方法、干净重写；本文件不含对方代码。
命名避让：papers 表是拍照录入的来源试卷（processing/done/failed），
组卷产物另称 exam sheet，表 exam_sheets / exam_sheet_results。

红线：
- 题干/答案只取错题行快照，不现编；无答案的题答案页留空并标注。
- 回填只追加 QuestionRecord，并走既有 schedule_after_answer 排期纪律；
  绝不直接写 BKT 掌握度（BKT 是掌握唯一裁决源，FSRS 只排期）。
- 导出不嵌图片字节、不出签名 URL；配图只列对象键 caption。
- 同一题在同一组卷内重复回填返回 409（调用方定死的口径）。
"""

from __future__ import annotations

import html as _html
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from typing import Any, Mapping, Optional, Sequence
from xml.sax.saxutils import escape as _xml_escape

# ── 留白 ───────────────────────────────────────────────────────────────────

#: 留白模式：auto 按题型推断；fixed 四档固定高度。
WHITESPACE_MODES: tuple[str, ...] = ("auto", "none", "small", "medium", "large")

#: 固定留白高度（px）。auto 模式不用此表。
FIXED_WHITESPACE_PX: dict[str, int] = {
    "none": 0,
    "small": 64,
    "medium": 128,
    "large": 256,
}

#: auto 模式下各题型的留白高度（px）。
AUTO_WHITESPACE_PX: dict[str, int] = {
    "choice": 48,
    "judgment": 40,
    "fill": 72,
    "solution": 200,
}

#: 解答题每多一个小问增加的留白（px）与上限。
SOLUTION_EXTRA_PER_PART_PX = 80
SOLUTION_MAX_PX = 480

#: 单题留白 override 的合法范围（px）。
OVERRIDE_MIN_PX = 0
OVERRIDE_MAX_PX = 480

#: 一张组卷最多题目数（防误操作一次拉入整库）。
MAX_ITEMS = 50

#: 配图对象键形态（同 figure_crop.py 的键纪律）：只验形态，不验存在性。
FIGURE_KEY_RE = re.compile(r"^figures/[^/\s]+/p\d+_\d+\.png$")

_OPTION_MARK = re.compile(r"(?:^|[\s\n])\s*([A-D])\s*[.．:：]|[(（]([A-D])[)）]")
_JUDGE_MARK = re.compile(r"判断|对错|正误|是否正确|true\s*/\s*false", re.IGNORECASE)
_FILL_MARK = re.compile(r"_{3,}|（\s*）|\(\s+\)|\[\s*\]|填空")
_PART_FULL = re.compile(r"（\s*(\d{1,2})\s*）")
_PART_HALF = re.compile(r"(?:^|[\n。；;：:？?！!]\s*)\(\s*(\d{1,2})\s*\)")


def detect_question_kind(text: str) -> str:
    """按题干文字推断题型；无法识别时按解答题处理。"""
    letters = {
        m.group(1) or m.group(2)
        for m in _OPTION_MARK.finditer(text)
        if m.group(1) or m.group(2)
    }
    if len(letters) >= 2:
        return "choice"
    if _JUDGE_MARK.search(text):
        return "judgment"
    if _FILL_MARK.search(text):
        return "fill"
    return "solution"


def count_question_parts(text: str) -> int:
    """统计题干中的小问数量，至少为 1。"""
    numbers = {m.group(1) for m in _PART_FULL.finditer(text)}
    numbers |= {m.group(1) for m in _PART_HALF.finditer(text)}
    return max(1, len(numbers))


def whitespace_px_for(
    mode: str, question_text: str, override: Optional[int] = None
) -> int:
    """一道题下方的留白高度（px）：单题 override 优先于模式。"""
    if override is not None:
        return override
    if mode != "auto":
        return FIXED_WHITESPACE_PX[mode]
    kind = detect_question_kind(question_text)
    if kind != "solution":
        return AUTO_WHITESPACE_PX[kind]
    extra = (count_question_parts(question_text) - 1) * SOLUTION_EXTRA_PER_PART_PX
    return min(SOLUTION_MAX_PX, AUTO_WHITESPACE_PX["solution"] + extra)


# ── 规格校验 ───────────────────────────────────────────────────────────────


@dataclass
class SheetIssue:
    field: str
    code: str
    message: str


@dataclass
class SheetCheck:
    passed: bool
    issues: list[SheetIssue] = field(default_factory=list)


def validate_exam_sheet_spec(spec: object) -> list[SheetIssue]:
    """校验组卷规格的结构（不查库）：id/title/items/留白/配图键。"""
    issues: list[SheetIssue] = []
    if not isinstance(spec, dict):
        return [SheetIssue("", "not_an_object", "spec must be an object")]
    spec_id = spec.get("id")
    if not isinstance(spec_id, str) or not spec_id.strip():
        issues.append(SheetIssue("id", "missing_id", "id must be a non-empty string"))
    title = spec.get("title")
    if not isinstance(title, str) or not title.strip():
        issues.append(
            SheetIssue("title", "missing_title", "title must be a non-empty string")
        )
    mode = spec.get("whitespace", "auto")
    if mode not in WHITESPACE_MODES:
        issues.append(
            SheetIssue(
                "whitespace",
                "bad_whitespace_mode",
                f"whitespace must be one of {', '.join(WHITESPACE_MODES)}",
            )
        )
    if "include_answer_page" in spec and not isinstance(
        spec["include_answer_page"], bool
    ):
        issues.append(
            SheetIssue(
                "include_answer_page",
                "not_a_bool",
                "include_answer_page must be a boolean",
            )
        )
    items = spec.get("items")
    if not isinstance(items, list) or not items:
        issues.append(
            SheetIssue("items", "empty_items", "items must be a non-empty list")
        )
        return issues
    if len(items) > MAX_ITEMS:
        issues.append(
            SheetIssue(
                "items", "too_many_items", f"at most {MAX_ITEMS} items per sheet"
            )
        )
    seen: set[str] = set()
    for idx, item in enumerate(items):
        field = f"items[{idx}]"
        if not isinstance(item, dict):
            issues.append(SheetIssue(field, "not_an_object", "item must be an object"))
            continue
        wq_id = item.get("wrong_question_id")
        if not isinstance(wq_id, str) or not wq_id.strip():
            issues.append(
                SheetIssue(
                    f"{field}.wrong_question_id",
                    "missing_question",
                    "wrong_question_id must be a non-empty string",
                )
            )
        elif wq_id in seen:
            issues.append(
                SheetIssue(
                    f"{field}.wrong_question_id",
                    "duplicate_question",
                    f"wrong_question_id {wq_id!r} appears more than once",
                )
            )
        else:
            seen.add(wq_id)
        override = item.get("whitespace_px")
        if override is not None and (
            not isinstance(override, int)
            or isinstance(override, bool)
            or not OVERRIDE_MIN_PX <= override <= OVERRIDE_MAX_PX
        ):
            issues.append(
                SheetIssue(
                    f"{field}.whitespace_px",
                    "whitespace_out_of_range",
                    f"whitespace_px must be an int in "
                    f"[{OVERRIDE_MIN_PX}, {OVERRIDE_MAX_PX}]",
                )
            )
        figure_key = item.get("figure_key")
        if figure_key is not None and (
            not isinstance(figure_key, str) or not FIGURE_KEY_RE.match(figure_key)
        ):
            issues.append(
                SheetIssue(
                    f"{field}.figure_key",
                    "bad_figure_key",
                    "figure_key must look like figures/<doc>/p<page>_<n>.png",
                )
            )
    return issues


# ── 拼装 ───────────────────────────────────────────────────────────────────


def assemble_exam_sheet(
    spec: Mapping[str, Any],
    owned_items: Sequence[Mapping[str, Any]],
    attempt_stats: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> tuple[Optional[dict[str, Any]], list[SheetIssue]]:
    """确定性拼装：只接受属于该学生的已存在错题，逐条列原因失败。

    owned_items 是路由从库里按 student_id 取回的错题行快照
    （id/subject/question_text/correct_answer）；attempt_stats 是
    {wrong_question_id: {attempts, last_is_correct, last_answered_at}}。
    返回 (assembled, issues)：issues 非空时 assembled 为 None。
    """
    issues = validate_exam_sheet_spec(spec)
    if issues:
        return None, issues
    owned = {str(item["id"]): item for item in owned_items}
    stats = attempt_stats or {}
    mode = spec.get("whitespace", "auto")
    include_answers = bool(spec.get("include_answer_page", False))
    questions: list[dict[str, Any]] = []
    answer_key: list[dict[str, Any]] = []
    unanswered: list[int] = []
    for number, item in enumerate(spec["items"], start=1):
        wq_id = str(item["wrong_question_id"])
        row = owned.get(wq_id)
        if row is None:
            issues.append(
                SheetIssue(
                    f"items[{number - 1}].wrong_question_id",
                    "question_not_owned",
                    f"wrong question {wq_id!r} does not exist or "
                    "does not belong to this student",
                )
            )
            continue
        stem = row.get("question_text") or ""
        answer = row.get("correct_answer")
        answer_text = answer if isinstance(answer, str) and answer.strip() else None
        stat = stats.get(wq_id, {})
        questions.append(
            {
                "number": number,
                "wrong_question_id": wq_id,
                "subject": row.get("subject"),
                "question_text": stem,
                "correct_answer": answer_text,
                "whitespace_px": whitespace_px_for(
                    mode, stem, item.get("whitespace_px")
                ),
                "figure_key": item.get("figure_key"),
                "attempts": int(stat.get("attempts", 0)),
                "last_is_correct": stat.get("last_is_correct"),
                "last_answered_at": stat.get("last_answered_at"),
            }
        )
        if include_answers:
            if answer_text is not None:
                answer_key.append(
                    {
                        "number": number,
                        "wrong_question_id": wq_id,
                        "answer": answer_text,
                    }
                )
            else:
                unanswered.append(number)
    if issues:
        return None, issues
    return {
        "id": spec["id"],
        "student_id": spec.get("student_id"),
        "title": spec["title"],
        "whitespace_mode": mode,
        "include_answer_page": include_answers,
        "questions": questions,
        "answer_key": answer_key if include_answers else [],
        "unanswered": unanswered if include_answers else [],
    }, []


# ── HTML 打印导出（自包含，不依赖外部资源） ───────────────────────────────

_EXAM_SHEET_CSS = """
.exam-sheet { max-width: 210mm; margin: 0 auto; padding: 16px; color: #111; background: #fff; font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; line-height: 1.6; }
.exam-sheet h1 { text-align: center; font-size: 22px; margin: 0 0 8px; }
.exam-sheet .exam-meta { text-align: center; font-size: 14px; color: #444; margin-bottom: 20px; }
.exam-sheet .exam-question { break-inside: avoid; page-break-inside: avoid; padding: 12px 0; border-bottom: 1px dashed #ccc; }
.exam-sheet .exam-question-head { font-weight: 600; }
.exam-sheet .exam-stem { white-space: pre-wrap; margin: 6px 0; }
.exam-sheet .exam-figure { font-size: 12px; color: #666; margin: 6px 0; }
.exam-sheet .exam-answer-space { border-bottom: 1px dotted #ddd; }
.exam-sheet .exam-answer-key { break-before: page; page-break-before: always; padding-top: 8px; }
.exam-sheet .exam-answer-key h2 { text-align: center; font-size: 18px; margin: 0 0 12px; }
@media print { .exam-sheet { padding: 0; max-width: none; } @page { size: A4; margin: 15mm; } }
"""


def _esc(value: Optional[str]) -> str:
    return _html.escape(value or "", quote=True)


def render_sheet_html(assembled: Mapping[str, Any]) -> str:
    """渲染自包含打印 HTML：题目 + 留白 + 可选答案页（新页）。"""
    parts: list[str] = []
    parts.append(f"<h1>{_esc(str(assembled['title']))}</h1>")
    parts.append(
        f"<div class=\"exam-meta\">共 {len(assembled['questions'])} 题"
        f" · 留白模式 {_esc(str(assembled['whitespace_mode']))}</div>"
    )
    for q in assembled["questions"]:
        stem = _esc(str(q["question_text"]))
        figure = (
            f"<div class=\"exam-figure\">配图：{_esc(str(q['figure_key']))}</div>"
            if q.get("figure_key")
            else ""
        )
        parts.append(
            f"<div class=\"exam-question\">"
            f"<div class=\"exam-question-head\">{q['number']}. "
            f"{_esc(str(q.get('subject') or ''))}</div>"
            f"<div class=\"exam-stem\">{stem}</div>"
            f"{figure}"
            f"<div class=\"exam-answer-space\" "
            f"style=\"min-height:{int(q['whitespace_px'])}px\"></div>"
            f"</div>"
        )
    if assembled.get("include_answer_page"):
        parts.append("<div class=\"exam-answer-key\"><h2>答案页</h2>")
        for entry in assembled.get("answer_key", []):
            parts.append(
                f"<p><b>{entry['number']}.</b> {_esc(str(entry['answer']))}</p>"
            )
        if assembled.get("unanswered"):
            missing = "、".join(str(n) for n in assembled["unanswered"])
            parts.append(f"<p>以下题号未收录答案，留空：{missing}</p>")
        if not assembled.get("answer_key") and not assembled.get("unanswered"):
            parts.append("<p>本题卷暂无收录答案。</p>")
        parts.append("</div>")
    body = "\n".join(parts)
    return (
        "<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<title>{_esc(str(assembled['title']))}</title>\n"
        f"<style>body {{ margin: 0; background: #fff; }}{_EXAM_SHEET_CSS}</style>\n"
        "</head>\n<body>\n"
        f"<div class=\"exam-sheet\">\n{body}\n</div>\n"
        "</body>\n</html>\n"
    )


def sheet_file_name(title: str, suffix: str) -> str:
    """下载文件名：去掉文件系统不允许的字符，截断到 80 字。"""
    stem = re.sub(r'[\\/:*?"<>|\s]+', "_", title).strip("_")[:80]
    return f"{stem or 'exam-sheet'}.{suffix}"


# ── DOCX 导出（只用 stdlib：zipfile + 手写 OOXML） ────────────────────────


def _docx_paragraph(
    text: str, *, bold: bool = False, size: Optional[int] = None,
    spacing_after_twips: Optional[int] = None, page_break: bool = False,
) -> str:
    props = ""
    if spacing_after_twips is not None or size is not None:
        spacing = (
            f"<w:spacing w:after=\"{spacing_after_twips}\" w:line=\"240\" "
            f"w:lineRule=\"auto\"/>"
            if spacing_after_twips is not None
            else ""
        )
        props = f"<w:pPr>{spacing}</w:pPr>"
    run_props = ""
    if bold or size is not None:
        b = "<w:b/>" if bold else ""
        sz = f"<w:sz w:val=\"{size}\"/>" if size is not None else ""
        run_props = f"<w:rPr>{b}{sz}</w:rPr>"
    br = "<w:br w:type=\"page\"/>" if page_break else ""
    return (
        f"<w:p>{props}<w:r>{run_props}"
        f"<w:t xml:space=\"preserve\">{_xml_escape(text)}</w:t>{br}</w:r></w:p>"
    )


def render_sheet_docx(assembled: Mapping[str, Any]) -> bytes:
    """渲染最小合法 DOCX：标题/题干/留白空段/答案页；配图只写 caption。

    留白用空段的段后间距承载（1px ≈ 15 twips，96dpi 换算）。
    不新增任何依赖；桌面 Word 真机打开未验（见嫁接文档未验证项）。
    """
    paras: list[str] = []
    paras.append(_docx_paragraph(str(assembled["title"]), bold=True, size=44))
    paras.append(
        _docx_paragraph(
            f"共 {len(assembled['questions'])} 题 · "
            f"留白模式 {assembled['whitespace_mode']}"
        )
    )
    for q in assembled["questions"]:
        paras.append(
            _docx_paragraph(
                f"{q['number']}. {q.get('subject') or ''}", bold=True
            )
        )
        for line in str(q["question_text"]).split("\n"):
            paras.append(_docx_paragraph(line))
        if q.get("figure_key"):
            paras.append(_docx_paragraph(f"配图：{q['figure_key']}"))
        paras.append(
            _docx_paragraph("", spacing_after_twips=int(q["whitespace_px"]) * 15)
        )
    if assembled.get("include_answer_page"):
        paras.append(_docx_paragraph("答案页", bold=True, size=36, page_break=True))
        for entry in assembled.get("answer_key", []):
            paras.append(
                _docx_paragraph(f"{entry['number']}. {entry['answer']}")
            )
        if assembled.get("unanswered"):
            missing = "、".join(str(n) for n in assembled["unanswered"])
            paras.append(_docx_paragraph(f"以下题号未收录答案，留空：{missing}"))
        if not assembled.get("answer_key") and not assembled.get("unanswered"):
            paras.append(_docx_paragraph("本题卷暂无收录答案。"))
    document_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
        "<w:body>"
        + "".join(paras)
        + "</w:body></w:document>"
    )
    content_types = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">"
        "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>"
        "<Default Extension=\"xml\" ContentType=\"application/xml\"/>"
        "<Override PartName=\"/word/document.xml\" "
        "ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>"
        "</Types>"
    )
    rels = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">"
        "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" "
        "Target=\"word/document.xml\"/>"
        "</Relationships>"
    )
    styles = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        "<w:styles xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
        "<w:docDefaults><w:rPrDefault><w:rPr>"
        "<w:rFonts w:ascii=\"Calibri\" w:hAnsi=\"Calibri\" w:cs=\"Calibri\"/>"
        "<w:sz w:val=\"22\"/>"
        "</w:rPr></w:rPrDefault></w:docDefaults>"
        "</w:styles>"
    )
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in (
            ("[Content_Types].xml", content_types),
            ("_rels/.rels", rels),
            ("word/document.xml", document_xml),
            ("word/styles.xml", styles),
        ):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data.encode("utf-8"))
    return buf.getvalue()


# ── 作答统计与结果回填（需 DB：由路由传入会话） ─────────────────────────


class SheetResultsError(Exception):
    """回填校验失败：status 为 409（重复）或 422（结构/归属问题）。"""

    def __init__(self, status: int, issues: list[SheetIssue]) -> None:
        super().__init__(f"sheet results rejected ({status})")
        self.status = status
        self.issues = issues


async def sheet_attempt_stats(
    db: Any, student_id: Any, wrong_question_ids: Sequence[str]
) -> dict[str, dict[str, Any]]:
    """每道错题的组卷作答统计（attempts/最近结果/最近时间）。"""
    from sqlalchemy import func, select

    from services.models import ExamSheet, ExamSheetResult

    ids = [str(wq_id) for wq_id in wrong_question_ids]
    if not ids:
        return {}
    parsed = []
    for wq_id in ids:
        try:
            parsed.append(uuid.UUID(wq_id))
        except ValueError:
            continue
    if not parsed:
        return {}
    rows = (
        await db.execute(
            select(
                ExamSheetResult.wrong_question_id,
                func.count(ExamSheetResult.id),
            )
            .join(ExamSheet, ExamSheet.id == ExamSheetResult.sheet_id)
            .where(
                ExamSheet.student_id == student_id,
                ExamSheetResult.wrong_question_id.in_(parsed),
            )
            .group_by(ExamSheetResult.wrong_question_id)
        )
    ).all()
    latest = (
        await db.execute(
            select(
                ExamSheetResult.wrong_question_id,
                ExamSheetResult.is_correct,
                ExamSheetResult.answered_at,
            )
            .join(ExamSheet, ExamSheet.id == ExamSheetResult.sheet_id)
            .where(
                ExamSheet.student_id == student_id,
                ExamSheetResult.wrong_question_id.in_(parsed),
            )
            .order_by(
                ExamSheetResult.wrong_question_id,
                ExamSheetResult.answered_at.desc(),
            )
            .distinct(ExamSheetResult.wrong_question_id)
        )
    ).all()
    stats: dict[str, dict[str, Any]] = {
        wq_id: {"attempts": 0, "last_is_correct": None, "last_answered_at": None}
        for wq_id in ids
    }
    for wq_id, count in rows:
        stats[str(wq_id)]["attempts"] = int(count)
    for wq_id, is_correct, answered_at in latest:
        stats[str(wq_id)]["last_is_correct"] = is_correct
        stats[str(wq_id)]["last_answered_at"] = (
            answered_at.isoformat() if answered_at else None
        )
    return stats


async def apply_sheet_results(
    db: Any,
    sheet: Any,
    student_id: Any,
    results: object,
    now: datetime,
) -> list[dict[str, Any]]:
    """回填组卷结果：只追加 QuestionRecord + FSRS 排期，不写掌握度。

    sheet 是已验归属的 ExamSheet 行；results 是
    [{wrong_question_id, is_correct, seconds?}]。全部校验通过后才写；
    同一题已回填过 → 409；题不在本卷/原题已删除 → 422。调用方提交。
    """
    from sqlalchemy import select

    from services.models import ExamSheetResult, QuestionRecord, WrongQuestion
    from services.wrongbook_review_service import schedule_after_answer

    if not isinstance(results, list) or not results:
        raise SheetResultsError(
            422, [SheetIssue("results", "empty_results", "results must be a non-empty list")]
        )
    sheet_items = {
        str(q["wrong_question_id"]) for q in sheet.spec.get("questions", [])
    }
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    issues: list[SheetIssue] = []
    for idx, entry in enumerate(results):
        field = f"results[{idx}]"
        if not isinstance(entry, dict):
            issues.append(SheetIssue(field, "not_an_object", "result must be an object"))
            continue
        wq_id = entry.get("wrong_question_id")
        if not isinstance(wq_id, str) or not wq_id.strip():
            issues.append(
                SheetIssue(
                    f"{field}.wrong_question_id",
                    "missing_question",
                    "wrong_question_id must be a non-empty string",
                )
            )
            continue
        if wq_id in seen:
            issues.append(
                SheetIssue(
                    f"{field}.wrong_question_id",
                    "duplicate_result",
                    f"wrong_question_id {wq_id!r} appears more than once",
                )
            )
            continue
        seen.add(wq_id)
        if wq_id not in sheet_items:
            issues.append(
                SheetIssue(
                    f"{field}.wrong_question_id",
                    "question_not_in_sheet",
                    f"wrong_question_id {wq_id!r} is not an item of this sheet",
                )
            )
            continue
        is_correct = entry.get("is_correct")
        if type(is_correct) is not bool:
            issues.append(
                SheetIssue(
                    f"{field}.is_correct",
                    "not_a_bool",
                    "is_correct must be a boolean",
                )
            )
            continue
        seconds = entry.get("seconds")
        if seconds is not None and (
            not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 0
        ):
            issues.append(
                SheetIssue(
                    f"{field}.seconds",
                    "bad_seconds",
                    "seconds must be a non-negative int",
                )
            )
            continue
        parsed.append(
            {"wrong_question_id": wq_id, "is_correct": is_correct, "seconds": seconds}
        )
    if issues:
        raise SheetResultsError(422, issues)

    existing = (
        await db.execute(
            select(ExamSheetResult.wrong_question_id).where(
                ExamSheetResult.sheet_id == sheet.id,
                ExamSheetResult.wrong_question_id.in_(
                    [uuid.UUID(p["wrong_question_id"]) for p in parsed]
                ),
            )
        )
    ).scalars().all()
    if existing:
        raise SheetResultsError(
            409,
            [
                SheetIssue(
                    "results",
                    "already_recorded",
                    "already recorded for this sheet: "
                    + ", ".join(sorted(str(wq_id) for wq_id in existing)),
                )
            ],
        )

    recorded: list[dict[str, Any]] = []
    for entry in parsed:
        wq_id = uuid.UUID(entry["wrong_question_id"])
        wq = await db.get(WrongQuestion, wq_id)
        if wq is None or wq.student_id != student_id:
            raise SheetResultsError(
                422,
                [
                    SheetIssue(
                        "results",
                        "question_not_owned",
                        f"wrong question {entry['wrong_question_id']!r} "
                        "does not exist or does not belong to this student",
                    )
                ],
            )
        seconds = entry["seconds"]
        db.add(
            QuestionRecord(
                student_id=student_id,
                source="exam_sheet",
                subject=wq.subject,
                question_text=wq.question_text,
                correct_answer=wq.correct_answer,
                is_correct=entry["is_correct"],
                grader="sheet",
                duration_ms=seconds * 1000 if seconds is not None else None,
                wrong_question_id=wq_id,
                meta={
                    "solution": "exam_sheet",
                    "sheet_id": sheet.id,
                },
            )
        )
        # 只排期（FSRS），不写 BKT 掌握度：掌握裁决仍走既有证据链。
        schedule_after_answer(
            wq, is_correct=entry["is_correct"], struggled=False, now=now
        )
        db.add(
            ExamSheetResult(
                sheet_id=sheet.id,
                wrong_question_id=wq_id,
                is_correct=entry["is_correct"],
                seconds=seconds,
                answered_at=now,
            )
        )
        recorded.append(
            {
                "wrong_question_id": entry["wrong_question_id"],
                "is_correct": entry["is_correct"],
                "seconds": seconds,
            }
        )
    return recorded
