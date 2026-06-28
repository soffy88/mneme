#!/usr/bin/env python3
"""
物理 KU 批量提取 + 入库（全 9 本）。

用法：
  DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/mneme \
  DEEPSEEK_API_KEY=... \
  .venv/bin/python scripts/extract_physics_ku_batch.py [options]

  --books BX1,BX2,...  只跑指定本册 tb_id 后缀（逗号分隔）；默认全部
  --dry-run            只打印，不入库
  --limit N            每本只跑前 N 章（调试用）

物理 ku_type（6类）：
  physical_concept / physical_law / physical_model /
  experiment / method / formula
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

try:
    import fitz
except ImportError:
    sys.exit("缺少 pymupdf: pip install pymupdf")
try:
    import asyncpg
except ImportError:
    sys.exit("缺少 asyncpg: pip install asyncpg")
try:
    import httpx
except ImportError:
    sys.exit("缺少 httpx: pip install httpx")

# ── 配置 ──────────────────────────────────────────────────────────────────────

PDF_DIR = Path(os.environ.get("PDF_DIR", str(Path(__file__).parent.parent / "curriculum_standards")))
DS_KEY  = os.environ.get("DEEPSEEK_API_KEY", "")
DB_URL  = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5433/mneme")
CHUNK   = 10_000   # 每次 LLM 最大字符；截断时自动减半重试

CATALOG = [
    {
        "tb_id":    "RENJIAO-G8-PHYSICS-S",
        "filename": "M_物理_（根据2022年版课程标准修订）义务教育教科书·物理八年级上册.pdf",
        "title":    "人教版物理八年级上册",
    },
    {
        "tb_id":    "RENJIAO-G8-PHYSICS-X",
        "filename": "M_物理_（根据2022年版课程标准修订）义务教育教科书·物理八年级下册.pdf",
        "title":    "人教版物理八年级下册",
    },
    {
        "tb_id":    "RENJIAO-G9-PHYSICS-QYC",
        "filename": "M_物理_（根据2022年版课程标准修订）义务教育教科书·物理九年级全一册.pdf",
        "title":    "人教版物理九年级全一册",
    },
    {
        "tb_id":    "RENJIAO-G10-PHYSICS-BX1",
        "filename": "H_物理_普通高中教科书·物理必修第一册.pdf",
        "title":    "人教版高中物理必修第一册",
    },
    {
        "tb_id":    "RENJIAO-G10-PHYSICS-BX2",
        "filename": "H_物理_普通高中教科书·物理必修第二册.pdf",
        "title":    "人教版高中物理必修第二册",
    },
    {
        "tb_id":    "RENJIAO-G11-PHYSICS-BX3",
        "filename": "H_物理_普通高中教科书·物理必修第三册.pdf",
        "title":    "人教版高中物理必修第三册",
    },
    {
        "tb_id":    "RENJIAO-G11-PHYSICS-SBX1",
        "filename": "H_物理_普通高中教科书·物理选择性必修第一册.pdf",
        "title":    "人教版高中物理选择性必修第一册",
    },
    {
        "tb_id":    "RENJIAO-G11-PHYSICS-SBX2",
        "filename": "H_物理_普通高中教科书·物理选择性必修第二册.pdf",
        "title":    "人教版高中物理选择性必修第二册",
    },
    {
        "tb_id":    "RENJIAO-G12-PHYSICS-SBX3",
        "filename": "H_物理_普通高中教科书·物理选择性必修第三册.pdf",
        "title":    "人教版高中物理选择性必修第三册",
    },
]

VALID_KU_TYPES = {
    "physical_concept", "physical_law", "physical_model",
    "experiment", "method", "formula",
}

# ── LLM Prompt ────────────────────────────────────────────────────────────────

LLM_SYSTEM = """你是中国K12物理教材知识点（KU）提取专家。

KU（知识单元）定义：教材正文中一个最小可独立掌握/遗忘的知识项。

▌物理 KU 类型（ku_type 必须精确选一）：
  physical_concept  物理概念——定义一个物理量或物理现象
                    （位移、速度、加速度、力、质量、惯性）
  physical_law      物理规律/定律——描述物理量之间的规律性关系
                    （牛顿第一/二/三定律、自由落体规律、运动学方程组）
  physical_model    物理模型——简化现实的理想化模型或典型情景
                    （质点模型、匀变速直线运动、轻绳轻杆、斜面模型）
                    ★ 注意：这是物理解题核心，必须独立识别，不能归入 concept
  experiment        实验探究——一个完整的实验设计与操作
                    （打点计时器测速、探究小车运动规律、验证牛顿第二定律）
                    ★ 注意：教材中每个"实验"章节必须提取为独立 KU
  method            科学思维方法——通用分析方法/技巧
                    （控制变量法、图像法、极限思想、等效替代法、微元法）
  formula           单条计算公式——可独立记忆和使用的公式
                    （v=v₀+at, x=v₀t+½at², F=ma, 合力公式）
                    注：一组公式（运动学方程组）归 physical_law，单条归 formula

