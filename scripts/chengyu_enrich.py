"""
成语防误用内容补全脚本
- 50个优先（含高频易错经典）
- 改进版 prompt：约束感情色彩/适用对象/典故准确性
- 结果写入 knowledge_units.rich_content
"""
import asyncio
import json
import sys
import time
import asyncpg
import urllib.request

DB_URL = "postgresql://postgres:postgres@localhost:5433/mneme"
DEEPSEEK_KEY = "REDACTED_DEEPSEEK_KEY"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"

# ── 高频易错成语（高考必考）优先处理 ──────────────────────────
PRIORITY_IDIOMS = [
    # 用户点名的经典易错
    "差强人意", "不刊之论", "首当其冲", "七月流火", "万人空巷",
    # 感情色彩易错（褒贬反用）
    "炙手可热", "明日黄花", "屡试不爽", "空穴来风", "不以为然",
    "始作俑者", "无所不为", "目无全牛", "登堂入室", "美轮美奂",
    # 适用对象易错（性别/年龄/对象限制）
    "豆蔻年华", "破镜重圆", "相敬如宾", "举案齐眉", "天伦之乐",
    "汗牛充栋", "浩如烟海", "鳞次栉比", "美不胜收", "不孚众望",
    # 谦敬辞易错（自谦误用于他人）
    "抛砖引玉", "鼎力相助", "蓬荜生辉", "敬谢不敏", "不吝赐教",
    # 望文生义高频
    "望其项背", "不以为然", "不省人事", "如坐春风", "相濡以沫",
    "哀鸿遍野", "蹉跎岁月", "叹为观止", "弹冠相庆", "不可理喻",
    # 教材里出现的常见成语（给前面补全收尾）
    "豁然开朗", "锲而不舍", "不可思议", "兴高采烈", "扣人心弦",
]
# 去重保持顺序
seen = set()
PRIORITY_IDIOMS = [x for x in PRIORITY_IDIOMS if not (x in seen or seen.add(x))]
PRIORITY_IDIOMS = PRIORITY_IDIOMS[:50]

PROMPT = """你是高考语文成语专家，参考《现代汉语词典》第7版和《成语大词典》给出权威释义。

请对成语"{idiom}"返回严格JSON，字段说明如下——

【感情色彩规则】
- 只在成语本身（不依赖语境）有明显褒义/贬义时才标褒/贬
- "差强人意"等"勉强满意/基本可以"类 = 中性，不要标褒义
- 有争议或中性的，直接填"中性"

【适用对象规则】
- 只有词典明确限制才写限制（如"豆蔻年华"词典注明指少女）
- 没有明确词典限制的填"不限"，不要自己添加限制
- 不要写"只能用于X句"这类句法限制（那是语法问题不是成语限制）

【易错点规则】
- 必须是真实的、高频的高考考点误用，不是为凑内容编的
- 写法："学生常误认为____，实际上____"
- 如果该成语没有典型误用（如"锲而不舍"误用不常见），填null

【典故规则】
- 必须是真实历史/文献典故，不能改编或编造
- 不确定的典故填"出处待考"，不要猜测

【易混成语规则】
- 只列真正容易混淆的（有实证），不要硬凑
- 区别要说核心，不要废话

返回JSON（所有字段必须有，不能省略）：
{{
  "idiom": "{idiom}",
  "pinyin": "带声调拼音",
  "key_morpheme": "最易误解的关键字/语素含义（若无生僻义填null）",
  "definition": "权威简明释义，20字以内",
  "sentiment": "褒义|贬义|中性",
  "target": "适用对象（词典有明确限制则写，否则填不限）",
  "respect_type": "谦辞|敬辞|无",
  "error_point": "最典型高频误用说明，或null（若无典型误用）",
  "correct_example": "正确用法例句，30字以内",
  "wrong_example": "错误用法例句+括号说明错在哪，或null",
  "confusable": [
    {{"idiom": "易混成语", "diff": "一句话说清区别"}}
  ],
  "origin": "真实典故来源（书名+故事概述，不确定填出处待考）",
  "exam_tip": "高考命题最常考的陷阱，一句话"
}}"""


