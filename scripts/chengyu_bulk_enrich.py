"""
成语批量补全脚本
- 客观字段（感情色彩/适用对象/谦敬辞）严格以词典为准
- 生成字段（易错点/正反例/易混辨析）LLM补充
- --all 模式自动跑完所有批次，自动抽查，质量异常才停

用法:
  python3 scripts/chengyu_bulk_enrich.py            # dry-run 第一批100条
  python3 scripts/chengyu_bulk_enrich.py --execute  # 写库（第一批）
  python3 scripts/chengyu_bulk_enrich.py --execute --batch 2
  python3 scripts/chengyu_bulk_enrich.py --execute --all  # 跑完所有批次
  python3 scripts/chengyu_bulk_enrich.py --retry-failed   # 重试失败条目
"""
import asyncio
import json
import os
import sys
import time
import asyncpg
import urllib.request

DB_URL  = "postgresql://postgres:postgres@localhost:5433/mneme"
DS_KEY  = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DS_KEY")
DS_URL  = "https://api.deepseek.com/chat/completions"
FAILED_LOG = "/tmp/chengyu_enrich_failed.json"

BATCH_SIZE = 100

if not DS_KEY:
    # fallback: read from .env in project root
    env_path = os.path.join(os.path.dirname(__file__), "../.env")
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if line.startswith("DEEPSEEK_API_KEY="):
                DS_KEY = line.split("=", 1)[1].strip()
                break

PROMPT = """你是高考语文成语专家，以下规则必须严格遵守。

对成语"{idiom}"返回JSON。

【感情色彩——必须以《现代汉语词典》第7版词典标注为准】
- 词典标明褒义才填"褒义"，标明贬义才填"贬义"
- 词典未明确标注的，填"中性"——不要自行判断
- 有古今义差异/存在学界争议的，填"中性"并在dispute_note说明
  例：空穴来风 → 中性，dispute_note说明"本义有根据/今多用于无根据"
  例：不求甚解 → 中性，dispute_note说明"本义褒义（读书领会精神），今多贬义"

【适用对象——必须有词典明确限制才写】
- 词典注明"只用于女子""专指书籍"等才写
- 没有明确词典限制→填"不限"
- 绝对禁止写"只能用于否定句/肯定句"这类句法限制

【谦敬辞——词典有标注才填】
- 词典注明谦辞才填"谦辞"，注明敬辞才填"敬辞"
- 其余填"无"

【易错点——只写真实高频考点，无则null】
- 格式："学生常误以为____，实际____"
- 没有典型高频误用 → 填null，不硬凑

【典故——不确定填"出处待考"，不编造】

返回JSON（所有字段必须存在）：
{{
  "idiom": "{idiom}",
  "pinyin": "带声调拼音（如 chā qiáng rén yì）",
  "key_morpheme": "最易误解的关键字义（无则null）",
  "definition": "词典权威释义，20字以内",
  "sentiment": "褒义|贬义|中性",
  "dispute_note": "古今义争议说明（无则null）",
  "target": "适用对象（词典有限制才写，否则填不限）",
  "respect_type": "谦辞|敬辞|无",
  "error_point": "高频误用说明（学生常误以为...实际...），或null",
  "correct_example": "正确用法例句，25字以内",
  "wrong_example": "错误用法例句+括号说明，或null",
  "confusable": [{{"idiom": "易混成语", "diff": "一句话区别"}}],
  "origin": "典故出处（不确定填出处待考）",
  "exam_tip": "高考最常考的陷阱，一句话（若无特殊陷阱填null）"
}}"""


def extract_idiom_name(name: str) -> str:
    parts = [p.strip() for p in name.split("·")]
    if len(parts) >= 3 and parts[1] == "成语":
        return parts[2]
    if len(parts) >= 2 and parts[0] == "成语":
        return parts[1]
    if len(parts) >= 2:
        return parts[0]
    return name.strip()