▌每个 KU 的字段：
  name           KU 名称（≤25字，精确表达）
  ku_type        上面6类之一（必须准确分类）
  core           核心定义/公式/规律描述（≤80字）
  applicable_conditions  适用条件或限制（物理特有难点，如"仅适用匀变速直线运动"
                         "忽略空气阻力"；无条件则写"无特殊限制"）
  difficulty     0.1–0.9（0.1=理解即可，0.5=需推导练习，0.9=综合应用难）
  prerequisites  前置KU名列表（本册内或跨册，最多4个）
  experiment_meta 仅当 ku_type=experiment 时填写：
    {"purpose":"实验目的","principle":"实验原理","instruments":"主要器材",
     "key_steps":"关键步骤要点","data_method":"数据处理方法"}
    其他类型此字段设为 null

▌KC（知识簇）聚类规则：
  按物理逻辑聚类，每 KC 含 3–8 个 KU，同一 KC 内 KU 相互关联
  KC 名示例："运动学概念体系""牛顿定律与应用""力的分析与合成"

▌规则：
  - 不设数量限制：内容多 KU 多，内容少 KU 少，自然浮动
  - physical_model 和 experiment 必须独立识别，不能混入 concept
  - 适用条件（applicable_conditions）必须填写，是物理 KU 的核心属性
  - 公式变量恢复正常字符（如 狓→x, 犪→a）