def call_deepseek(idiom: str) -> dict | None:
    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": PROMPT.format(idiom=idiom)}],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 900,
    }).encode()
    req = urllib.request.Request(
        DEEPSEEK_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_KEY}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            data = json.loads(resp.read())
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
    except Exception as e:
        print(f"  ✗ API error for {idiom}: {e}", file=sys.stderr)
        return None


async def run(limit: int = 50, dry_run: bool = True):
    conn = await asyncpg.connect(DB_URL)

    # 按优先级顺序找成语 ID（每个成语只取一条，已合并过）
    results = []
    not_found = []
    found_ids = set()

    for idiom in PRIORITY_IDIOMS:
        row = await conn.fetchrow(
            """SELECT id, name, rich_content FROM knowledge_units
               WHERE ku_type='chengyu' AND (
                 name = $1 OR name LIKE $1 || '·%' OR name LIKE '%·' || $1
               )
               LIMIT 1""",
            idiom,
        )
        if row:
            results.append((row["id"], idiom, row["rich_content"]))
            found_ids.add(row["id"])
        else:
            not_found.append(idiom)

    # 补足到 limit 个（取尚未 rich_content 的库内成语）
    if len(results) < limit:
        extras = await conn.fetch(
            """SELECT id, name, rich_content FROM knowledge_units
               WHERE ku_type='chengyu'
               AND (rich_content IS NULL OR rich_content::text = '{}' OR NOT rich_content ? 'pinyin')
               AND id != ALL($1::text[])
               ORDER BY name
               LIMIT $2""",
            list(found_ids),
            limit - len(results),
        )
        for r in extras:
            # 提取干净的成语名
            parts = [p.strip() for p in r["name"].split("·")]
            if len(parts) >= 3 and parts[1] == "成语":
                iname = parts[2]
            elif len(parts) >= 2 and parts[0] == "成语":
                iname = parts[1]
            elif len(parts) >= 2:
                iname = parts[0]
            else:
                iname = r["name"]
            results.append((r["id"], iname, r["rich_content"]))
            found_ids.add(r["id"])

    if not_found:
        print(f"⚠️  数据库中未找到: {not_found}")

    print(f"准备补全 {len(results)} 个成语...")

    enriched = []
    for i, (ku_id, idiom, existing_rc) in enumerate(results, 1):
        print(f"  [{i}/{len(results)}] {idiom}...", flush=True)
        rc_data = call_deepseek(idiom)
        if rc_data is None:
            continue
        time.sleep(0.3)  # 避免 rate limit

        # 合并到已有 rich_content（保留 sources 列表）
        existing = json.loads(existing_rc) if existing_rc else {}
        existing.update(rc_data)
        enriched.append((ku_id, idiom, existing))

        if not dry_run:
            await conn.execute(
                "UPDATE knowledge_units SET rich_content=$1 WHERE id=$2",
                json.dumps(existing, ensure_ascii=False),
                ku_id,
            )

    await conn.close()

    # 输出结果供抽查
    print(f"\n=== 补全结果（{'DRY-RUN' if dry_run else '已写库'}）===")
    for _, idiom, rc in enriched:
        print(f"\n── {idiom} ──")
        print(f"  拼音:     {rc.get('pinyin','')}")
        print(f"  释义:     {rc.get('definition','')}")
        print(f"  感情色彩: {rc.get('sentiment','')}")
        print(f"  适用对象: {rc.get('target','')}")
        print(f"  谦敬辞:   {rc.get('respect_type','')}")
        print(f"  易错点:   {rc.get('error_point','')}")
        print(f"  正例:     {rc.get('correct_example','')}")
        print(f"  反例:     {rc.get('wrong_example','')}")
        confusable = rc.get("confusable", [])
        if confusable:
            for c in confusable:
                print(f"  易混:     {c.get('idiom','')} — {c.get('diff','')}")
        print(f"  典故:     {rc.get('origin','')}")
        print(f"  高考陷阱: {rc.get('exam_tip','')}")

    if dry_run:
        print(f"\n=== DRY-RUN 完毕（共 {len(enriched)} 个）。传 --execute 写库 ===")

    return enriched


if __name__ == "__main__":
    dry = "--execute" not in sys.argv
    asyncio.run(run(limit=50, dry_run=dry))
