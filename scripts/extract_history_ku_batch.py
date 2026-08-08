"""extract_history_ku_batch —— 初中历史教材 → 教材主线 KU 入库（P1）。

以中国历史七上/七下/八上/八下（2022 课标人教版）为主线教材，把 PDF 按
"第N课"切分，LLM 抽取每课知识点为教材主线 KU，写入 mneme：
  textbooks（subject=history）→ knowledge_clusters（课，display_order=课序号=chapter_order）
  → knowledge_units（该课知识点 KU：name/core/ku_type/prerequisites/difficulty）

KU 规范承 HISTORY-TEXTBOOK-MAINLINE-CC-SPEC-001 §3（corpus_role=primary 教材主述，
本章节序 chapter_order 驱动每日连载游标）。

用法:
  DEEPSEEK_API_KEY=... DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/mneme \
    .venv/bin/python scripts/extract_history_ku_batch.py [--books G7-S,G7-X,...] [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

PDF_DIR = Path(os.environ.get("PDF_DIR", str(Path(__file__).parent.parent / "curriculum_standards")))
_MNEME_PW = os.environ.get("POSTGRES_PASSWORD", "WmFJJAEtVFknjCDwNmi9bu45cK3mwi4")
DB_URL = os.environ.get(
    "DATABASE_URL",
    f"postgresql+asyncpg://postgres:{_MNEME_PW}@localhost:5433/mneme",
)
DS_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
# LLM 端点: 缺省用 hevi 已验证的 opencode (deepseek-v4-flash, P0 实证稳定)。
_OC_BASE = os.environ.get("OPENCODE_BASE_URL", "")
_OC_KEY = os.environ.get("OPENCODE_API_KEY", "")
_OC_MODEL = os.environ.get("OPENCODE_MODEL", "deepseek-v4-flash")
if not (_OC_BASE and _OC_KEY):
    try:
        _hevi_env = Path("/data/soffy/projects/hevi/.env").read_text()
        for line in _hevi_env.splitlines():
            line = line.strip()
            if line.startswith("OPENCODE_BASE_URL="):
                _OC_BASE = line.split("=", 1)[1]
            elif line.startswith("OPENCODE_API_KEY="):
                _OC_KEY = line.split("=", 1)[1]
            elif line.startswith("OPENCODE_MODEL="):
                _OC_MODEL = line.split("=", 1)[1]
    except Exception:
        pass

try:
    import httpx
except ImportError:
    sys.exit("缺少 httpx: pip install httpx")
try:
    import asyncpg
except ImportError:
    sys.exit("缺少 asyncpg: pip install asyncpg")
try:
    import pymupdf as fitz  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    sys.exit("缺少 pymupdf: pip install pymupdf")

# ── 教材目录（中国历史 4 册主线，P1 先七上验证，D1 决策）──────────────
CATALOG = [
    {
        "tb_id": "TONGBIAN-G7-HISTORY-S",
        "filename": "M_历史_（根据2022年版课程标准修订）义务教育教科书·中国历史七年级上册.pdf",
        "title": "统编版中国历史七年级上册",
        "grade": "G7",
    },
    {
        "tb_id": "TONGBIAN-G7-HISTORY-X",
        "filename": "M_历史_（根据2022年版课程标准修订）义务教育教科书·中国历史七年级下册.pdf",
        "title": "统编版中国历史七年级下册",
        "grade": "G7",
    },
    {
        "tb_id": "TONGBIAN-G8-HISTORY-S",
        "filename": "M_历史_（根据2022年版课程标准修订）义务教育教科书·中国历史八年级上册.pdf",
        "title": "统编版中国历史八年级上册",
        "grade": "G8",
    },
    {
        "tb_id": "TONGBIAN-G8-HISTORY-X",
        "filename": "M_历史_（根据2022年版课程标准修订）义务教育教科书·中国历史八年级下册.pdf",
        "title": "统编版中国历史八年级下册",
        "grade": "G8",
    },
]

VALID_KU_TYPES = {
    "person",          # 人物：身份/事迹/评价
    "event",           # 事件：时间/经过/结果
    "system",          # 制度/政策：内容/作用
    "culture",         # 文化/科技/思想
    "geography",       # 地理/文明遗址
    "causation",       # 因果/影响/意义
    "time",            # 纪年/时期分期
}

LLM_SYSTEM = """你是中国初中历史教材知识点（KU）提取专家。