def call_deepseek(idiom: str) -> dict | None:
    if not DS_KEY:
        print("  ✗ DEEPSEEK_API_KEY not set", file=sys.stderr)
        return None
    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": PROMPT.format(idiom=idiom)}],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 800,
    }).encode()
    req = urllib.request.Request(
        DS_URL, data=payload,
        headers={"Authorization": f"Bearer {DS_KEY}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            data = json.loads(resp.read())
            return json.loads(data["choices"][0]["message"]["content"])
    except Exception as e:
        print(f"  ✗ API error: {e}", file=sys.stderr)
        return None


def auto_quality_check(sample: list[dict], batch: int) -> bool:
    """Auto quality check on 20% sample. Returns False = STOP."""
    total = len(sample)
    if total == 0:
        return True

    issues = []

    # Hard stop: absolute syntactic restrictions
    forbidden = ["只能用于否定句", "只能用于肯定句", "只用于否定", "只用于肯定"]
    for rc in sample:
        for field in ["error_point", "exam_tip", "target"]:
            val = rc.get(field) or ""
            for f in forbidden:
                if f in val:
                    issues.append(f"⛔ STOP [{rc.get('idiom')}] {field}: 含禁止句法限制 '{f}'")

    if issues:
        print("\n".join(issues))
        return False  # hard stop

    # Soft warnings
    sentiments = [rc.get("sentiment", "中性") for rc in sample]
    zhongxing = sentiments.count("中性")
    buyizhongxing = [s for s in sentiments if s != "中性"]
    if total > 5 and zhongxing / total < 0.25:
        print(f"  ⚠️  批次{batch} WARN: 中性比例仅 {zhongxing}/{total}={zhongxing/total:.0%}，感情色彩可能过度标注")
        print(f"       非中性: {buyizhongxing}")

    has_error = sum(1 for rc in sample if rc.get("error_point"))
    if total > 5 and has_error / total > 0.75:
        print(f"  ⚠️  批次{batch} WARN: 易错点比例 {has_error}/{total}={has_error/total:.0%}，可能硬凑")

    print(f"  ✓  批次{batch} 质量检查通过 (中性{zhongxing}/{total}, 有易错点{has_error}/{total})")
    return True


def print_sample(enriched: list, batch: int) -> list[dict]:
    """Print 20% sample, return the sample list for auto-check."""
    check_every = 5
    sample = []
    print(f"\n{'='*60}")
    print(f"=== 批次{batch} 考点字段抽查（每{check_every}条取1条）===")
    print(f"{'='*60}")
    for idx, (_, idiom, rc) in enumerate(enriched):
        if (idx + 1) % check_every != 0:
            continue
        sample.append(rc)
        dispute = rc.get("dispute_note")
        print(f"\n── {idiom} ──")
        print(f"  感情色彩: {rc.get('sentiment','?')}  谦敬辞: {rc.get('respect_type','?')}  对象: {rc.get('target','?')}")
        if dispute:
            print(f"  ⚠️ 争议注: {dispute}")
        print(f"  易错点: {rc.get('error_point') or '（无）'}")
        print(f"  高考陷阱: {rc.get('exam_tip') or '（无）'}")
    return sample


def load_failed_log() -> list[str]:
    if os.path.exists(FAILED_LOG):
        return json.load(open(FAILED_LOG))
    return []


def save_failed_log(failed: list[str]):
    existing = load_failed_log()
    merged = list(dict.fromkeys(existing + failed))  # deduplicate, preserve order
    json.dump(merged, open(FAILED_LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    if merged:
        print(f"  ↳ 失败条目已记录到 {FAILED_LOG} ({len(merged)} 条)")


async def run_batch(conn, batch: int, dry_run: bool, force_offset: int | None = None) -> tuple[list, list]:
    # In --all mode, force_offset=0 so each call gets the next unprocessed rows
    # (each successful write removes rows from the eligible set)
    offset = force_offset if force_offset is not None else (batch - 1) * BATCH_SIZE

    rows = await conn.fetch("""
        SELECT id, name, rich_content
        FROM knowledge_units
        WHERE ku_type = 'chengyu'
          AND (rich_content IS NULL OR NOT rich_content ? 'pinyin')
          AND (rich_content->>'source_type' = '课内' OR rich_content IS NULL)
        ORDER BY name
        LIMIT $1 OFFSET $2
    """, BATCH_SIZE, offset)

    total_pending = await conn.fetchval("""
        SELECT COUNT(*) FROM knowledge_units
        WHERE ku_type='chengyu'
          AND (rich_content IS NULL OR NOT rich_content ? 'pinyin')
          AND (rich_content->>'source_type' = '课内' OR rich_content IS NULL)
    """)

    print(f"\n=== 批次 {batch}：第 {offset+1}–{offset+len(rows)} 条 / 共 {total_pending} 条待补全 ===")
    print(f"模式: {'DRY-RUN' if dry_run else '写库'}")

    enriched = []
    failed = []

    for i, row in enumerate(rows, 1):
        idiom = extract_idiom_name(row["name"])
        print(f"  [{i:03d}/{len(rows)}] {idiom}...", flush=True)
        rc = call_deepseek(idiom)
        if rc is None:
            failed.append(idiom)
            time.sleep(1)
            continue
        time.sleep(0.3)

        existing = json.loads(row["rich_content"]) if row["rich_content"] else {}
        existing.update(rc)
        enriched.append((row["id"], idiom, existing))

        if not dry_run:
            await conn.execute(
                "UPDATE knowledge_units SET rich_content=$1 WHERE id=$2",
                json.dumps(existing, ensure_ascii=False), row["id"],
            )

    return enriched, failed


async def run_retry_failed(dry_run: bool):
    failed_idioms = load_failed_log()
    if not failed_idioms:
        print("没有失败条目。")
        return
    print(f"重试 {len(failed_idioms)} 条失败成语...")
    conn = await asyncpg.connect(DB_URL)
    retried_ok = []
    still_failed = []
    for idiom in failed_idioms:
        print(f"  重试: {idiom}...", flush=True)
        row = await conn.fetchrow(
            "SELECT id, rich_content FROM knowledge_units WHERE ku_type='chengyu' AND name=$1 LIMIT 1",
            idiom,
        )
        if not row:
            # try name·X format
            row = await conn.fetchrow(
                "SELECT id, rich_content FROM knowledge_units WHERE ku_type='chengyu' AND name LIKE $1 LIMIT 1",
                f"%{idiom}%",
            )
        if not row:
            print(f"    ✗ 数据库中找不到: {idiom}")
            still_failed.append(idiom)
            continue
        rc = call_deepseek(idiom)
        if rc is None:
            still_failed.append(idiom)
            time.sleep(1)
            continue
        existing = json.loads(row["rich_content"]) if row["rich_content"] else {}
        existing.update(rc)
        if not dry_run:
            await conn.execute(
                "UPDATE knowledge_units SET rich_content=$1 WHERE id=$2",
                json.dumps(existing, ensure_ascii=False), row["id"],
            )
        retried_ok.append(idiom)
        time.sleep(0.3)
    await conn.close()
    # Update failed log
    json.dump(still_failed, open(FAILED_LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n重试结果: 成功={len(retried_ok)} 仍失败={len(still_failed)}")
    if retried_ok:
        print(f"  成功: {retried_ok}")


async def run(batch: int = 1, dry_run: bool = True, run_all: bool = False):
    conn = await asyncpg.connect(DB_URL)

    if run_all:
        # Calculate total batches
        total_pending = await conn.fetchval("""
            SELECT COUNT(*) FROM knowledge_units
            WHERE ku_type='chengyu'
              AND (rich_content IS NULL OR NOT rich_content ? 'pinyin')
              AND (rich_content->>'source_type' = '课内' OR rich_content IS NULL)
        """)
        import math
        total_batches = math.ceil(total_pending / BATCH_SIZE)
        print(f"共 {total_pending} 条待补全，分 {total_batches} 批次")
        all_failed = []
        all_enriched_count = 0
        all_dispute = 0
        all_has_error = 0

        for b in range(1, total_batches + 1):
            enriched, failed = await run_batch(conn, b, dry_run, force_offset=0)
            sample = print_sample(enriched, b)
            ok = auto_quality_check(sample, b)
            if not ok:
                await conn.close()
                print(f"\n⛔ 批次{b}质量检查不通过，停止。请人工确认后继续。")
                save_failed_log(all_failed)
                return
            all_failed.extend(failed)
            all_enriched_count += len(enriched)
            all_dispute += sum(1 for _, _, rc in enriched if rc.get("dispute_note"))
            all_has_error += sum(1 for _, _, rc in enriched if rc.get("error_point"))
            print(f"  → 批次{b} 完成: 成功={len(enriched)} 失败={len(failed)}")
            if failed:
                save_failed_log(failed)
            time.sleep(2)  # brief pause between batches

        await conn.close()
        print(f"\n{'='*60}")
        print("✅ 全部批次完成")
        print(f"  共补全:      {all_enriched_count} 条")
        print(f"  有易错点:    {all_has_error} 条 ({all_has_error/max(all_enriched_count,1):.0%})")
        print(f"  古今义争议:  {all_dispute} 条")
        all_failed_total = load_failed_log()
        print(f"  API失败(待重试): {len(all_failed_total)} 条 → {FAILED_LOG}")
    else:
        enriched, failed = await run_batch(conn, batch, dry_run)
        await conn.close()
        sample = print_sample(enriched, batch)
        auto_quality_check(sample, batch)
        print(f"\n{'='*60}")
        print(f"结果: 成功={len(enriched)} 失败={len(failed)}")
        if failed:
            print(f"失败列表: {failed}")
            save_failed_log(failed)
        if dry_run:
            print("传 --execute 正式写库")
        else:
            print(f"✅ 批次{batch}写库完成")


if __name__ == "__main__":
    if "--retry-failed" in sys.argv:
        dry = "--execute" not in sys.argv
        asyncio.run(run_retry_failed(dry_run=dry))
    else:
        dry = "--execute" not in sys.argv
        run_all = "--all" in sys.argv
        batch_arg = 1
        if "--batch" in sys.argv:
            idx = sys.argv.index("--batch")
            batch_arg = int(sys.argv[idx + 1])
        asyncio.run(run(batch=batch_arg, dry_run=dry, run_all=run_all))
