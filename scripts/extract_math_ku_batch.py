#!/usr/bin/env python3
"""
人教版数学 G1-G12 全量KU批量提取 + 入库。
运行（宿主机，需 pip install pymupdf asyncpg httpx）：
  DEEPSEEK_API_KEY=... DATABASE_URL=... python scripts/extract_math_ku_batch.py
或直接用 docker（已有 pymupdf/asyncpg/httpx）:
  docker run --rm --network mneme_default \\
    -v ~/projects/mneme:/app \\
    -v ~/projects/mneme/curriculum_standards:/data \\
    -e DATABASE_URL=postgresql+asyncpg://... -e DEEPSEEK_API_KEY=... \\
    mneme-api:latest python /app/scripts/extract_math_ku_batch.py

R-1: 单册失败跳过，记录后继续。
R-3: 真实正文抽取，不凑数，不编造。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

# ── 依赖 ──────────────────────────────────────────────────────────────────────
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
try:
    import urllib.request
    import urllib.parse
except ImportError:
    pass  # stdlib

# ── 配置 ──────────────────────────────────────────────────────────────────────

PDF_DIR = Path(os.environ.get("PDF_DIR", "/data"))
DS_KEY  = os.environ.get("DEEPSEEK_API_KEY", "")
DB_URL  = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/mneme")
WORKERS = int(os.environ.get("KU_WORKERS", "2"))   # 并发册数
CHUNK   = 11_000                                    # 每次LLM最大字符

# 映射到 DB 中已有的 textbook stub ID（避免重复建表项）
# 没有对应旧 stub 的用新 ID，已有 stub 的直接复用（ON CONFLICT DO UPDATE edition/name）
EXISTING_TB_MAP: dict[int, str] = {
    1:  "RENJIAO-G1-MATH-S",
    2:  "RENJIAO-G1-MATH-X",
    3:  "RENJIAO-G2-MATH-S",
    4:  "RENJIAO-G2-MATH-X",
    5:  "RENJIAO-G3-MATH-S",
    6:  "RENJIAO-G3-MATH-X",
    7:  "RENJIAO-G4-MATH-S",
    8:  "RENJIAO-G4-MATH-X",
    9:  "RENJIAO-G5-MATH-S",
    10: "RENJIAO-G5-MATH-X",
    11: "RENJIAO-G6-MATH-S",
    12: "RENJIAO-G6-MATH-X",
    13: "RENJIAO-G7-MATH-S",
    # 14: G7下 → 新建 RENJIAO-G7-MATH-X
    15: "RENJIAO-G8-MATH-S",
    # 16: G8下 → 新建 RENJIAO-G8-MATH-X
    # 17: G9上 → 新建 RENJIAO-G9-MATH-S
    18: "RENJIAO-G9-MATH-X",
    19: "renjiao-math-g10-a",  # 新版A版必修一，已有，含5条课标KU
    # 20-23: 高中新版 → 新建
}
NEW_TB_IDS: dict[int, str] = {
    14: "RENJIAO-G7-MATH-X",
    16: "RENJIAO-G8-MATH-X",
    17: "RENJIAO-G9-MATH-S",
    20: "RENJIAO-G10-MATH-A-BX2",
    21: "RENJIAO-G11-MATH-A-SBX1",
    22: "RENJIAO-G11-MATH-A-SBX2",
    23: "RENJIAO-G12-MATH-A-SBX3",
}

CATALOG: list[dict] = [
    # (seq, content_id, title_short, grade, stage, edition)
    {"seq":1,  "cid":"c3e06fe4-c6b3-49cb-8727-4f8ff69bbfbc","title":"数学一年级上册","grade":"G1","stage":"es","edition":"2022修订"},
    {"seq":2,  "cid":"6bf8ae7e-d987-40b4-8fb3-bbb98fcb50b5","title":"数学一年级下册","grade":"G1","stage":"es","edition":"2022修订"},
    {"seq":3,  "cid":"8cfc5a2a-425c-4b9a-a97c-e78d4a4c1e3a","title":"数学二年级上册","grade":"G2","stage":"es","edition":"2022修订"},
    {"seq":4,  "cid":"c1897b18-b302-4e8d-9fd4-40915c4b05c2","title":"数学二年级下册","grade":"G2","stage":"es","edition":"2022修订"},
    {"seq":5,  "cid":"33c8d495-9862-4e19-aab9-61d2af08608a","title":"数学三年级上册","grade":"G3","stage":"es","edition":"2022修订"},
    {"seq":6,  "cid":"8666a8bd-a0e7-49aa-ba07-bf419ceead24","title":"数学三年级下册","grade":"G3","stage":"es","edition":"2022修订"},
    {"seq":7,  "cid":"654e3d1e-c995-4340-81c5-abd7881d835b","title":"数学四年级上册","grade":"G4","stage":"es","edition":"2011"},
    {"seq":8,  "cid":"aa00ab9d-b343-4542-b16d-9c3900b3444b","title":"数学四年级下册","grade":"G4","stage":"es","edition":"2011"},
    {"seq":9,  "cid":"d0d6252f-2233-4f66-9ac9-440638d56fec","title":"数学五年级上册","grade":"G5","stage":"es","edition":"2011"},
    {"seq":10, "cid":"83339b94-2b33-4a9b-ba0e-026b4fdd4f0e","title":"数学五年级下册","grade":"G5","stage":"es","edition":"2011"},
    {"seq":11, "cid":"845136d4-e27b-4e7e-b9a9-00cadf4f9e20","title":"数学六年级上册","grade":"G6","stage":"es","edition":"2011"},
    {"seq":12, "cid":"8e650f4c-e616-4699-ac0a-4911b22e2f2e","title":"数学六年级下册","grade":"G6","stage":"es","edition":"2011"},
    {"seq":13, "cid":"540ac93d-67fc-4353-9e49-1ef20d02b5a4","title":"数学七年级上册","grade":"G7","stage":"ms","edition":"2022修订"},
    {"seq":14, "cid":"81d65033-4cb1-4cf0-ae27-8c367c537c30","title":"数学七年级下册","grade":"G7","stage":"ms","edition":"2022修订"},
    {"seq":15, "cid":"81264e9e-22bc-4289-8389-13b40433b5ba","title":"数学八年级上册","grade":"G8","stage":"ms","edition":"2022修订"},
    {"seq":16, "cid":"e91a6f80-2a9a-4452-a47e-b9ec164156ff","title":"数学八年级下册","grade":"G8","stage":"ms","edition":"2022修订"},
    {"seq":17, "cid":"937a48c1-de81-4cc6-91b2-617cd859de4b","title":"数学九年级上册","grade":"G9","stage":"ms","edition":"2011"},
    {"seq":18, "cid":"ab188631-292c-455e-8082-e09a0ab4001c","title":"数学九年级下册","grade":"G9","stage":"ms","edition":"2011"},
    {"seq":19, "cid":"6e764703-6e5e-4ea3-9462-34652c2678ef","title":"高中数学必修一（A版）","grade":"G10","stage":"hs","edition":"2017修订"},
    {"seq":20, "cid":"d296fc79-8d47-4b18-862c-6df49adc2ce0","title":"高中数学必修二（A版）","grade":"G10","stage":"hs","edition":"2017修订"},
    {"seq":21, "cid":"d0fd2c1f-6b4f-43f0-8229-de0a53b197df","title":"高中数学选择性必修一（A版）","grade":"G11","stage":"hs","edition":"2017修订"},
    {"seq":22, "cid":"99c1fb5b-d1e0-4238-90b9-a573ab84bf08","title":"高中数学选择性必修二（A版）","grade":"G11","stage":"hs","edition":"2017修订"},
    {"seq":23, "cid":"ffaba6c3-497d-47b0-b91a-784f43625507","title":"高中数学选择性必修三（A版）","grade":"G12","stage":"hs","edition":"2017修订"},
]

STAGE_CN = {"es":"小学","ms":"初中","hs":"高中"}

LLM_SYSTEM = """你是中国K12数学教材知识点（KU）提取专家。