▌核心原则：
  教材 KU = 从课文中提取的"最小可独立掌握的史实/概念/意义"单元。观点与分期
  以教材主述为准（唯物史观主线），不引入教材外观点。每个知识点单独一个 KU，
  不合并。

▌ku_type（必须精确选一）：
  person      历史人物：身份、主要事迹、历史评价
  event       历史事件：时间、地点、经过、结果
  system      制度/政策/变法：内容、作用、影响
  culture     文化/科技/思想/艺术成就
  geography   地理/遗址/文明分布
  causation   因果/影响/意义/启示
  time        纪年/时代分期/阶段特征

▌输出 JSON 对象：
{"kus": [
  {"name": "知识点名", "core": "核心内容（史实/意义，1-3 句）",
   "ku_type": "event", "prerequisites": ["前导知识点名", ...], "difficulty": 0.3},
  ...
]}

▌规则：
  1. 覆盖本课全部知识点，不遗漏重要人物/事件/制度；
  2. core 用教材表述，含具体时间（如"约公元前2070年"）；
  3. prerequisites 只填本课内或前课已出现的前导概念，不知道留空数组；
  4. difficulty 0.01-0.99，基础识记 0.2-0.4，理解分析 0.5-0.7。
"""


def extract_page_texts(pdf_path: Path) -> dict[int, str]:
    doc = fitz.open(str(pdf_path))
    pages: dict[int, str] = {}
    for i in range(doc.page_count):
        t = doc[i].get_text().strip()
        if t:
            pages[i + 1] = t
    doc.close()
    return pages


def split_into_lessons(pages: dict[int, str]) -> list[tuple[int, str, str]]:
    """按"第N课"切分 → [(课序号, 课标题, 正文)]。

    历史教材页眉是"第N课  标题"（数字序号），首页特征=标题行后紧跟正文。
    贪心单调算法防页眉误判（同语文脚本哲学）。
    """
    lesson_starts: dict[int, int] = {}
    lesson_titles: dict[int, str] = {}
    prev_pg = 0
    for pg in sorted(pages):
        text = pages[pg]
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            continue
        # 标题行："第1课  中国境内早期人类的代表——北京人"（页眉行可能带页码数字）
        m = re.match(r"^第(\d+)课\s+(.+)$", lines[0])
        if m:
            num, title = int(m.group(1)), m.group(2)
            title = re.sub(r"\d+$", "", title).strip()      # 去掉行尾页码
            if num not in lesson_starts or pg > prev_pg:
                lesson_starts[num] = pg
                lesson_titles[num] = title
                prev_pg = pg

    if not lesson_starts:
        return []
    ordered = sorted(lesson_starts.items(), key=lambda x: x[1])
    pg_sorted = sorted(pages)
    lessons: list[tuple[int, str, str]] = []
    for i, (num, start_pg) in enumerate(ordered):
        end_pg = ordered[i + 1][1] if i + 1 < len(ordered) else max(pages) + 1
        body = "\n".join(pages[p] for p in pg_sorted if start_pg <= p < end_pg)
        if body.strip():
            lessons.append((num, lesson_titles[num], body))
    return lessons


def _call_llm(client: httpx.Client, lesson_name: str, text_chunk: str) -> dict:
    user = f"课文「{lesson_name}」正文内容（{len(text_chunk)}字符）：\n\n{text_chunk}\n\n请按规则提取本课全部知识点 KU。"
    url = f"{_OC_BASE}/chat/completions" if _OC_BASE else "https://api.deepseek.com/chat/completions"
    resp = client.post(
        url,
        json={
            "model": _OC_MODEL if _OC_BASE else "deepseek-chat",
            "messages": [
                {"role": "system", "content": LLM_SYSTEM},
                {"role": "user", "content": user},
            ],
            "max_tokens": 16384,
            "temperature": 0.1,
        },
        timeout=300,
    )
    resp.raise_for_status()
    msg = resp.json()["choices"][0]["message"]
    content = (msg.get("content") or "").strip()
    reasoning = (msg.get("reasoning_content") or "").strip()
    # opencode(deepseek-v4-flash) 响应抖动: content 可能是最终 JSON, 也可能被
    # 推理全文占据; content 无 JSON 时取 reasoning_content 提取 (P1 实证)。
    for raw in (content, reasoning):
        if not raw:
            continue
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE).strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                obj = json.loads(m.group())
                if isinstance(obj, dict) and obj.get("kus"):
                    return obj["kus"]
            except json.JSONDecodeError:
                continue
    raise ValueError(f"No JSON in response (content={len(content)}, reasoning={len(reasoning)})")


def dedup_kus(kus: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for ku in kus:
        key = str(ku.get("name", "")).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(ku)
    return out


def pg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def upsert_cluster(conn: asyncpg.Connection, tb_id: str, lesson_name: str, order: int) -> str:
    slug = re.sub(r"[^\w一-鿿]", "-", lesson_name)[:40].strip("-").lower()
    kc_id = f"{tb_id}-kc-{order:02d}-{slug}"
    await conn.execute(
        """
        INSERT INTO knowledge_clusters (id, textbook_id, name, display_order)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (id) DO NOTHING
        """,
        kc_id, tb_id, lesson_name, order,
    )
    return kc_id


async def upsert_ku(conn: asyncpg.Connection, tb_id: str, cluster_id: str, ku: dict) -> None:
    slug = re.sub(r"[^\w一-鿿]", "-", str(ku.get("name", "")))[:40].strip("-").lower()
    ku_id = f"{tb_id}-ku-{slug}"
    diff = min(max(float(ku.get("difficulty", 0.4)), 0.01), 0.99)
    prereqs = json.dumps(ku.get("prerequisites", []), ensure_ascii=False)
    ku_type = ku.get("ku_type", "event")
    if ku_type not in VALID_KU_TYPES:
        ku_type = "event"
    desc = str(ku.get("core") or "")
    await conn.execute(
        """
        INSERT INTO knowledge_units
          (id, textbook_id, cluster_id, name, description,
           prerequisites, related_kus, difficulty, exam_frequency,
           question_types, ku_type, mastery_levels)
        VALUES ($1,$2,$3,$4,$5,$6,'[]'::jsonb,$7,'mid','[]'::jsonb,$8,'[]'::jsonb)
        ON CONFLICT (id) DO NOTHING
        """,
        ku_id, tb_id, cluster_id, ku.get("name"), desc, prereqs, diff, ku_type,
    )


async def upsert_book(conn: asyncpg.Connection, book: dict) -> str:
    await conn.execute(
        """
        INSERT INTO textbooks (id, subject, grade, edition, book_name)
        VALUES ($1, 'history', $2, '统编版2022', $3)
        ON CONFLICT (id) DO NOTHING
        """,
        book["tb_id"], book["grade"], book["title"],
    )
    return book["tb_id"]


_FROM_LESSON: int | None = None


async def process_book(book: dict, client: httpx.Client, dry_run: bool, limit: int | None) -> None:
    tb_id = book["tb_id"]
    pdf = PDF_DIR / book["filename"]
    if not pdf.exists():
        print(f"\n[跳过] {tb_id}: PDF 不存在 ({pdf})", flush=True)
        return
    print(f"\n{'='*60}\n开始: {book['title']} ({tb_id})\nPDF: {pdf.name} ({pdf.stat().st_size//1024} KB)", flush=True)

    pages = extract_page_texts(pdf)
    lessons = split_into_lessons(pages)
    print(f"识别到 {len(lessons)} 课: {[f'{n}课 {t}' for n, t, _ in lessons[:5]]}…", flush=True)
    if not lessons:
        print("  ⚠️  未识别到课节，跳过", flush=True)
        return

    all_kus: list[dict] = []
    if from_lesson := _FROM_LESSON:  # noqa: F821 - 经闭包注入
        lessons = [l for l in lessons if l[0] >= from_lesson]
    if limit:
        lessons = lessons[:limit]
    for order, title, body in lessons:
        kus = []
        for attempt in range(3):
            try:
                kus = _call_llm(client, f"第{order}课 {title}", body)
                break
            except Exception as e:
                print(f"  第{order}课 {title}: 第{attempt + 1}次失败 ({str(e)[:60]}), 重试", flush=True)
                await asyncio.sleep(5)
        if not kus:
            # 分块降级: 长课文分 2 段分别抽, 每段独立 prompt → content 更容易出。
            chunk_len = max(1500, len(body) // 2 + 1)
            chunks = [body[i:i + chunk_len] for i in range(0, len(body), chunk_len)] if len(body) > 2000 else []
            for ci, chunk in enumerate(chunks):
                try:
                    kus += _call_llm(client, f"第{order}课 {title} (段{ci + 1}/{len(chunks)})", chunk)
                except Exception as e:
                    print(f"    分块{ci + 1}也失败: {str(e)[:60]}", flush=True)
            if kus:
                print(f"  第{order}课 {title}: 分块补救 {len(kus)} KU", flush=True)
            else:
                print(f"  ✗ 第{order}课 {title}: LLM 3 次+分块全失败，跳过", flush=True)
                continue
        for ku in kus:
            ku["_order"] = order
        all_kus.extend(kus)
        print(f"  第{order}课 {title}: {len(kus)} KU", flush=True)
        await asyncio.sleep(1.5)  # 限速防触发 deepseek 限流

    all_kus = dedup_kus(all_kus)
    type_cnt = Counter(ku.get("ku_type", "?") for ku in all_kus)
    print(f"共 {len(all_kus)} KU, 类型分布: {dict(type_cnt)}", flush=True)

    if dry_run:
        return

    conn = await asyncpg.connect(pg_dsn(DB_URL))
    try:
        await upsert_book(conn, book)
        # 每课一个 cluster（display_order=课序号=chapter_order）
        per_lesson: dict[int, list[dict]] = {}
        for ku in all_kus:
            per_lesson.setdefault(ku["_order"], []).append(ku)
        for order in sorted(per_lesson):
            lesson_title = next((t for n, t, _ in lessons if n == order), f"第{order}课")
            cluster_id = await upsert_cluster(conn, tb_id, lesson_title, order)
            for ku in per_lesson[order]:
                ku.pop("_order", None)
                await upsert_ku(conn, tb_id, cluster_id, ku)
        print(f"  已入库: {tb_id} ({len(all_kus)} KU)", flush=True)
    finally:
        await conn.close()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--books", default="", help="只跑指定 tb_id 后缀(逗号分隔), 默认全部")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="每本只跑前 N 课")
    parser.add_argument("--from-lesson", type=int, default=None, help="从第 N 课续跑(跳过前 N-1 课)")
    args = parser.parse_args()

    if not (DS_KEY or (_OC_BASE and _OC_KEY)) and not args.dry_run:
        sys.exit("缺少 LLM key (DEEPSEEK_API_KEY 或 OPENCODE_API_KEY)")
    wanted = {s.strip() for s in args.books.split(",") if s.strip()}
    global _FROM_LESSON
    _FROM_LESSON = args.from_lesson
    books = [b for b in CATALOG if not wanted or any(w in b["tb_id"] for w in wanted)]
    if not books:
        sys.exit(f"没有匹配的教材。可用后缀: {[b['tb_id'].split('-')[-1] for b in CATALOG]}")

    _llm_key = _OC_KEY or DS_KEY
    with httpx.Client(headers={"Authorization": f"Bearer {_llm_key}"}) as client:
        for book in books:
            await process_book(book, client, args.dry_run, args.limit)


if __name__ == "__main__":
    asyncio.run(main())