输出纯 JSON（无 markdown 代码块）：
{
  "chapter": "章节名",
  "kus": [
    {
      "id": "ku-001",
      "name": "KU名称",
      "ku_type": "physical_concept",
      "core": "核心定义（≤80字）",
      "applicable_conditions": "适用条件",
      "difficulty": 0.4,
      "prerequisites": [],
      "experiment_meta": null
    }
  ],
  "kcs": [
    {"id": "kc-001", "name": "KC名", "logic_reason": "聚类逻辑", "ku_ids": ["ku-001"]}
  ]
}
只输出 JSON，不加任何其他文字。"""


# ── PDF → 章节文本 ────────────────────────────────────────────────────────────

def extract_page_texts(pdf_path: Path) -> dict[int, str]:
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        sys.exit(f"PDF 打开失败: {e}")
    pages: dict[int, str] = {}
    for i in range(doc.page_count):
        t = doc[i].get_text().strip()
        if t:
            pages[i + 1] = t
    doc.close()
    return pages


def split_into_chapters(pages: dict[int, str]) -> list[tuple[str, str]]:
    """
    识别章节边界。
    收集每个章序号的所有候选页，再按章节顺序贪心选取"页码单调递增"的那个，
    过滤掉封面缩略图/TOC 中的误判。
    """
    CHARS = "一二三四五六七八九十"
    # chapter_occurrences: {章序汉字 → [候选页列表]}
    chapter_occurrences: dict[str, list[int]] = {}

    for pg in sorted(pages):
        page_head = pages[pg][:300]
        for line in page_head.split("\n")[:6]:
            line = line.strip()
            m = re.match(r"^第([一二三四五六七八九十]+)章\s*[一-鿿]", line)
            if not m:
                continue
            # 过滤目录行：含点线（···）或该行以纯数字结尾
            if re.search(r"[·…]{2,}|\d+\s*$", line):
                continue
            ch = m.group(1)
            chapter_occurrences.setdefault(ch, []).append(pg)
            break  # 每页只取第一个匹配

    if not chapter_occurrences:
        return [("全册", "\n".join(pages[p] for p in sorted(pages)))]

    # 按章节编号顺序，贪心选取页码单调递增的首个候选
    all_ch = sorted(chapter_occurrences.keys(), key=lambda x: CHARS.find(x) if x in CHARS else 99)
    chapter_starts: dict[str, int] = {}
    prev_pg = 0
    for ch in all_ch:
        valid = [p for p in chapter_occurrences[ch] if p > prev_pg]
        if valid:
            chapter_starts[ch] = valid[0]
            prev_pg = valid[0]

    if not chapter_starts:
        return [("全册", "\n".join(pages[p] for p in sorted(pages)))]

    ordered = sorted(chapter_starts.items(), key=lambda x: x[1])  # 按实际页码排序
    pg_sorted = sorted(pages)
    chapters: list[tuple[str, str]] = []
    for i, (ch, start_pg) in enumerate(ordered):
        end_pg = ordered[i + 1][1] if i + 1 < len(ordered) else max(pages) + 1
        text = "\n".join(pages[p] for p in pg_sorted if start_pg <= p < end_pg)
        if text.strip():
            chapters.append((f"第{ch}章", text))
    return chapters


# ── LLM 调用 ─────────────────────────────────────────────────────────────────

def _call_llm(client: httpx.Client, chapter_name: str, text_chunk: str, part_hint: str) -> dict:
    user = (
        f"{chapter_name}{part_hint} 正文内容（{len(text_chunk)}字符）：\n\n"
        f"{text_chunk}\n\n"
        "请提取所有KU（含物理模型和实验类），聚成KC，标前置依赖和适用条件。"
    )
    max_tok = 8192  # DeepSeek-V3 上限；按实际生成量计费，max 不增加成本
    resp = client.post(
        "https://api.deepseek.com/chat/completions",
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": LLM_SYSTEM},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tok,
            "temperature": 0.1,
        },
        timeout=120,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"].strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw, flags=re.MULTILINE).strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"No JSON object in response ({len(raw)} chars): {raw[:120]}")


def llm_extract(client: httpx.Client, chapter_name: str, text_chunk: str, part_hint: str = "") -> dict:
    """
    调用 LLM 提取 KU；失败重试 1 次；
    若两次都失败，把 chunk 减半，各抽一次并合并结果。
    """
    for attempt in range(2):
        try:
            return _call_llm(client, chapter_name, text_chunk, part_hint)
        except Exception as e:
            print(f"    [LLM 失败 attempt {attempt+1}] {e}", flush=True)
            time.sleep(3)

    # 减半重试
    half = len(text_chunk) // 2
    print(f"    [减半重试] chunk {len(text_chunk)}→{half}+{len(text_chunk)-half}", flush=True)
    merged: dict = {"chapter": chapter_name, "kus": [], "kcs": []}
    kid_offset = 0
    for sub_idx, sub in enumerate([text_chunk[:half], text_chunk[half:]]):
        try:
            sub_hint = f"{part_hint}(减半{sub_idx+1}/2)"
            d = _call_llm(client, chapter_name, sub, sub_hint)
            # 重新编号避免 id 冲突
            for ku in d.get("kus", []):
                old_id = ku.get("id", f"ku-{kid_offset:03d}")
                new_id = f"ku-{kid_offset:03d}"
                ku["id"] = new_id
                # 修正本批次 kcs 中对 old_id 的引用
                for kc in d.get("kcs", []):
                    kc["ku_ids"] = [new_id if k == old_id else k for k in kc.get("ku_ids", [])]
                kid_offset += 1
            merged["kus"].extend(d.get("kus", []))
            merged["kcs"].extend(d.get("kcs", []))
        except Exception as e:
            print(f"    [减半失败] sub{sub_idx+1}: {e}", flush=True)
    return merged


# ── 抽取主循环 ───────────────────────────────────────────────────────────────

def _attach_kcs(kus: list[dict], kcs: list[dict]) -> None:
    ku_kc: dict[str, list[str]] = {}
    for kc in kcs:
        for kid in kc.get("ku_ids", []):
            ku_kc.setdefault(kid, []).append(kc.get("name", ""))
    for ku in kus:
        ku.setdefault("_kcs", ku_kc.get(ku.get("id", ""), []) or ["综合知识"])


def extract_all_kus(
    client: httpx.Client,
    chapters: list[tuple[str, str]],
    limit: int | None = None,
) -> list[dict]:
    all_kus: list[dict] = []
    chapters_to_run = chapters[:limit] if limit else chapters

    for ch_name, ch_text in chapters_to_run:
        if not ch_text.strip():
            continue

        # 切块
        parts: list[str] = []
        if len(ch_text) <= CHUNK:
            parts = [ch_text]
        else:
            n = (len(ch_text) + CHUNK - 1) // CHUNK
            for i in range(n):
                parts.append(ch_text[i * CHUNK: (i + 1) * CHUNK])

        for pi, part in enumerate(parts):
            hint = f"（{pi+1}/{len(parts)}）" if len(parts) > 1 else ""
            print(f"  LLM: {ch_name}{hint} ({len(part)}字)", flush=True)
            data  = llm_extract(client, ch_name, part, hint)
            kus   = data.get("kus", [])
            kcs   = data.get("kcs", [])

            id_to_name = {ku.get("id", ""): ku.get("name", "") for ku in kus}
            _attach_kcs(kus, kcs)
            for ku in kus:
                ku["_chapter"] = ch_name
                kt = ku.get("ku_type", "physical_concept")
                ku["ku_type"] = kt if kt in VALID_KU_TYPES else "physical_concept"
                ku["prerequisites"] = [
                    id_to_name.get(p, p)
                    for p in ku.get("prerequisites", []) if p
                ]
            all_kus.extend(kus)

    return all_kus


def dedup_kus(kus: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for ku in kus:
        key = ku.get("name", "").strip()
        if key and key not in seen:
            seen.add(key)
            out.append(ku)
    return out


# ── 异常检测 ─────────────────────────────────────────────────────────────────

def anomaly_check(tb_id: str, kus: list[dict]) -> bool:
    """返回 True 表示正常，False 表示需要停下。"""
    type_cnt = Counter(ku.get("ku_type") for ku in kus)
    total = len(kus)
    if total == 0:
        print(f"  ⚠️  {tb_id}: 0 KU 抽出，停止批量流程", flush=True)
        return False
    # 高中教材实验类应 ≥ 1
    is_hs = any(x in tb_id for x in ("BX", "SBX"))
    if is_hs and type_cnt.get("experiment", 0) == 0:
        print(f"  ⚠️  {tb_id}: 实验类 KU=0（高中教材异常），停止", flush=True)
        return False
    # 严重集中：>85% 同一类型（通常 concept），说明分类崩了
    if total >= 10:
        max_type_ratio = max(type_cnt.values()) / total
        if max_type_ratio > 0.85:
            dominant = max(type_cnt, key=type_cnt.get)
            print(f"  ⚠️  {tb_id}: {dominant} 占比 {max_type_ratio:.0%}，分类可能崩坏，停止", flush=True)
            return False
    return True


# ── DB 入库 ──────────────────────────────────────────────────────────────────

def pg_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def upsert_cluster(conn: asyncpg.Connection, tb_id: str, kc_name: str, order: int) -> str:
    slug = re.sub(r"[^\w一-鿿]", "-", kc_name)[:40].strip("-").lower()
    kc_id = f"{tb_id}-kc-{slug}"
    await conn.execute(
        """
        INSERT INTO knowledge_clusters (id, textbook_id, name, display_order)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (id) DO NOTHING
        """,
        kc_id, tb_id, kc_name, order,
    )
    return kc_id


async def upsert_ku(conn: asyncpg.Connection, tb_id: str, cluster_id: str, ku: dict) -> None:
    slug = re.sub(r"[^\w一-鿿]", "-", ku["name"])[:40].strip("-").lower()
    ku_id = f"{tb_id}-ku-{slug}"
    diff  = min(max(float(ku.get("difficulty", 0.5)), 0.01), 0.99)
    prereqs = json.dumps(ku.get("prerequisites", []), ensure_ascii=False)
    ku_type = ku.get("ku_type", "physical_concept")

    desc_parts = []
    if ku.get("core"):
        desc_parts.append(ku["core"])
    if ku.get("applicable_conditions") and ku["applicable_conditions"] != "无特殊限制":
        desc_parts.append(f"【适用条件】{ku['applicable_conditions']}")
    if isinstance(ku.get("experiment_meta"), dict):
        em = ku["experiment_meta"]
        desc_parts.append(
            f"【实验】目的：{em.get('purpose','')}；原理：{em.get('principle','')}；"
            f"器材：{em.get('instruments','')}；步骤：{em.get('key_steps','')}；"
            f"数据处理：{em.get('data_method','')}"
        )
    description = "\n".join(desc_parts) or None

    await conn.execute(
        """
        INSERT INTO knowledge_units
          (id, textbook_id, cluster_id, name, description,
           prerequisites, related_kus, difficulty, exam_frequency,
           question_types, ku_type, mastery_levels)
        VALUES ($1,$2,$3,$4,$5,$6,'[]'::jsonb,$7,'mid','[]'::jsonb,$8,'[]'::jsonb)
        ON CONFLICT (id) DO NOTHING
        """,
        ku_id, tb_id, cluster_id,
        ku["name"], description,
        prereqs, diff, ku_type,
    )


async def store_kus(conn: asyncpg.Connection, tb_id: str, kus: list[dict]) -> int:
    kc_map: dict[str, str] = {}
    order = 1
    for ku in kus:
        for kc_name in ku.get("_kcs", []):
            if kc_name not in kc_map:
                kc_map[kc_name] = await upsert_cluster(conn, tb_id, kc_name, order)
                order += 1

    if not kc_map:
        fallback = await upsert_cluster(conn, tb_id, "综合知识", 999)
    else:
        fallback = next(iter(kc_map.values()))

    for ku in kus:
        kc_names = ku.get("_kcs") or ["综合知识"]
        cluster_id = kc_map.get(kc_names[0], fallback)
        await upsert_ku(conn, tb_id, cluster_id, ku)

    return len(kus)


# ── 单本处理 ─────────────────────────────────────────────────────────────────

async def process_book(
    book: dict,
    client: httpx.Client,
    dry_run: bool,
    limit: int | None,
    only_new: bool = False,
) -> int | None:
    """
    处理一本书。返回入库 KU 数；返回 None 表示异常需停止。
    only_new=True 时不打印完整 dry-run，只入库新增 KU（依赖 ON CONFLICT DO NOTHING）。
    """
    tb_id    = book["tb_id"]
    pdf_path = PDF_DIR / book["filename"]
    if not pdf_path.exists():
        print(f"  ❌ PDF 不存在: {pdf_path}", flush=True)
        return None

    print(f"\n{'='*60}", flush=True)
    print(f"→ {book['title']}  [{tb_id}]  ({pdf_path.stat().st_size//1024}KB)", flush=True)

    pages    = extract_page_texts(pdf_path)
    chapters = split_into_chapters(pages)
    total_ch = sum(len(t) for _, t in chapters)
    print(f"  {len(chapters)} 章节, {total_ch} 字符", flush=True)
    for cn, ct in chapters:
        print(f"    {cn}: {len(ct)} 字符", flush=True)

    t0 = time.time()
    kus_raw = extract_all_kus(client, chapters, limit=limit)
    kus     = dedup_kus(kus_raw)
    elapsed = time.time() - t0
    type_cnt = Counter(ku.get("ku_type") for ku in kus)

    print(f"\n  原始 {len(kus_raw)} KU → 去重 {len(kus)} KU  ({elapsed:.0f}s)", flush=True)
    print("  KU类型分布:", flush=True)
    for kt, cnt in sorted(type_cnt.items(), key=lambda x: -x[1]):
        print(f"    {kt:<22}: {cnt}", flush=True)

    # 实验类抽查
    exp_kus = [ku for ku in kus if ku.get("ku_type") == "experiment"]
    if exp_kus:
        sample = exp_kus[0]
        em = sample.get("experiment_meta") or {}
        print(f"  [实验样本] {sample.get('name')}", flush=True)
        print(f"    目的: {em.get('purpose','')[:60]}", flush=True)
        print(f"    器材: {em.get('instruments','')[:60]}", flush=True)

    if not anomaly_check(tb_id, kus):
        return None

    if dry_run:
        print("  [DRY-RUN] 未入库", flush=True)
        return len(kus)

    conn = await asyncpg.connect(pg_dsn(DB_URL))
    try:
        stored = await store_kus(conn, tb_id, kus)
    finally:
        await conn.close()
    print(f"  ✅ 入库完成: {stored} KU", flush=True)
    return stored


# ── 主流程 ────────────────────────────────────────────────────────────────────

async def main(book_filter: list[str], dry_run: bool, limit: int | None) -> None:
    if not DS_KEY:
        sys.exit("未设置 DEEPSEEK_API_KEY")

    # 精确匹配 tb_id 末尾字段（BX1 不误匹配 SBX1）
    def _match(tb_id: str) -> bool:
        suffix = tb_id.split("-")[-1]
        return any(f == suffix or f == tb_id for f in book_filter)

    books = [b for b in CATALOG if not book_filter or _match(b["tb_id"])]
    if not books:
        sys.exit(f"未找到匹配的本册: {book_filter}")

    print(f"待处理 {len(books)} 本物理教材", flush=True)

    client = httpx.Client(
        headers={"Authorization": f"Bearer {DS_KEY}"},
        timeout=120,
    )
    results: list[tuple[str, int | str]] = []
    try:
        for book in books:
            stored = await process_book(book, client, dry_run, limit)
            if stored is None:
                print("\n⛔ 检测到异常，停止批量流程，请检查后手动继续。", flush=True)
                break
            results.append((book["tb_id"], stored))
    finally:
        client.close()

    print(f"\n{'='*60}", flush=True)
    print("汇总:", flush=True)
    for tb_id, cnt in results:
        print(f"  {tb_id:<32}: {cnt} KU", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", type=str, default="", help="本册 tb_id 后缀，逗号分隔（如 BX1,BX2）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="每本只跑前N章")
    args = ap.parse_args()

    book_filter = [x.strip() for x in args.books.split(",") if x.strip()]
    asyncio.run(main(book_filter, args.dry_run, args.limit))
