"""
成语批量补全脚本（改进版）
- 客观字段（感情色彩/适用对象/谦敬辞）严格以词典为准
- 生成字段（易错点/正反例/易混辨析）LLM补充
- 分批运行，每批导出考点字段供人工抽查(20%)

用法:
  python3 scripts/chengyu_bulk_enrich.py            # dry-run 第一批100条
  python3 scripts/chengyu_bulk_enrich.py --execute  # 写库
  python3 scripts/chengyu_bulk_enrich.py --batch 2  # 第二批(offset=100)
  python3 scripts/chengyu_bulk_enrich.py --execute --batch 2
  python3 scripts/chengyu_bulk_enrich.py --batch 3  # 第三批(offset=200)
"""
import asyncio, json, sys, time
import asyncpg
import urllib.request

DB_URL  = "postgresql://postgres:postgres@localhost:5433/mneme"
DS_KEY  = "sk-b3f05c1f0e32484daee698170181f9ac"
DS_URL  = "https://api.deepseek.com/chat/completions"

BATCH_SIZE = 100

# ── 改进版 prompt：客观字段词典准，生成字段LLM补 ─────────────────────
PROMPT = """你是高考语文成语专家，以下规则必须严格遵守。

对成语"{idiom}"返回JSON。

【感情色彩——必须以《现代汉语词典》第7版词典标注为准】
- 词典标明褒义才填"褒义"，标明贬义才填"贬义"
- 词典未明确标注的，填"中性"——不要自行判断
- 有古今义差异/存在学界争议的，填"中性"并在dispute_note说明
  例：空穴来风 → 中性，dispute_note说明"本义有根据/今多用于无根据"

【适用对象——必须有词典明确限制才写】
- 词典注明"只用于女子""专指书籍"等才写
- 没有明确词典限制→填"不限"
- 不写"只能用于否定句/肯定句"这类句法限制

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

async def run(batch: int = 1, dry_run: bool = True):
    conn = await asyncpg.connect(DB_URL)
    offset = (batch - 1) * BATCH_SIZE

    # 取待补全的课内成语（无pinyin的）
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

    print(f"=== 批次 {batch}：第 {offset+1}–{offset+len(rows)} 条 / 共 {total_pending} 条待补全 ===")
    print(f"模式: {'DRY-RUN' if dry_run else '写库'}")
    print()

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

        # 保留已有字段（如source_type/sources）
        existing = json.loads(row["rich_content"]) if row["rich_content"] else {}
        existing.update(rc)
        enriched.append((row["id"], idiom, existing))

        if not dry_run:
            await conn.execute(
                "UPDATE knowledge_units SET rich_content=$1 WHERE id=$2",
                json.dumps(existing, ensure_ascii=False), row["id"],
            )

    await conn.close()

    # ── 输出考点字段（供20%抽查）──────────────────────────────────────
    check_every = 5  # 每5条打印1条 = 20%抽查
    print(f"\n{'='*60}")
    print(f"=== 考点字段抽查（每{check_every}条取1条，共{len(enriched)//check_every}条）===")
    print(f"{'='*60}")
    for idx, (_, idiom, rc) in enumerate(enriched):
        if (idx + 1) % check_every != 0:
            continue
        dispute = rc.get("dispute_note")
        print(f"\n── {idiom} ──")
        print(f"  感情色彩: {rc.get('sentiment','?')}  谦敬辞: {rc.get('respect_type','?')}  对象: {rc.get('target','?')}")
        if dispute:
            print(f"  ⚠️ 争议注: {dispute}")
        print(f"  易错点: {rc.get('error_point') or '（无）'}")
        print(f"  高考陷阱: {rc.get('exam_tip') or '（无）'}")

    print(f"\n{'='*60}")
    print(f"结果: 成功={len(enriched)} 失败={len(failed)}")
    if failed:
        print(f"失败列表: {failed}")
    if dry_run:
        print("传 --execute 正式写库")
    else:
        print(f"✅ 批次{batch}写库完成")

if __name__ == "__main__":
    dry = "--execute" not in sys.argv
    batch_arg = 1
    if "--batch" in sys.argv:
        idx = sys.argv.index("--batch")
        batch_arg = int(sys.argv[idx + 1])
    asyncio.run(run(batch=batch_arg, dry_run=dry))
