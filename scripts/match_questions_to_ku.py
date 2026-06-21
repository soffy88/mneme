#!/usr/bin/env python3
"""
CMM-Math题目 → 人教版教材KU 匹配脚本（本地 Ollama qwen2.5:7b，4并发）。

用法:
  docker run --rm --network host \\
    -v ~/projects/mneme/scripts:/app/scripts \\
    -e DATABASE_URL=postgresql://postgres:postgres@localhost:5433/mneme \\
    -e OLLAMA_URL=http://localhost:11434 \\
    -e DEEPSEEK_API_KEY=sk-... \\
    mneme-api:latest python /app/scripts/match_questions_to_ku.py [--dry-run] [--limit N] [--grade G] [--rematched]

参数:
  --dry-run     只打印匹配结果，不写DB
  --limit N     只处理前N条（验证用）
  --grade G     只处理指定年级（如 g7）
  --rematched   同时重匹配已有RENJIAO key的题（默认只处理cmm-math key）
  --concurrency 并发数（默认4）

分层策略:
  G4-G9    本地直接写入（有效命中88-100%）
  G1-G3    写入 + 标记 needs_image_review（图片题<ImageHere>多）
  G10-G12  本地为主，confidence<0.7 → DeepSeek兜底（需 DEEPSEEK_API_KEY）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from typing import Any

try:
    import asyncpg
    import httpx
except ImportError as e:
    sys.exit(f"缺少依赖: {e}")

# ── 配置 ──────────────────────────────────────────────────────────────────────

DB_URL      = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@db:5432/mneme")
OLLAMA_URL  = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
DS_KEY      = os.environ.get("DEEPSEEK_API_KEY", "")

# 高中合并候选池（G10-G12题跨册）
_HS_TB = [
    "renjiao-math-g10-a",
    "RENJIAO-G10-MATH-BX2",
    "RENJIAO-G11-MATH-A-SBX1",
    "RENJIAO-G11-MATH-A-SBX2",
    "RENJIAO-G12-MATH-A-SBX3",
]
GRADE_TB_MAP: dict[str, list[str]] = {
    "g1":  ["RENJIAO-G1-MATH-S", "RENJIAO-G1-MATH-X"],
    "g2":  ["RENJIAO-G2-MATH-S", "RENJIAO-G2-MATH-X"],
    "g3":  ["RENJIAO-G3-MATH-S", "RENJIAO-G3-MATH-X"],
    "g4":  ["RENJIAO-G4-MATH-S", "RENJIAO-G4-MATH-X"],
    "g5":  ["RENJIAO-G5-MATH-S", "RENJIAO-G5-MATH-X"],
    "g6":  ["RENJIAO-G6-MATH-S", "RENJIAO-G6-MATH-X"],
    "g7":  ["RENJIAO-G7-MATH-S", "RENJIAO-G7-MATH-X"],
    "g8":  ["RENJIAO-G8-MATH-S", "RENJIAO-G8-MATH-X"],
    "g9":  ["RENJIAO-G9-MATH-S", "RENJIAO-G9-MATH-X"],
    "g10": _HS_TB,
    "g11": _HS_TB,
    "g12": _HS_TB,
}

LLM_SYSTEM = """你是数学教材知识点（KU）匹配专家。

给定一道数学题目和该年级的候选KU列表，
找出该题考察的1-3个最相关KU。

规则：
- 精确匹配：题目考什么知识点，就选那个KU
- 主考点必选，涉及点（辅助知识）也可选（最多3个）
- 如果候选列表中没有合适的KU，返回空数组（不强行匹配）
- 只看KU名称和描述，不编造新KU