KU（知识单元）定义：教材正文中一个最小知识单元：
- 一个黑体/「一般地」/「定义」/「定理」引出的概念或结论
- 一个可独立成题考的公式/法则/方法
- 能独立被学生掌握或单独遗忘的知识项

规则：
- 不设数量限制：内容多KU多，内容少KU少，自然浮动
- 变量字体映射自动还原：狓=x，狔=y，犪=a，犫=b，犮=c，犽=k，犺=h
- KC按知识逻辑聚类（非章节），每KC 3-8个KU
- prerequisites 写KU名字（本册内）或先修知识名（跨册）

输出纯JSON（无markdown代码块）：
{
  "chapter": "章节名",
  "kus": [
    {"id":"ku-001","name":"KU名","core":"核心定义/公式/法则（60字内）",
     "difficulty":0.3,"prerequisites":[]}
  ],
  "kcs": [
    {"id":"kc-001","name":"KC名","logic_reason":"聚类逻辑","ku_ids":["ku-001"]}
  ]
}
只输出JSON，不加任何其他文字。"""


# ── 下载 PDF ──────────────────────────────────────────────────────────────────

def _get_pdf_url(content_id: str) -> str | None:
    try:
        detail_url = f"https://s-file-1.ykt.cbern.com.cn/zxx/ndrv2/resources/tch_material/details/{content_id}.json"
        detail = json.loads(urllib.request.urlopen(detail_url, timeout=15).read())
        for item in detail.get("ti_items", []):
            fmt = item.get("ti_format", "") or item.get("lc_ti_format", "")
            if fmt == "pdf":
                for u in item.get("ti_storages", []):
                    if "r1-ndr-private" in u and u.endswith(".pdf"):
                        return re.sub(
                            r"https?://[^/]+\.ykt\.cbern\.com\.cn/",
                            "https://c1.ykt.cbern.com.cn/",
                            u,
                        )
    except Exception as e:
        print(f"    [get_url ERROR] {e}")
    return None


def download_pdf(content_id: str, out_path: Path) -> bool:
    if out_path.exists() and out_path.stat().st_size > 500_000:
        return True
    url = _get_pdf_url(content_id)
    if not url:
        return False
    encoded = urllib.parse.quote(url, safe=":/?&=#")
    req = urllib.request.Request(
        encoded,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://basic.smartedu.cn/"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(out_path, "wb") as f:
            f.write(r.read())
        return out_path.stat().st_size > 100_000
    except Exception as e:
        print(f"    [download ERROR] {e}")
        return False


# ── PDF → 章节文本 ────────────────────────────────────────────────────────────

def _extract_page_texts(pdf_path: Path) -> dict[int, str]:
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        print(f"    [pdf ERROR] {e}")
        return {}
    pages = {}
    for i in range(doc.page_count):
        t = doc[i].get_text().strip()
        if t:
            pages[i + 1] = t
    doc.close()
    return pages


CHAPTER_CHARS = "一二三四五六七八九十十一十二"


def split_into_chapters(pages: dict[int, str]) -> list[tuple[str, str]]:
    """返回 [(章节名, 拼接正文文本), ...] 章节列表。"""
    # 检测章节切换
    current = None
    chapter_starts: dict[str, int] = {}
    for pg_num in sorted(pages):
        t = pages[pg_num]
        m = re.search(r"第([一二三四五六七八九十]+)章", t)
        if m:
            ch = m.group(1)
            if ch != current:
                current = ch
                if ch not in chapter_starts:
                    chapter_starts[ch] = pg_num

    if not chapter_starts:
        # 无章节标记：整体作为一章
        full = "\n".join(pages[p] for p in sorted(pages))
        return [("全册", full)]

    ordered = sorted(chapter_starts.items(), key=lambda x: CHAPTER_CHARS.find(x[0]) if x[0] in CHAPTER_CHARS else 99)
    pg_sorted = sorted(pages)
    chapters = []
    for i, (ch, start_pg) in enumerate(ordered):
        end_pg = ordered[i + 1][1] if i + 1 < len(ordered) else max(pages) + 1
        text = "\n".join(pages[p] for p in pg_sorted if start_pg <= p < end_pg)
        chapters.append((f"第{ch}章", text))
    return chapters


# ── LLM 调用 ─────────────────────────────────────────────────────────────────

def llm_extract(client: httpx.Client, chapter_name: str, text_chunk: str, part_hint: str = "") -> dict:
    label = f"{chapter_name}{part_hint}"
    user = f"""{label} 正文内容（{len(text_chunk)}字符）：

