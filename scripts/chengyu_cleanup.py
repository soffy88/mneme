"""
成语库清理执行脚本
dry-run: python3 scripts/chengyu_cleanup.py
执行:    python3 scripts/chengyu_cleanup.py --execute
"""
import asyncio
import json
import re
import sys
import asyncpg

DB_URL = "postgresql://postgres:postgres@localhost:5433/mneme"

# ─────────────────────────────────────────────────────────────────
# 决策表（按用户最终确认）
# ─────────────────────────────────────────────────────────────────

# ── D类：垃圾删除（提取后的成语名 → 删） ─────────────────────────
DELETE_NAMES: set[str] = {
    # D类 16条
    "泥腿子专家", "读书：目的和前提", "与……相悖", "信息边缘化",
    "信息鸿沟", "受……鼓舞", "国际话语权", "多声部合唱",
    "冬时年节，月一十五", "好马不鞴双鞍，烈女不更二夫",
    "跨越式追赶", "诸子散文中积累的名句（成语类）",
    "过了这个村可没有这个店", "搽在表面的自欺欺人的脂粉",
    # B类特殊2条
    "直僵僵", "马太效应",
    # C1类中3条删（非名言非熟语）
    "装腔作势，借以吓人", "残酷斗争，无情打击", "天庭饱满，地阁方圆",
    # C2类中1条删
    "皇帝的新装",
    # 漏网3字2条
    "琵琶行", "万应锭",
}

# ── A类→cizu_yunyong（词义运用） ─────────────────────────────────
RETYPE_CIZU: set[str] = {
    # A类 ≤2字
    "劈手", "撂下", "深沉", "落寞", "赏玩",
    "刀俎", "切齿", "显然", "洗练", "肆虐",
    "钟爱", "称职", "匿名", "智叟", "赋闲", "拿糖",
    # 漏网3字（词义运用）
    "下苦功", "不足道", "不更事", "吝啬鬼", "现世宝",
    # B类特殊（括号去掉后本是词）
    "吞噬", "不逊", "喧嚣",
}

# ── A类→zixing_ziyin（字音字形） ─────────────────────────────────
RETYPE_ZIYIN: set[str] = {
    # A类 ≤2字（有字音字形陷阱）
    "幽远", "恪守", "执拗", "萧索", "讪讪",
    "隽永", "颓废", "戮力", "寒暄", "圭臬", "颓唐",
    # 漏网3字（叠字/难字形）
    "暖乎乎", "汗涔涔",
}

# ── C1类→mingpian（13条，3条已删） ────────────────────────────────
RETYPE_MINGPIAN: set[str] = {
    "下笔千言，离题万里", "同是天涯沦落人",
    "日有所思，夜有所梦", "此时无声胜有声",
    "犹抱琵琶半遮面", "相逢何必曾相识",
    "秋月春风等闲度", "空话连篇，言之无物",
    "羁鸟恋旧林", "门前冷落鞍马稀",
    "旋风翻败叶", "赚得行人错喜欢", "水尽鹅飞罢",
}

# ── B类特殊（原括号名 → 新名+新类型+来源备注） ────────────────────
# key = 提取后的带括号名；value = (clean_name, new_ku_type, source_note|None)
B_SPECIAL: dict[str, tuple[str, str, str | None]] = {
    "三径（代指隐士住处）": ("三径", "wenhua_changshi", "陶渊明《归去来兮辞》典故，代指隐士居所"),
    "人生如朝露（苏武传）": ("人生如朝露", "mingpian",   "苏武传"),
    "吞噬（成语）":          ("吞噬",        "cizu_yunyong", None),
    "不逊（xùn）":          ("不逊",        "cizu_yunyong", None),
    "喧嚣（蝉）":            ("喧嚣",        "cizu_yunyong", None),
    # 直僵僵 & 马太效应 在 DELETE_NAMES 中
}

# ── "成语积累" 两条（原名含括号，是D类） ─────────────────────────
# 它们 extract 后仍含"积累"，被 DELETE_NAMES 里的字符串模糊匹配不到
# → 单独列 name 前缀
DELETE_PREFIX_KEYWORDS: list[str] = [
    "成语积累（",   # 成语积累（烛之武退秦师）/（鸿门宴）
]


# ─────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────

def extract_idiom_name(name: str) -> str:
    parts = [p.strip() for p in name.split("·")]
    if len(parts) >= 3 and parts[1] == "成语":
        return parts[2]
    if len(parts) >= 2 and parts[0] == "成语":
        return parts[1]
    if len(parts) >= 2:
        return parts[0]
    return name.strip()