输出纯JSON（不加markdown代码块）：
{
  "matched": [
    {"id": "RENJIAO-G7-MATH-S-ku-...", "name": "KU名", "role": "main|related"},
    ...
  ],
  "confidence": 0.9,
  "reason": "一句话说明匹配依据"
}"""


# ── keyword_filter（核心：命中率0%→97%的关键）────────────────────────────────

def keyword_filter(question: str, kus: list[dict], top_n: int = 40) -> list[dict]:
    """Bigram关键词预筛，从全量KU候选中选出最相关的top_n个。"""
    def tokenize(text: str) -> set[str]:
        clean = re.sub(r'[^一-鿿\w]', ' ', text)
        tokens: set[str] = set()
        for w in clean.split():
            if len(w) >= 2:
                tokens.add(w)
            for i in range(len(w) - 1):
                tokens.add(w[i:i + 2])
        return tokens

    q_tokens = tokenize(question[:400])

    def score(ku: dict) -> int:
        return len(q_tokens & tokenize(f"{ku['name']} {ku.get('description', '')}"))

    return sorted(kus, key=score, reverse=True)[:top_n]


def build_ku_text(kus: list[dict]) -> str:
    lines = []
    for ku in kus:
        desc = (ku.get("description") or "")[:80]
        lines.append(f'- id:"{ku["id"]}" | {ku["name"]} | {desc}')
    return "\n".join(lines)


# ── Ollama 匹配（qwen2.5:7b，format:json）────────────────────────────────────

def ollama_match(client: httpx.Client, question_text: str, grade: str, ku_text: str) -> dict:
    grade_cn = {
        "g1": "一年级", "g2": "二年级", "g3": "三年级", "g4": "四年级",
        "g5": "五年级", "g6": "六年级", "g7": "七年级", "g8": "八年级",
        "g9": "九年级", "g10": "高一", "g11": "高二", "g12": "高三",
    }.get(grade, grade)

    # qwen3.5/gemma4等thinking模型用 think:False；qwen2.5用 format:json
    is_thinking = any(k in OLLAMA_MODEL.lower() for k in ["qwen3", "gemma4"])
    payload: dict[str, Any] = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": LLM_SYSTEM},
            {"role": "user", "content": (
                f"题目（{grade_cn}数学）：\n{question_text[:600]}\n\n"
                f"候选KU列表：\n{ku_text}"
            )},
        ],
        "stream": False,
        "options": {"temperature": 0.05, "num_predict": 800},
    }
    if is_thinking:
        payload["think"] = False
    else:
        payload["format"] = "json"

    t0 = time.time()
    try:
        resp = client.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
        raw = resp.json()["message"]["content"].strip()
        raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            data = json.loads(m.group()) if m else {}
    except Exception as e:
        data = {"error": str(e)[:80]}
    data["_elapsed"] = time.time() - t0
    return data


# ── DeepSeek 兜底（G10-G12 低置信）──────────────────────────────────────────

def deepseek_match(client: httpx.Client, question_text: str, grade: str, ku_text: str) -> dict:
    grade_cn = {
        "g10": "高一", "g11": "高二", "g12": "高三",
    }.get(grade, grade)
    try:
        resp = client.post(
            "https://api.deepseek.com/chat/completions",
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": LLM_SYSTEM},
                    {"role": "user", "content": (
                        f"题目（{grade_cn}数学）：\n{question_text[:800]}\n\n"
                        f"候选KU列表：\n{ku_text}\n\n请匹配1-3个最相关KU，输出JSON。"
                    )},
                ],
                "max_tokens": 800,
                "temperature": 0.05,
            },
            timeout=60,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        return json.loads(m.group()) if m else {}
    except Exception as e:
        return {"error": str(e)[:80]}


# ── 核心：单题处理 ────────────────────────────────────────────────────────────

async def process_one(
    sem: asyncio.Semaphore,
    pool: asyncpg.Pool,
    row: asyncpg.Record,
    ku_cache: dict[str, list[dict]],
    ollama: httpx.Client,
    ds_client: httpx.Client | None,
    dry_run: bool,
    idx: int,
    total: int,
) -> dict:
    async with sem:
        wq_id   = str(row["id"])
        qtxt    = (row["question_text"] or "").strip()
        kp_raw  = row["knowledge_points"]
        kp      = json.loads(kp_raw) if isinstance(kp_raw, str) else (kp_raw or {})

        # 提取年级（优先从knowledge_points的key，其次profiler_analysis）
        grade = _extract_grade(kp, row)
        if not grade:
            print(f"  [{idx}/{total}] ⚠ 无法提取年级 {wq_id[:8]}")
            return {"wq_id": wq_id, "status": "no_grade"}

        kus = ku_cache.get(grade, [])
        if not kus:
            print(f"  [{idx}/{total}] ⚠ {grade}无KU")
            return {"wq_id": wq_id, "status": "no_ku", "grade": grade}

        # 图片题标记
        has_image = "<ImageHere>" in qtxt

        # keyword 预筛 → 40候选
        candidates = keyword_filter(qtxt, kus, top_n=40)
        ku_text = build_ku_text(candidates)

        # Ollama 匹配（在线程里跑同步 httpx）
        result = await asyncio.to_thread(ollama_match, ollama, qtxt, grade, ku_text)
        elapsed = result.pop("_elapsed", 0)
        matched = result.get("matched", [])
        conf    = float(result.get("confidence", 0))
        model_used = OLLAMA_MODEL
        used_ds = False

        # G10-G12 低置信 → DeepSeek 兜底
        is_hs = grade in ("g10", "g11", "g12")
        if is_hs and conf < 0.7 and ds_client is not None:
            ds_result = await asyncio.to_thread(deepseek_match, ds_client, qtxt, grade, ku_text)
            ds_matched = ds_result.get("matched", [])
            if ds_matched:
                matched   = ds_matched
                conf      = float(ds_result.get("confidence", conf))
                model_used = "deepseek"
                used_ds   = True

        # 构建新 knowledge_points {ku_id: ku_name}
        new_kp: dict[str, str] = {}
        for m in matched:
            kid  = m.get("id", "")
            kname = m.get("name", "")
            if kid and kname:
                new_kp[kid] = kname

        # flags
        flags: list[str] = []
        if has_image:
            flags.append("needs_image_review")
        if used_ds:
            flags.append("deepseek_fallback")
        if is_hs and conf < 0.7:
            flags.append("low_confidence")

        meta = {
            "confidence": round(conf, 4),
            "model": model_used,
            "flags": flags,
            "elapsed_s": round(elapsed, 2),
        }

        status_icon = "✅" if new_kp else "❌"
        ds_tag = " [DS]" if used_ds else ""
        img_tag = " [img]" if has_image else ""
        print(f"  [{idx:04d}/{total}] {status_icon} {grade}{ds_tag}{img_tag} "
              f"conf={conf:.2f} {elapsed:.1f}s | "
              f"{list(new_kp.keys())[0][:50] if new_kp else '—'}")

        if not dry_run:
            async with pool.acquire() as conn:
                if new_kp:
                    await conn.execute(
                        """UPDATE wrong_questions
                           SET knowledge_points = $1::jsonb,
                               ku_match_meta    = $2::jsonb
                           WHERE id = $3::uuid""",
                        json.dumps(new_kp, ensure_ascii=False),
                        json.dumps(meta, ensure_ascii=False),
                        wq_id,
                    )
                else:
                    await conn.execute(
                        "UPDATE wrong_questions SET ku_match_meta=$1::jsonb WHERE id=$2::uuid",
                        json.dumps(meta, ensure_ascii=False),
                        wq_id,
                    )

        return {
            "wq_id": wq_id, "grade": grade, "matched": bool(new_kp),
            "confidence": conf, "flags": flags, "model": model_used,
            "new_kus": list(new_kp.keys()), "elapsed": elapsed,
        }


def _extract_grade(kp: dict, row: asyncpg.Record) -> str | None:
    """从knowledge_points key或profiler_analysis提取年级。"""
    # 1. cmm-math-g{N}-xxx
    for key in kp:
        m = re.match(r"cmm-math-(g\d+)-", key)
        if m:
            return m.group(1)
    # 2. RENJIAO-G{N}-... 已匹配的
    for key in kp:
        m = re.match(r"[A-Z]+-G(\d+)-", key)
        if m:
            n = int(m.group(1))
            return f"g{n}"
    # 3. profiler_analysis.grade / level
    pa = row.get("profiler_analysis") or {}
    if isinstance(pa, str):
        try:
            pa = json.loads(pa)
        except Exception:
            pa = {}
    for field in ("grade", "level", "grade_cn"):
        val = pa.get(field, "")
        if val:
            grade_map = {
                "G1": "g1", "G2": "g2", "G3": "g3", "G4": "g4",
                "G5": "g5", "G6": "g6", "G7": "g7", "G8": "g8",
                "G9": "g9", "G10": "g10", "G11": "g11", "G12": "g12",
                "一年级": "g1", "二年级": "g2", "三年级": "g3", "四年级": "g4",
                "五年级": "g5", "六年级": "g6", "七年级": "g7", "八年级": "g8",
                "九年级": "g9", "高一": "g10", "高二": "g11", "高三": "g12",
            }
            normalized = grade_map.get(str(val).strip())
            if normalized:
                return normalized
    return None


# ── 主流程 ────────────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:
    db_url = DB_URL.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(db_url, min_size=4, max_size=8)

    try:
        # 构建 WHERE 条件
        if args.rematched:
            # 重匹配所有（含已有RENJIAO key）— 跳过续跑保护
            kp_filter = "knowledge_points IS NOT NULL AND knowledge_points != '{}'::jsonb"
            resume_clause = ""
        else:
            # 仅处理仍有cmm-math key的；ku_match_meta IS NULL = 未曾处理过（续跑保护）
            kp_filter = "knowledge_points::text LIKE '%cmm-math-%'"
            resume_clause = "AND ku_match_meta IS NULL"

        grade_clause = ""
        if args.grade:
            grade_clause = f"AND knowledge_points::text LIKE '%cmm-math-{args.grade}-%'"

        limit_clause = f"LIMIT {args.limit}" if args.limit else ""

        async with pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT id, question_text, knowledge_points, profiler_analysis
                FROM wrong_questions
                WHERE {kp_filter} {resume_clause} {grade_clause}
                ORDER BY id
                {limit_clause}
            """)
            total = len(rows)
            print(f"待处理: {total} 条题目")
            if total == 0:
                print("无待处理题目，退出。")
                return

            # 缓存所有年级KU
            ku_cache: dict[str, list[dict]] = {}
            for grade, tb_ids in GRADE_TB_MAP.items():
                kus = await conn.fetch(
                    "SELECT id, name, description FROM knowledge_units WHERE textbook_id = ANY($1::text[])",
                    tb_ids,
                )
                ku_cache[grade] = [dict(r) for r in kus]
            total_ku = sum(len(v) for v in ku_cache.values())
            print(f"KU缓存: {total_ku} 条（{len(ku_cache)} 个年级）\n")

        ollama = httpx.Client(timeout=120)
        ds_client: httpx.Client | None = None
        if DS_KEY:
            ds_client = httpx.Client(
                headers={"Authorization": f"Bearer {DS_KEY}"},
                timeout=60,
            )
        elif not args.dry_run:
            print("⚠ 未设置 DEEPSEEK_API_KEY，G10-G12 低置信题目将不做兜底")

        sem = asyncio.Semaphore(args.concurrency)
        t0  = time.time()

        tasks = [
            process_one(sem, pool, row, ku_cache, ollama, ds_client, args.dry_run, i + 1, total)
            for i, row in enumerate(rows)
        ]
        results = await asyncio.gather(*tasks)

        ollama.close()
        if ds_client:
            ds_client.close()
    finally:
        await pool.close()

    # ── 汇总报告 ──────────────────────────────────────────────────────────────
    elapsed_total = time.time() - t0
    ok      = [r for r in results if r.get("matched")]
    fail    = [r for r in results if r.get("status") == "no_grade" or not r.get("matched")]
    img     = [r for r in results if "needs_image_review" in r.get("flags", [])]
    ds_used = [r for r in results if "deepseek_fallback" in r.get("flags", [])]
    low_c   = [r for r in results if "low_confidence" in r.get("flags", [])]

    # 年级细分
    grade_stats: dict[str, dict] = {}
    for r in results:
        g = r.get("grade", "?")
        if g not in grade_stats:
            grade_stats[g] = {"total": 0, "matched": 0}
        grade_stats[g]["total"] += 1
        if r.get("matched"):
            grade_stats[g]["matched"] += 1

    print(f"""
{'='*55}
  全量挂题匹配完工报告
{'='*55}
  总题数      : {total}
  匹配成功    : {len(ok)}/{total}  ({100*len(ok)//max(total,1)}%)
  匹配失败    : {total - len(ok)}
  needs_image_review : {len(img)} 条（图片题，待OCR）
  DeepSeek兜底       : {len(ds_used)} 条（高中低置信）
  仍低置信(<0.7)     : {len(low_c)} 条（DeepSeek也返回低置信）
  耗时        : {elapsed_total:.0f}s  ({elapsed_total/60:.1f}min)
  平均        : {elapsed_total/max(total,1):.2f}s/题

  年级细分:""")
    for g in sorted(grade_stats):
        st = grade_stats[g]
        pct = 100 * st["matched"] // max(st["total"], 1)
        print(f"    {g}: {st['matched']}/{st['total']} ({pct}%)")

    if args.dry_run:
        print("\n[dry-run 模式，未写DB]")

    # 保存完整结果
    out = "/tmp/ku_match_full_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n  完整结果: {out}")
    print('='*55)

    # 抽查：各年级各取1条成功匹配
    print("\n=== 抽查样本（各年级首条成功匹配）===")
    seen_grades: set[str] = set()
    for r in results:
        g = r.get("grade", "?")
        if r.get("matched") and g not in seen_grades:
            seen_grades.add(g)
            print(f"\n  [{g}] conf={r['confidence']:.2f}  flags={r['flags']}")
            for kid in r.get("new_kus", [])[:2]:
                print(f"       → {kid[:70]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",     action="store_true")
    parser.add_argument("--limit",       type=int, default=None)
    parser.add_argument("--grade",       type=str, default=None, help="g1-g12")
    parser.add_argument("--rematched",   action="store_true", help="重匹配已有RENJIAO key的题")
    parser.add_argument("--concurrency", type=int, default=4, help="并发数（默认4）")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