{text_chunk}

请提取所有KU，聚成KC，标前置依赖。"""
    try:
        resp = client.post(
            "https://api.deepseek.com/chat/completions",
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": LLM_SYSTEM},
                    {"role": "user", "content": user},
                ],
                "max_tokens": 4000,
                "temperature": 0.1,
            },
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        usage = resp.json().get("usage", {})
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return {"data": json.loads(m.group()), "usage": usage}
    except Exception as e:
        print(f"    [llm ERROR] {e}")
    return {"data": {}, "usage": {}}


def extract_volume_kus(client: httpx.Client, chapters: list[tuple[str, str]]) -> list[dict]:
    """按章分段调LLM，收集所有KU原始结果。"""
    all_kus: list[dict] = []
    for ch_name, ch_text in chapters:
        if not ch_text.strip():
            continue
        parts = []
        if len(ch_text) <= CHUNK:
            parts = [ch_text]
        else:
            n = (len(ch_text) + CHUNK - 1) // CHUNK
            for i in range(min(n, 4)):  # 最多4段
                parts.append(ch_text[i * CHUNK: (i + 1) * CHUNK])

        for pi, part in enumerate(parts):
            hint = f"（{pi+1}/{len(parts)}）" if len(parts) > 1 else ""
            result = llm_extract(client, ch_name, part, hint)
            data = result.get("data", {})
            kus = data.get("kus", [])
            kcs = data.get("kcs", [])
            # 用章节前缀重写 KU/KC id 避免跨章冲突
            prefix = re.sub(r"[^一二三四五六七八九十]", "", ch_name)[:2] + str(pi + 1)
            for ku in kus:
                ku["_chapter"] = ch_name
                ku["_kcs"] = []
            for kc in kcs:
                for kid in kc.get("ku_ids", []):
                    for ku in kus:
                        if ku.get("id") == kid:
                            ku["_kcs"].append(kc.get("name", ""))
            all_kus.extend(kus)
    return all_kus


# ── 去重 ─────────────────────────────────────────────────────────────────────

def dedup_kus(kus: list[dict]) -> list[dict]:
    """按 KU 名去重（保留第一次出现）。"""
    seen: set[str] = set()
    out = []
    for ku in kus:
        key = ku.get("name", "").strip()
        if key and key not in seen:
            seen.add(key)
            out.append(ku)
    return out


# ── DB 入库 ──────────────────────────────────────────────────────────────────

def _pg_dsn(db_url: str) -> str:
    return db_url.replace("postgresql+asyncpg://", "postgresql://")


async def upsert_textbook(conn: asyncpg.Connection, vol: dict) -> None:
    seq = vol["seq"]
    tb_id = EXISTING_TB_MAP.get(seq) or NEW_TB_IDS.get(seq) or f"pep-math-{vol['grade'].lower()}-{seq:02d}"
    vol["_tb_id"] = tb_id
    await conn.execute(
        """
        INSERT INTO textbooks (id, subject, grade, edition, book_name)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (id) DO UPDATE
          SET book_name = EXCLUDED.book_name, edition = EXCLUDED.edition
        """,
        tb_id, "数学", vol["grade"], vol["edition"],
        f"人教版·{vol['title']}",
    )


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


async def upsert_ku(
    conn: asyncpg.Connection,
    tb_id: str,
    cluster_id: str,
    ku: dict,
    grade: str,
) -> str:
    slug = re.sub(r"[^\w一-鿿]", "-", ku["name"])[:40].strip("-").lower()
    ku_id = f"{tb_id}-ku-{slug}"
    diff = float(ku.get("difficulty", 0.5))
    prereqs = json.dumps(ku.get("prerequisites", []), ensure_ascii=False)
    await conn.execute(
        """
        INSERT INTO knowledge_units
          (id, textbook_id, cluster_id, name, description,
           prerequisites, related_kus, difficulty, exam_frequency,
           question_types, ku_type, mastery_levels)
        VALUES ($1,$2,$3,$4,$5,$6,'[]'::jsonb,$7,'mid','["short_answer"]'::jsonb,'concept','[]'::jsonb)
        ON CONFLICT (id) DO NOTHING
        """,
        ku_id, tb_id, cluster_id,
        ku["name"], ku.get("core", ""),
        prereqs, min(max(diff, 0.01), 0.99),
    )
    return ku_id


async def db_store_volume(conn: asyncpg.Connection, vol: dict, kus: list[dict]) -> int:
    tb_id = vol["_tb_id"]
    # 按 KC 聚类建 cluster
    kc_name_map: dict[str, str] = {}  # kc_name → cluster_id
    kc_order = 1
    for ku in kus:
        for kc_name in ku.get("_kcs", []) or ["综合知识"]:
            if kc_name not in kc_name_map:
                kc_id = await upsert_cluster(conn, tb_id, kc_name, kc_order)
                kc_name_map[kc_name] = kc_id
                kc_order += 1

    # 插 KU
    stored = 0
    for ku in kus:
        kc_names = ku.get("_kcs", []) or ["综合知识"]
        cluster_id = kc_name_map.get(kc_names[0], list(kc_name_map.values())[0] if kc_name_map else "unknown")
        await upsert_ku(conn, tb_id, cluster_id, ku, vol["grade"])
        stored += 1
    return stored


# ── 单册流程 ─────────────────────────────────────────────────────────────────

async def process_volume(vol: dict, conn: asyncpg.Connection, sem: asyncio.Semaphore) -> dict:
    seq = vol["seq"]
    title = vol["title"]
    grade = vol["grade"]
    t0 = time.time()

    result = {
        "seq": seq, "title": title, "grade": grade,
        "status": "ok", "kus_raw": 0, "kus_stored": 0,
        "elapsed": 0, "error": "",
    }

    async with sem:
        try:
            # 1. 下载 PDF
            pdf_path = PDF_DIR / f"{grade}_{seq:02d}_{title[:15].replace(' ','_')}.pdf"
            print(f"[{seq:02d}/{len(CATALOG)}] {title} → 下载...", flush=True)
            ok = await asyncio.to_thread(download_pdf, vol["cid"], pdf_path)
            if not ok:
                raise RuntimeError("PDF下载失败")

            # 2. 提取文本 → 章节
            pages = await asyncio.to_thread(_extract_page_texts, pdf_path)
            if not pages:
                raise RuntimeError("PDF无文字层")
            chapters = await asyncio.to_thread(split_into_chapters, pages)
            total_chars = sum(len(t) for _, t in chapters)
            print(f"[{seq:02d}] {title}: {len(chapters)}章 {total_chars}字符", flush=True)

            # 3. LLM 抽取
            client = httpx.Client(
                headers={"Authorization": f"Bearer {DS_KEY}"},
                timeout=120,
            )
            try:
                kus_raw = await asyncio.to_thread(extract_volume_kus, client, chapters)
            finally:
                client.close()

            kus_dedup = dedup_kus(kus_raw)
            result["kus_raw"] = len(kus_raw)
            print(f"[{seq:02d}] {title}: {len(kus_raw)}KU原始 → {len(kus_dedup)}KU去重", flush=True)

            # 4. 入库
            await upsert_textbook(conn, vol)
            stored = await db_store_volume(conn, vol, kus_dedup)
            result["kus_stored"] = stored

        except Exception as e:
            result["status"] = "fail"
            result["error"] = str(e)
            print(f"[{seq:02d}] ❌ {title}: {e}", flush=True)

        result["elapsed"] = round(time.time() - t0, 1)
        status_icon = "✅" if result["status"] == "ok" else "❌"
        print(
            f"[{seq:02d}] {status_icon} {title}: "
            f"{result['kus_stored']}KU入库  {result['elapsed']:.0f}s",
            flush=True,
        )
    return result


# ── 清理 CMM-Math 临时KU ─────────────────────────────────────────────────────

async def cleanup_cmm_temp_kus(conn: asyncpg.Connection) -> int:
    """删除 cmm-math-* 临时 KU/KC/教材记录（反推的9年级占位知识点）。"""
    rows = await conn.fetch("SELECT id FROM textbooks WHERE id LIKE 'cmm-math-%'")
    tb_ids = [r["id"] for r in rows]
    if not tb_ids:
        return 0
    # 先删 FK 子记录
    ku_rows = await conn.fetch(
        "DELETE FROM knowledge_units WHERE textbook_id = ANY($1) RETURNING id", tb_ids
    )
    deleted_ku = len(ku_rows)
    await conn.execute("DELETE FROM knowledge_clusters WHERE textbook_id = ANY($1)", tb_ids)
    await conn.execute("DELETE FROM textbooks WHERE id = ANY($1)", tb_ids)
    return deleted_ku


# ── 主入口 ───────────────────────────────────────────────────────────────────

async def main() -> None:
    if not DS_KEY:
        sys.exit("未设置 DEEPSEEK_API_KEY")

    dsn = _pg_dsn(DB_URL)
    conn = await asyncpg.connect(dsn)

    t_start = time.time()
    sem = asyncio.Semaphore(WORKERS)

    # 并发处理所有册
    tasks = [process_volume(vol, conn, sem) for vol in CATALOG]
    results = await asyncio.gather(*tasks)

    # 清理 CMM-Math 临时 KU
    print("\n清理 CMM-Math 临时KU...", flush=True)
    deleted = await cleanup_cmm_temp_kus(conn)
    print(f"已清理: {deleted} 条临时KU", flush=True)

    await conn.close()

    # 生成报告
    ok_results = [r for r in results if r["status"] == "ok"]
    fail_results = [r for r in results if r["status"] != "ok"]
    total_ku = sum(r["kus_stored"] for r in ok_results)
    total_ku_raw = sum(r["kus_raw"] for r in ok_results)
    elapsed = time.time() - t_start

    report_lines = [
        "=" * 72,
        "  人教版数学 G1-G12 KU 批量提取报告",
        "=" * 72,
        f"  完成: {len(ok_results)}/{len(CATALOG)} 册",
        f"  KU入库: {total_ku} 个（原始 {total_ku_raw} → 去重后）",
        f"  CMM临时KU清理: {deleted} 条",
        f"  总耗时: {elapsed/60:.1f} 分钟",
        "",
        "  各册结果:",
    ]
    by_stage: dict[str, list] = {"es": [], "ms": [], "hs": []}
    for r in results:
        icon = "✅" if r["status"] == "ok" else "❌"
        vol = next(v for v in CATALOG if v["seq"] == r["seq"])
        by_stage.setdefault(vol["stage"], []).append(r)
        report_lines.append(
            f"  {icon} [{r['grade']}] {r['title']}: "
            f"{r['kus_stored']}KU  {r['elapsed']:.0f}s"
            + (f"  ← {r['error']}" if r["error"] else "")
        )

    report_lines += [
        "",
        "  学段KU分布:",
        f"    小学(G1-G6): {sum(r['kus_stored'] for r in by_stage.get('es',[]))}" ,
        f"    初中(G7-G9): {sum(r['kus_stored'] for r in by_stage.get('ms',[]))}",
        f"    高中(G10-G12): {sum(r['kus_stored'] for r in by_stage.get('hs',[]))}",
        "",
        "  版本说明:",
        "    G1-G3: 2022年版课程标准修订（平台最新）",
        "    G4-G6: 2011年版（平台未上线2022标准三三制修订版）",
        "    G7-G8: 2022年版课程标准修订（平台最新）",
        "    G9:    2011年版（平台未上线2022修订版）",
        "    G10-G12: 人教A版（2017版2020修订）",
        "",
    ]

    if fail_results:
        report_lines += [
            f"  失败册 ({len(fail_results)} 册):",
            *[f"    [{r['grade']}] {r['title']}: {r['error']}" for r in fail_results],
        ]

    report_lines.append("=" * 72)
    report = "\n".join(report_lines)
    print("\n" + report, flush=True)

    rpt_path = PDF_DIR / "数学KU批量提取报告.txt"
    rpt_path.write_text(report, encoding="utf-8")
    print(f"\n报告: {rpt_path}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
