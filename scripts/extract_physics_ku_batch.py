#!/usr/bin/env python3
"""
物理 KU 批量提取 + 入库。

用法（宿主机，.venv 已含所需包）：
  DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/mneme \\
  DEEPSEEK_API_KEY=... \\
  .venv/bin/python scripts/extract_physics_ku_batch.py [--dry-run] [--limit N]

  --dry-run : 只打印 KU，不入库
  --limit N : 只处理前 N 个章节（调试用）

物理 ku_type（区别于数学）：
  physical_concept  物理概念（位移、加速度、合力）
  physical_law      物理规律/定律（牛顿定律、运动学公式组）
  physical_model    物理模型（质点、匀变速模型、弹簧模型）★物理特有
  experiment        实验探究（测速、验证牛顿第二定律）★物理特有
  method            科学思维方法（控制变量、图像法、极限法）
  formula           计算公式（v=v₀+at、F=ma 单条公式）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
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
CHUNK   = 10_000   # 每次 LLM 最大字符

# 待抽本册（本次只跑一本）
BOOK = {
    "tb_id":    "RENJIAO-G10-PHYSICS-BX1",
    "filename": "H_物理_普通高中教科书·物理必修第一册.pdf",
    "title":    "高中物理必修第一册",
    "grade":    "G10",
    "stage":    "hs",
    "edition":  "RENJIAO",
    "subject":  "physics",
}

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
    CHARS = "一二三四五六七八九十"
    chapter_starts: dict[str, int] = {}
    current: str | None = None
    for pg in sorted(pages):
        m = re.search(r"第([一二三四五六七八九十]+)章", pages[pg])
        if m:
            ch = m.group(1)
            if ch != current:
                current = ch
                chapter_starts.setdefault(ch, pg)

    if not chapter_starts:
        return [("全册", "\n".join(pages[p] for p in sorted(pages)))]

    ordered = sorted(chapter_starts.items(), key=lambda x: CHARS.find(x[0]) if x[0] in CHARS else 99)
    pg_sorted = sorted(pages)
    chapters: list[tuple[str, str]] = []
    for i, (ch, start_pg) in enumerate(ordered):
        end_pg = ordered[i + 1][1] if i + 1 < len(ordered) else max(pages) + 1
        text = "\n".join(pages[p] for p in pg_sorted if start_pg <= p < end_pg)
        chapters.append((f"第{ch}章", text))
    return chapters


# ── LLM 调用 ─────────────────────────────────────────────────────────────────

def llm_extract(client: httpx.Client, chapter_name: str, text_chunk: str, part_hint: str = "") -> dict:
    user = f"""{chapter_name}{part_hint} 正文内容（{len(text_chunk)}字符）：

{text_chunk}

