"""
综合脚本：
1. 清理脏数据（非成语/重复）
2. 修正 name 格式（保留有效但格式乱的成语）
3. 给课内成语打 source_type='课内'
4. 创建高考备考教材/cluster（若不存在）
5. 导入50个高考高频易错成语 + DeepSeek 补全
6. 导出供抽查
"""
import asyncio, json, sys, time, hashlib
import asyncpg
import urllib.request

DB_URL  = "postgresql://postgres:postgres@localhost:5433/mneme"
DS_KEY  = "sk-b3f05c1f0e32484daee698170181f9ac"
DS_URL  = "https://api.deepseek.com/chat/completions"

GAOKAO_TEXTBOOK_ID = "GAOKAO-CHINESE-GAOKAO"
GAOKAO_CLUSTER_ID  = "GAOKAO-CHINESE-GAOKAO-kc-高考高频成语"

# ── 1. 脏数据清单 ──────────────────────────────────────────────

# 删除（非成语）
DELETE_IDS = [
    "TONGBIAN-G10-CHINESE-BXX-ku-一线药物-首选药物-青蒿素",  # 医学术语
    "TONGBIAN-G8-CHINESE-X-ku-社戏--成语-写包票",             # 方言俗语
    "TONGBIAN-G8-CHINESE-X-ku-社戏--成语-自失",               # 单词非成语
    "TONGBIAN-G7-CHINESE-S-ku-杞人忧天--成语",                # 重复条目
]

# 修正 name（有效成语但 name 格式乱）→ (id, new_name)
RENAME_MAP = {
    "TONGBIAN-G8-CHINESE-X-ku-社戏--成语-行云流水":    "行云流水",
    "TONGBIAN-G7-CHINESE-X-ku-说和做--成语-气冲斗牛":  "气冲斗牛",
    "TONGBIAN-G7-CHINESE-X-ku-说和做--成语-兀兀穷年":  "兀兀穷年",
    "TONGBIAN-G7-CHINESE-X-ku-说和做--成语-群蚁排衙":  "群蚁排衙",
    "TONGBIAN-G7-CHINESE-X-ku-说和做--成语-警报迭起":  "警报迭起",
    "TONGBIAN-G7-CHINESE-X-ku-说和做--成语-迥乎不同":  "迥乎不同",
    "TONGBIAN-G7-CHINESE-S-ku-杞人忧天-成语":          "杞人忧天",
}

# ── 2. 50个高考高频易错成语 ────────────────────────────────────