def clean_bracket_name(name: str) -> tuple[str, str | None]:
    """返回 (cleaned_name, source_note_or_None)"""
    # 提取来源括号
    m = re.search(r"（([^）]{1,20})）", name)
    source = m.group(1) if m else None
    # 去掉所有括号（中英文）
    cleaned = re.sub(r"（[^）]{0,30}）", "", name)
    cleaned = re.sub(r"\([^\)]{0,20}\)", "", cleaned).strip()
    return cleaned, source


def has_bracket(name: str) -> bool:
    return "（" in name or "(" in name


# ─────────────────────────────────────────────────────────────────
# 主逻辑
# ─────────────────────────────────────────────────────────────────

async def run(dry_run: bool = True):
    conn = await asyncpg.connect(DB_URL)

    rows = await conn.fetch("""
        SELECT ku.id, ku.name, ku.description, ku.rich_content, ku.ku_type,
               t.book_name
        FROM knowledge_units ku
        JOIN textbooks t ON ku.textbook_id = t.id
        WHERE ku.ku_type = 'chengyu'
          AND t.subject   = 'chinese'
          AND ku.textbook_id != 'GAOKAO-CHINESE-GAOKAO'
        ORDER BY ku.id
    """)

    # ── 分类 ────────────────────────────────────────────────────
    ops_delete:  list[dict] = []
    ops_retype:  list[dict] = []   # ku_type 变更
    ops_rename:  list[dict] = []   # name 变更（B类去括号）
    ops_skip:    list[dict] = []   # 不动

    # B类去括号后可能重名 → 先收集 cleaned_name → entries 映射
    bracket_groups: dict[str, list[dict]] = {}

    for row in rows:
        r   = dict(row)
        iname = extract_idiom_name(r["name"])
        r["_iname"] = iname

        # ── D类：垃圾删除 ────────────────────────────────────────
        if iname in DELETE_NAMES:
            ops_delete.append(r | {"_reason": "D类垃圾"})
            continue

        # ── 名字含"积累"关键词 → 也删 ────────────────────────────
        if any(iname.startswith(kw) for kw in DELETE_PREFIX_KEYWORDS):
            ops_delete.append(r | {"_reason": "D类垃圾(积累标签)"})
            continue

        # ── A/漏网3字 → 转类型 ───────────────────────────────────
        if iname in RETYPE_CIZU:
            ops_retype.append(r | {"_new_type": "cizu_yunyong"})
            continue
        if iname in RETYPE_ZIYIN:
            ops_retype.append(r | {"_new_type": "zixing_ziyin"})
            continue

        # ── C1类 → mingpian ──────────────────────────────────────
        if iname in RETYPE_MINGPIAN:
            ops_retype.append(r | {"_new_type": "mingpian"})
            continue

        # ── B类特殊（带括号，特殊处理） ──────────────────────────
        if iname in B_SPECIAL:
            new_name, new_type, src = B_SPECIAL[iname]
            ops_retype.append(r | {
                "_new_type": new_type,
                "_rename": new_name,
                "_source": src,
            })
            continue

        # ── B类一般（带括号，去括号保留chengyu） ─────────────────
        if has_bracket(iname):
            cleaned, src = clean_bracket_name(iname)
            if cleaned:
                # 清理后名字若在删除集中 → 直接删（如 直僵僵/马太效应）
                if cleaned in DELETE_NAMES:
                    ops_delete.append(r | {"_reason": f"B类去括号后='{cleaned}'→删"})
                    continue
                key = cleaned
                if key not in bracket_groups:
                    bracket_groups[key] = []
                bracket_groups[key].append(r | {
                    "_cleaned": cleaned,
                    "_source":  src,
                })
                continue

        # ── 其余：正常条目，不动 ──────────────────────────────────
        ops_skip.append(r)

    # ── 处理 B类去括号后的重名 ───────────────────────────────────
    # 同时检查 cleaned_name 是否已有干净条目存在
    existing_clean: dict[str, str] = {}  # cleaned_name → existing_id
    for r in ops_skip:
        existing_clean[r["_iname"]] = r["id"]

    for cleaned_name, entries in bracket_groups.items():
        if cleaned_name in existing_clean:
            # 已有干净条目 → bracket 版全删，合并 sources 到 existing
            existing_id = existing_clean[cleaned_name]
            for e in entries:
                ops_delete.append(e | {"_reason": f"B类重名合并→{existing_id}"})
            # 把 sources 写入已有条目的 rich_content
            sources = [e["_source"] for e in entries if e["_source"]]
            if sources:
                ops_rename.append({
                    "id": existing_id,
                    "_iname": cleaned_name,
                    "_cleaned": cleaned_name,
                    "_source": " / ".join(sources),
                    "_new_type": None,
                    "_reason": "B类合并来源",
                })
        elif len(entries) > 1:
            # 多条 bracket 版指向同一 cleaned_name → 保留第一条，删其余
            keep = entries[0]
            srcs = [e["_source"] for e in entries if e["_source"]]
            ops_rename.append(keep | {
                "_cleaned": cleaned_name,
                "_source": " / ".join(srcs) if srcs else keep.get("_source"),
                "_new_type": None,
                "_reason": "B类去括号(dedup保留)",
            })
            for e in entries[1:]:
                ops_delete.append(e | {"_reason": "B类重名去重"})
        else:
            # 单条 bracket 版，正常重命名
            e = entries[0]
            ops_rename.append(e | {"_reason": "B类去括号"})

    # ─────────────────────────────────────────────────────────────
    # 打印 dry-run 报告
    # ─────────────────────────────────────────────────────────────
    print("=" * 68)
    print(f"成语库清理计划 ({'DRY-RUN' if dry_run else '正式执行'})")
    print("=" * 68)

    # D: 删除清单
    print(f"\n【D类】删除 {len(ops_delete)} 条")
    print("-" * 68)
    for r in sorted(ops_delete, key=lambda x: x["_iname"]):
        print(f"  🗑  {r['_iname']:<28}  ({r['_reason']})")

    # 分组（每条只出现一次）
    # B特殊：有 _rename 的（已包含 wenhua/mingpian/cizu 重命名）
    b_sp_list  = [r for r in ops_retype if "_rename" in r]
    # 纯转类型（无 rename）
    cizu_list  = [r for r in ops_retype if r["_new_type"] == "cizu_yunyong" and "_rename" not in r]
    ziyin_list = [r for r in ops_retype if r["_new_type"] == "zixing_ziyin"  and "_rename" not in r]
    ming_list  = [r for r in ops_retype if r["_new_type"] == "mingpian"       and "_rename" not in r]
    wh_list    = [r for r in ops_retype if r["_new_type"] == "wenhua_changshi" and "_rename" not in r]
    # B类 改名（仅真正改了 name 的；"合并来源"的不计入改名数）
    ops_rename_real  = [r for r in ops_rename if r.get("_cleaned") and r["_cleaned"] != r.get("_iname")]
    ops_rename_merge = [r for r in ops_rename if not (r.get("_cleaned") and r["_cleaned"] != r.get("_iname"))]

    print(f"\n【A类】→ cizu_yunyong {len(cizu_list)} 条")
    print("-" * 68)
    for r in cizu_list:
        print(f"  📦  {r['_iname']}")

    print(f"\n【A类】→ zixing_ziyin {len(ziyin_list)} 条")
    print("-" * 68)
    for r in ziyin_list:
        print(f"  📦  {r['_iname']}")

    print(f"\n【C1类】→ mingpian {len(ming_list)} 条")
    print("-" * 68)
    for r in ming_list:
        print(f"  📖  {r['_iname']}")

    print(f"\n【B类特殊】→ 改名+转类型 {len(b_sp_list)} 条")
    print("-" * 68)
    for r in b_sp_list:
        print(f"  ✏️   {r['_iname']} → {r['_rename']} [{r['_new_type']}]")

    print(f"\n【B类】去括号改名 → 保留chengyu {len(ops_rename_real)} 条")
    print("-" * 68)
    for r in ops_rename_real:
        src = r.get("_source", "")
        src_str = f" [来源:{src}]" if src else ""
        print(f"  ✏️   {r['_iname'][:30]:<30} → {r['_cleaned']}{src_str}")

    if ops_rename_merge:
        print(f"\n【B类】合并来源到已有条目 {len(ops_rename_merge)} 条（name 不变）")
        print("-" * 68)
        for r in ops_rename_merge:
            print(f"  🔗  {r['_iname']:<28}  ← 来源:{r.get('_source','')}")

    # 数量核算
    total_cizu  = len(cizu_list)  + len([r for r in b_sp_list if r["_new_type"] == "cizu_yunyong"])
    total_ziyin = len(ziyin_list)
    total_ming  = len(ming_list)  + len([r for r in b_sp_list if r["_new_type"] == "mingpian"])
    total_wh    = len(wh_list)    + len([r for r in b_sp_list if r["_new_type"] == "wenhua_changshi"])
    # 最终chengyu = 不动的 + 真实改名的（合并来源的已在 ops_skip 里）
    chengyu_after = len(ops_skip) + len(ops_rename_real)

    print()
    print("─" * 68)
    print("汇总:")
    print(f"  删除:              {len(ops_delete):>4} 条")
    print(f"  转 cizu_yunyong:   {total_cizu:>4} 条")
    print(f"  转 zixing_ziyin:   {total_ziyin:>4} 条")
    print(f"  转 mingpian:       {total_ming:>4} 条")
    print(f"  转 wenhua_changshi:{total_wh:>4} 条")
    print(f"  B类去括号改名:     {len(ops_rename_real):>4} 条（保留chengyu）")
    print(f"  合并来源(name不变):{len(ops_rename_merge):>4} 条（已是clean chengyu）")
    print(f"  正常四字不动:      {len(ops_skip):>4} 条")
    # ops_rename_merge 的 ID 已在 ops_skip 中，不重复计
    sanity = len(ops_delete)+total_cizu+total_ziyin+total_ming+total_wh+len(ops_rename_real)+len(ops_skip)
    print()
    print(f"  课内成语  清理前: {len(rows)} 条")
    print(f"  课内成语  清理后: {chengyu_after} 条（纯成语）")
    print(f"  核算: {sanity} ({'✅ 一致' if sanity==len(rows) else f'⚠️ 差{sanity-len(rows)}'})")

    if dry_run:
        print("\n传 --execute 正式执行")
        await conn.close()
        return

    # ─────────────────────────────────────────────────────────────
    # 执行
    # ─────────────────────────────────────────────────────────────
    print("\n开始执行...")
    deleted = retyped = renamed = 0

    async with conn.transaction():
        # 1. 删除
        for r in ops_delete:
            await conn.execute("DELETE FROM knowledge_units WHERE id=$1", r["id"])
            deleted += 1

        # 2. 转类型（+可能改名）
        for r in ops_retype:
            new_type = r["_new_type"]
            new_name = r.get("_rename")
            src      = r.get("_source")

            # 更新 rich_content 中的 source_text
            rc_raw = r.get("rich_content") or "{}"
            rc = json.loads(rc_raw) if rc_raw else {}
            if src:
                rc["source_text"] = src

            if new_name:
                await conn.execute("""
                    UPDATE knowledge_units
                    SET ku_type=$1, name=$2, rich_content=$3
                    WHERE id=$4
                """, new_type, new_name,
                    json.dumps(rc, ensure_ascii=False), r["id"])
            else:
                await conn.execute("""
                    UPDATE knowledge_units
                    SET ku_type=$1, rich_content=$2
                    WHERE id=$3
                """, new_type,
                    json.dumps(rc, ensure_ascii=False), r["id"])
            retyped += 1

        # 3. B类去括号改名（保留chengyu）
        for r in ops_rename:
            cleaned = r.get("_cleaned")
            src     = r.get("_source")
            if not cleaned:
                continue
            # 更新 rich_content 中的 source_text
            rc_raw = r.get("rich_content") or "{}"
            rc = json.loads(rc_raw) if rc_raw else {}
            if src:
                existing_src = rc.get("sources", [])
                if isinstance(existing_src, list):
                    if src not in existing_src:
                        existing_src.append(src)
                    rc["sources"] = existing_src
                else:
                    rc["source_text"] = src
            await conn.execute("""
                UPDATE knowledge_units
                SET name=$1, rich_content=$2
                WHERE id=$3
            """, cleaned, json.dumps(rc, ensure_ascii=False), r["id"])
            renamed += 1

    await conn.close()

    print("\n✅ 执行完成:")
    print(f"   删除 {deleted} 条")
    print(f"   转类型 {retyped} 条")
    print(f"   改名(去括号) {renamed} 条")

    # 验证
    check = await asyncpg.connect(DB_URL)
    remaining = await check.fetchval(
        "SELECT COUNT(*) FROM knowledge_units WHERE ku_type='chengyu' AND textbook_id != 'GAOKAO-CHINESE-GAOKAO'"
    )
    print(f"   课内成语剩余: {remaining} 条")
    await check.close()


if __name__ == "__main__":
    dry = "--execute" not in sys.argv
    asyncio.run(run(dry_run=dry))