请提取所有KU（含物理模型和实验类），聚成KC，标前置依赖和适用条件。"""
    try:
        resp = client.post(
            "https://api.deepseek.com/chat/completions",
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": LLM_SYSTEM},
                    {"role": "user", "content": user},
                ],
                "max_tokens": 4096,
                "temperature": 0.1,
            },
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception as e:
        print(f"    [LLM 错误] {e}", flush=True)
    return {}


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
        parts = []
        if len(ch_text) <= CHUNK:
            parts = [ch_text]
        else:
            n = (len(ch_text) + CHUNK - 1) // CHUNK
            for i in range(min(n, 5)):
                parts.append(ch_text[i * CHUNK: (i + 1) * CHUNK])

        for pi, part in enumerate(parts):
            hint = f"（{pi+1}/{len(parts)}）" if len(parts) > 1 else ""
            print(f"  LLM: {ch_name}{hint} ({len(part)}字)", flush=True)
            data = llm_extract(client, ch_name, part, hint)
            kus  = data.get("kus", [])
            kcs  = data.get("kcs", [])

            # 把 KC 名写回每个 KU
            ku_kc: dict[str, list[str]] = {}
            for kc in kcs:
                for kid in kc.get("ku_ids", []):
                    ku_kc.setdefault(kid, []).append(kc.get("name", ""))

            # 章内 id→name 映射，用于解析 prerequisites 里的 ku-xxx 引用
            id_to_name = {ku.get("id", ""): ku.get("name", "") for ku in kus}
            for ku in kus:
                ku["_chapter"] = ch_name
                ku["_kcs"] = ku_kc.get(ku.get("id", ""), []) or ["综合知识"]
                kt = ku.get("ku_type", "physical_concept")
                ku["ku_type"] = kt if kt in VALID_KU_TYPES else "physical_concept"
                # 解析 prerequisites 中的章内 ID → 名称
                resolved = []
                for p in ku.get("prerequisites", []):
                    resolved.append(id_to_name.get(p, p))
                ku["prerequisites"] = [r for r in resolved if r]
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


async def upsert_ku(conn: asyncpg.Connection, tb_id: str, cluster_id: str, ku: dict) -> str:
    slug = re.sub(r"[^\w一-鿿]", "-", ku["name"])[:40].strip("-").lower()
    ku_id = f"{tb_id}-ku-{slug}"
    diff  = min(max(float(ku.get("difficulty", 0.5)), 0.01), 0.99)
    prereqs = json.dumps(ku.get("prerequisites", []), ensure_ascii=False)
    ku_type = ku.get("ku_type", "physical_concept")

    # description：core + applicable_conditions + experiment_meta（如有）
    desc_parts = []
    if ku.get("core"):
        desc_parts.append(ku["core"])
    if ku.get("applicable_conditions") and ku["applicable_conditions"] != "无特殊限制":
        desc_parts.append(f"【适用条件】{ku['applicable_conditions']}")
    if ku.get("experiment_meta") and ku["experiment_meta"]:
        em = ku["experiment_meta"]
        if isinstance(em, dict):
            desc_parts.append(
                f"【实验】目的：{em.get('purpose','')}；原理：{em.get('principle','')}；"
                f"器材：{em.get('instruments','')}；步骤：{em.get('key_steps','')}；"
                f"数据处理：{em.get('data_method','')}"
            )
    description = "\n".join(desc_parts) if desc_parts else None

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
    return ku_id


async def store_kus(conn: asyncpg.Connection, tb_id: str, kus: list[dict]) -> int:
    # 建 KC → cluster_id 映射
    kc_map: dict[str, str] = {}
    order = 1
    for ku in kus:
        for kc_name in ku.get("_kcs", []):
            if kc_name not in kc_map:
                kc_id = await upsert_cluster(conn, tb_id, kc_name, order)
                kc_map[kc_name] = kc_id
                order += 1

    fallback = list(kc_map.values())[0] if kc_map else None
    if not fallback:
        # 建一个兜底 cluster
        fallback = await upsert_cluster(conn, tb_id, "综合知识", 999)

    stored = 0
    for ku in kus:
        kc_names = ku.get("_kcs") or ["综合知识"]
        cluster_id = kc_map.get(kc_names[0], fallback)
        await upsert_ku(conn, tb_id, cluster_id, ku)
        stored += 1
    return stored


# ── 干跑报告 ─────────────────────────────────────────────────────────────────

def print_dry_run(kus: list[dict]) -> None:
    from collections import Counter
    type_cnt = Counter(ku.get("ku_type", "?") for ku in kus)
    print(f"\n{'='*60}")
    print(f"  [DRY-RUN] 共 {len(kus)} 个 KU（去重后）")
    print(f"  KU类型分布:")
    for kt, cnt in sorted(type_cnt.items(), key=lambda x: -x[1]):
        print(f"    {kt:<22}: {cnt}")
    print()

    # 每种类型抽 2 个样本
    shown: dict[str, int] = {}
    for ku in kus:
        kt = ku.get("ku_type", "?")
        if shown.get(kt, 0) >= 2:
            continue
        shown[kt] = shown.get(kt, 0) + 1
        print(f"  [{kt}] {ku.get('name','?')}")
        print(f"    core:       {ku.get('core','')[:80]}")
        print(f"    conditions: {ku.get('applicable_conditions','')[:60]}")
        if ku.get("experiment_meta") and isinstance(ku["experiment_meta"], dict):
            em = ku["experiment_meta"]
            print(f"    实验目的:   {em.get('purpose','')[:60]}")
            print(f"    实验原理:   {em.get('principle','')[:60]}")
        print(f"    prereqs:    {ku.get('prerequisites',[])}")
        print(f"    difficulty: {ku.get('difficulty', 0.5)}")
        print()
    print(f"{'='*60}")


# ── 主流程 ────────────────────────────────────────────────────────────────────

async def main(dry_run: bool, limit: int | None) -> None:
    if not DS_KEY:
        sys.exit("未设置 DEEPSEEK_API_KEY")

    tb_id    = BOOK["tb_id"]
    pdf_path = PDF_DIR / BOOK["filename"]
    if not pdf_path.exists():
        sys.exit(f"PDF 不存在: {pdf_path}")

    print(f"→ {BOOK['title']}  ({pdf_path.stat().st_size//1024}KB)", flush=True)

    # 1. PDF → 章节
    pages    = extract_page_texts(pdf_path)
    chapters = split_into_chapters(pages)
    total_chars = sum(len(t) for _, t in chapters)
    print(f"  {len(chapters)} 章节, {total_chars} 字符", flush=True)
    for cn, ct in chapters:
        print(f"    {cn}: {len(ct)} 字符", flush=True)

    # 2. LLM 抽取
    client = httpx.Client(
        headers={"Authorization": f"Bearer {DS_KEY}"},
        timeout=120,
    )
    t0 = time.time()
    try:
        kus_raw = extract_all_kus(client, chapters, limit=limit)
    finally:
        client.close()

    kus = dedup_kus(kus_raw)
    print(f"\n  原始 {len(kus_raw)} KU → 去重 {len(kus)} KU  ({time.time()-t0:.0f}s)", flush=True)

    if dry_run:
        print_dry_run(kus)
        print("[DRY-RUN] 未入库。", flush=True)
        return

    # 3. 入库
    conn = await asyncpg.connect(pg_dsn(DB_URL))
    try:
        stored = await store_kus(conn, tb_id, kus)
    finally:
        await conn.close()

    print(f"\n  ✅ 入库完成: {stored} 个 KU", flush=True)
    from collections import Counter
    type_cnt = Counter(ku.get("ku_type", "?") for ku in kus)
    print("  KU类型分布:")
    for kt, cnt in sorted(type_cnt.items(), key=lambda x: -x[1]):
        print(f"    {kt:<22}: {cnt}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印，不入库")
    ap.add_argument("--limit", type=int, default=None, help="只处理前N个章节")
    args = ap.parse_args()
    asyncio.run(main(dry_run=args.dry_run, limit=args.limit))