GAOKAO_IDIOMS = [
    # 望文生义（字面义≠真义，高考最高频错误类型）
    "差强人意",     # "差"=稍微，整体=基本满意（非差劲）
    "七月流火",     # 火星下沉天气转凉（非七月天气炎热）
    "首当其冲",     # 首先遭受打击（非带头冲锋）
    "万人空巷",     # 人们走出家门（非空无一人）
    "不刊之论",     # 不可删改=极正确（非不能刊登）
    "炙手可热",     # 权势盛令人畏惧（非热门）
    "明日黄花",     # 过时的事物（非明天的花）
    "不孚众望",     # 不能使众人信服≠不负众望
    "惨淡经营",     # 费尽心力（非生意惨淡）
    "登堂入室",     # 学问由浅入深达高水平（褒义，非"入室"字面）
    "空穴来风",     # 传言有根据（当代争议，高考仍考原义）
    # 褒贬误用（感情色彩搞反）
    "始作俑者",     # 贬义：开创不好风气者
    "无所不为",     # 贬义：什么坏事都干（非万能）
    "弹冠相庆",     # 贬义：坏人得意庆贺
    "亦步亦趋",     # 贬义：跟随模仿，无主见
    "屡试不爽",     # 褒义：屡次试验都没差错（非屡试屡败）
    "叹为观止",     # 褒义：只赞美美好事物
    "无可厚非",     # 中性：没有大过错（非褒义赞扬）
    "哗众取宠",     # 贬义：故意迎合以博眼球
    "侃侃而谈",     # 褒义（谈话理直气壮）≠ 夸夸其谈（贬义）
    # 适用对象误用
    "豆蔻年华",     # 只指13-14岁少女
    "破镜重圆",     # 只用于夫妻分离后重聚
    "相敬如宾",     # 只用于夫妻
    "举案齐眉",     # 只用于夫妻
    "汗牛充栋",     # 只形容书籍多
    "浩如烟海",     # 形容文献资料多（非人多）
    "美轮美奂",     # 形容建筑高大华美
    "如坐春风",     # 受德高望重者的教化（非单纯感受春风）
    "巧夺天工",     # 人工超过自然（不用于自然景物）
    "相濡以沫",     # 困境中互相扶持（非平常的感情深厚）
    # 谦敬辞误用
    "抛砖引玉",     # 谦辞：只能用于自己
    "鼎力相助",     # 敬辞：只能用于对方
    "蓬荜生辉",     # 谦辞：他人到访使寒舍增光
    "敬谢不敏",     # 谦辞：自谦委婉拒绝（非自大）
    "不吝赐教",     # 敬辞：请对方指教
    # 易混淆成语对
    "不以为然",     # 不认为是对的（vs 不以为意=不在乎）
    "哀鸿遍野",     # 流离失所（非哀嚎声）
    "蹉跎岁月",     # 虚度光阴（非艰难困苦）
    "功亏一篑",     # 快成功时因最后一步失败（强调前功尽弃）
    "望其项背",     # 本义=赶得上，常与"难以/不能"连用表追不上
    "沧海一粟",     # 极渺小（非微不足道的努力）
    "应运而生",     # 顺应时势而产生（非刻意创造）
    "不可理喻",     # 贬义：无法讲道理（非形容人聪明）
    "如坐针毡",     # 形容极度不安（不用于正面情绪）
    "大方之家",     # 专指见识广博的人（非"大方"通俗义）
    "春秋笔法",     # 文笔含蓄，暗寓褒贬（非春秋时期）
    "危言危行",     # 褒义：正直的言行（非危险的言行）
    "文不加点",     # 文章一气呵成（"点"=涂改，非标点）
    "不足挂齿",     # 谦辞：不值得提及（non必须自谦用）
    "七嘴八舌",     # 中性：众人同时说话（非褒义团结）
]

assert len(GAOKAO_IDIOMS) == 50, f"需要50个，实际{len(GAOKAO_IDIOMS)}"

# ── DeepSeek prompt（修正版：差强人意=中性，望其项背不绝对化）

PROMPT = """你是高考语文专家，严格以《现代汉语词典》第7版和《汉语成语大词典》的标注为准。

对成语"{idiom}"返回严格JSON，遵守以下规则：

【感情色彩（客观字段，最重要）】
- 必须以词典标注为准，不自行判断
- 词典未明确标褒/贬义的，填"中性"，不要硬标
- 语境化褒贬（靠语境决定褒贬）的成语=中性
- 有"古今义争议"的（如空穴来风），在 dispute_note 字段说明两义

【适用对象（客观字段）】
- 词典有明确使用限制才写（如豆蔻年华=少女；汗牛充栋=书籍）
- 词典无明确限制填"不限"
- 不写"只能用于X句"这类句法限制

【谦敬辞（客观字段）】
- 词典有标注才填谦辞/敬辞，否则填无

【易错点（生成字段）】
- 真实高频高考考点误用，格式"学生常误以为____，实际____"
- 无典型误用填null，不硬凑

【典故】真实，不确定填"出处待考"

返回JSON（所有字段必须存在）：
{{
  "idiom": "{idiom}",
  "pinyin": "带声调拼音",
  "key_morpheme": "最易误解的关键字义，或null",
  "definition": "词典权威释义，20字以内",
  "sentiment": "褒义|贬义|中性",
  "dispute_note": "古今义争议说明（无争议填null）",
  "target": "适用对象（词典有限制才写，否则填不限）",
  "respect_type": "谦辞|敬辞|无",
  "error_point": "高频误用说明，或null",
  "correct_example": "正确例句，30字以内",
  "wrong_example": "错误例句+括号说明，或null",
  "confusable": [{{"idiom":"易混成语","diff":"一句话区别"}}],
  "origin": "真实典故出处，不确定填出处待考",
  "exam_tip": "高考最常考的陷阱，一句话",
  "source_type": "高考必备"
}}"""

# ── 四处人工修正（审核后定值，覆盖 DeepSeek 输出）────────────────
MANUAL_CORRECTIONS: dict[str, dict] = {
    "不以为然": {"sentiment": "中性"},
    "不孚众望": {"sentiment": "中性"},
    "空穴来风": {
        "sentiment": "中性",
        "dispute_note": "本义指有根据（空穴才来风）；今多误用为'毫无根据/无中生有'，两义并存，属古今义争议成语",
        "error_point": "学生常误以为只有'无根据'一义，实际本义为有根据，但当代多用于'无根据'义，属古今义争议",
    },
    "望其项背": {
        "error_point": "学生常误以为该成语本身表示赶不上，实际本义是能看见/赶得上；'难以/不能望其项背'中否定词才表示差距大",
    },
}


def call_deepseek(idiom: str) -> dict | None:
    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": PROMPT.format(idiom=idiom)}],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": 900,
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
        print(f"  ✗ {idiom}: {e}", file=sys.stderr)
        return None


def make_ku_id(idiom: str) -> str:
    slug = idiom.replace("，", "-").replace("、", "-").replace(" ", "-")
    return f"GAOKAO-CHINESE-ku-{slug}"


async def run(dry_run: bool = True):
    conn = await asyncpg.connect(DB_URL)

    # ── Step 1: 清脏数据 ──────────────────────────────────────
    print("=== Step 1: 清理脏数据 ===")
    for did in DELETE_IDS:
        exists = await conn.fetchval("SELECT id FROM knowledge_units WHERE id=$1", did)
        if exists:
            if not dry_run:
                await conn.execute("DELETE FROM knowledge_units WHERE id=$1", did)
            print(f"  {'🗑 DELETE' if not dry_run else '[DRY] DELETE'}: {did}")
        else:
            print(f"  ⚠️  已不存在（跳过）: {did}")

    # ── Step 2: 修正 name ──────────────────────────────────────
    print("\n=== Step 2: 修正脏 name ===")
    for kid, new_name in RENAME_MAP.items():
        exists = await conn.fetchval("SELECT id FROM knowledge_units WHERE id=$1", kid)
        if exists:
            if not dry_run:
                await conn.execute("UPDATE knowledge_units SET name=$1 WHERE id=$2", new_name, kid)
            print(f"  {'✏️  RENAME' if not dry_run else '[DRY] RENAME'}: {kid} → {new_name}")
        else:
            print(f"  ⚠️  已不存在（跳过）: {kid}")

    # ── Step 3: 给已有课内成语打 source_type='课内' ──────────────
    print("\n=== Step 3: 课内成语打标 source_type='课内' ===")
    if not dry_run:
        result = await conn.execute("""
            UPDATE knowledge_units
            SET rich_content = COALESCE(rich_content, '{}') || '{"source_type":"课内"}'::jsonb
            WHERE ku_type='chengyu'
            AND textbook_id != $1
        """, GAOKAO_TEXTBOOK_ID)
        print(f"  ✏️  已更新课内成语: {result}")
    else:
        cnt = await conn.fetchval(
            "SELECT COUNT(*) FROM knowledge_units WHERE ku_type='chengyu' AND textbook_id != $1",
            GAOKAO_TEXTBOOK_ID
        )
        print(f"  [DRY] 将打标 {cnt} 条课内成语")

    # ── Step 4: 建高考教材/cluster（若不存在）─────────────────
    print("\n=== Step 4: 建高考备考教材/cluster ===")
    tb_exists = await conn.fetchval("SELECT id FROM textbooks WHERE id=$1", GAOKAO_TEXTBOOK_ID)
    if not tb_exists:
        if not dry_run:
            await conn.execute("""
                INSERT INTO textbooks (id, subject, grade, edition, book_name)
                VALUES ($1,'chinese','G12','高考备考','高考备考·成语')
                ON CONFLICT DO NOTHING
            """, GAOKAO_TEXTBOOK_ID)
        print(f"  {'✅ 创建' if not dry_run else '[DRY] 创建'} textbook: {GAOKAO_TEXTBOOK_ID}")
    else:
        print(f"  ✓ textbook 已存在")

    kc_exists = await conn.fetchval("SELECT id FROM knowledge_clusters WHERE id=$1", GAOKAO_CLUSTER_ID)
    if not kc_exists:
        if not dry_run:
            await conn.execute("""
                INSERT INTO knowledge_clusters (id, textbook_id, name, display_order)
                VALUES ($1, $2, '高考高频易错成语', 1)
                ON CONFLICT DO NOTHING
            """, GAOKAO_CLUSTER_ID, GAOKAO_TEXTBOOK_ID)
        print(f"  {'✅ 创建' if not dry_run else '[DRY] 创建'} cluster: {GAOKAO_CLUSTER_ID}")
    else:
        print(f"  ✓ cluster 已存在")

    # ── Step 5: 导入50个高考成语 ──────────────────────────────
    print(f"\n=== Step 5: 导入50个高考高频成语 ({'DRY-RUN' if dry_run else '写库'}) ===")

    # 找出哪些已存在（避免重复）
    existing_idioms = set(await conn.fetch(
        "SELECT name FROM knowledge_units WHERE ku_type='chengyu'"
    ))
    existing_names = {r["name"] for r in existing_idioms}

    results = []
    for i, idiom in enumerate(GAOKAO_IDIOMS, 1):
        ku_id = make_ku_id(idiom)
        already = await conn.fetchval("SELECT id FROM knowledge_units WHERE id=$1", ku_id)
        in_ke_nei = idiom in existing_names  # 是否也在课内

        print(f"  [{i:02d}/50] {idiom}{'（课内亦有）' if in_ke_nei else ''}...", flush=True)
        rc = call_deepseek(idiom)
        if rc is None:
            continue
        time.sleep(0.3)

        # 应用人工修正（覆盖 LLM 输出）
        if idiom in MANUAL_CORRECTIONS:
            rc.update(MANUAL_CORRECTIONS[idiom])

        if in_ke_nei:
            rc["source_type"] = "课内+高考必备"
        else:
            rc["source_type"] = "高考必备"

        simple_desc = rc.get("definition", idiom)

        if not dry_run:
            if already:
                await conn.execute(
                    "UPDATE knowledge_units SET rich_content=$1 WHERE id=$2",
                    json.dumps(rc, ensure_ascii=False), ku_id
                )
            else:
                await conn.execute("""
                    INSERT INTO knowledge_units
                      (id, textbook_id, cluster_id, name, description,
                       ku_type, difficulty, exam_frequency, rich_content)
                    VALUES ($1,$2,$3,$4,$5,'chengyu',0.6,'high',$6)
                    ON CONFLICT (id) DO UPDATE SET rich_content=EXCLUDED.rich_content
                """, ku_id, GAOKAO_TEXTBOOK_ID, GAOKAO_CLUSTER_ID,
                    idiom, simple_desc,
                    json.dumps(rc, ensure_ascii=False))
        results.append((idiom, rc, in_ke_nei))

    await conn.close()

    # ── 输出抽查报告 ─────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"=== 50个高考高频成语补全结果（{'DRY-RUN' if dry_run else '已写库'}）===")
    print(f"{'='*60}\n")
    for idiom, rc, in_ke_nei in results:
        tag = "【课内+高考必备】" if in_ke_nei else "【高考必备】"
        print(f"── {idiom} {tag}")
        print(f"   拼音:     {rc.get('pinyin','')}")
        print(f"   释义:     {rc.get('definition','')}")
        print(f"   感情色彩: {rc.get('sentiment','')}  ★关键审查点")
        print(f"   适用对象: {rc.get('target','')}")
        print(f"   谦敬辞:   {rc.get('respect_type','')}")
        key_morph = rc.get('key_morpheme')
        if key_morph:
            print(f"   关键字义: {key_morph}")
        err = rc.get('error_point')
        print(f"   易错点:   {err if err else '（无典型误用）'}  ★关键审查点")
        print(f"   正例:     {rc.get('correct_example','')}")
        wrong = rc.get('wrong_example')
        if wrong:
            print(f"   反例:     {wrong}")
        conf = rc.get('confusable', [])
        for c in conf:
            print(f"   易混:     {c.get('idiom','')} — {c.get('diff','')}")
        print(f"   典故:     {rc.get('origin','')}")
        print(f"   高考陷阱: {rc.get('exam_tip','')}  ★关键审查点")
        print()

    if dry_run:
        print(f"\n=== DRY-RUN 完毕。确认内容无误后传 --execute 写库 ===")
    else:
        print(f"\n=== 写库完成：{len(results)} 个高考成语已导入 ===")


if __name__ == "__main__":
    dry = "--execute" not in sys.argv
    if dry:
        print("=== DRY-RUN 模式（传 --execute 执行）===\n")
    asyncio.run(run(dry_run=dry))
