"""
成语库成分审查脚本（dry-run only）
导出四类待处理清单:
  A. ≤2字词汇 → 转 zixing_ziyin / cizu_yunyong
  B. 名字带括号的真成语 → 清理名字
  C. 俗语/名言/诗句 → 转 mingpian 或留 chengyu
  D. 垃圾条目 → 删除

运行: python3 scripts/chengyu_audit.py
"""
import asyncio
import asyncpg
import re

DB_URL = "postgresql://postgres:postgres@localhost:5433/mneme"

# ── 字音字形类词汇（字形生僻/易错读/易错写）─────────────────────────
ZIXING_HINTS = {
    "圭臬", "恪守", "执拗", "寒暄", "萧索", "隽永", "颓唐", "颓废",
    "戮力", "圭臬", "讪讪", "幽远",
}

# ── 已知"名字带括号"的括号类型 ─────────────────────────────────────
SOURCE_BRACKET_RE = re.compile(
    r"（(出师表|苏武传|谈读书|梦回繁华|苏州园林|鸿门宴|烛之武退秦师"
    r"|白杨礼赞|孤独之旅|植树的牧羊人|山水画的意境|最苦与最乐|阿长"
    r"|老王|台阶|邹忌|江南逢|受降城|人民英雄|何厌之有|不求甚解"
    r"|说.木叶.|偭规|九死|伟大的悲剧|散文|名句.*成语).*?）",
    re.DOTALL
)
ANNOTATION_BRACKET_RE = re.compile(r"（成语）|（chengyu）|（成语类）")

# ── 垃圾特征 ─────────────────────────────────────────────────────────
GARBAGE_PATTERNS = [
    r"：",               # 冒号=课文标题
    r"……",              # 模板缺位
    r"积累",             # 类别标签
    r"月一十五",
    r"脂粉",
    r"好马不鞴",
    r"过了这个村",
    r"在表面",
    r"^成语积累",
    r"诸子散文",
]

# ── 现代概念（不是成语）────────────────────────────────────────────
MODERN_CONCEPTS = {
    "国际话语权", "信息边缘化", "多声部合唱", "跨越式追赶", "马太效应",
    "泥腿子专家", "信息鸿沟",
}

# ── 诗句（转mingpian）──────────────────────────────────────────────
POETRY_LINES = {
    "同是天涯沦落人", "此时无声胜有声", "相逢何必曾相识",
    "秋月春风等闲度", "犹抱琵琶半遮面", "落花时节",
    "门前冷落鞍马稀", "赚得行人错喜欢", "羁鸟恋旧林",
    "水尽鹅飞罢", "旋风翻败叶", "万籁俱寂",
}

# ── 留 chengyu 的多字熟语（有成语地位）────────────────────────────
KEEP_AS_CHENGYU = {
    "三人行，必有我师", "三人行必有我师",
    "项庄舞剑，意在沛公", "项庄舞剑意在沛公",
    "醉翁之意不在酒",
    "一夫当关，万夫莫开", "一夫当关万夫莫开",
    "塞翁失马，安知非福", "塞翁失马安知非福",
    "鞠躬尽瘁，死而后已", "鞠躬尽瘁死而后已",
    "人为刀俎，我为鱼肉", "人为刀俎我为鱼肉",
    "八仙过海，各显其能", "八仙过海各显其能",
    "兼听则明，偏信则暗",
    "天无绝人之路",
    "天有不测风云",
    "老死不相往来",
    "大行不顾细谨",
    "到什么山上唱什么歌",
    "取之无禁，用之不竭",
    "因人之力而敝之",
    "竖子不足与谋",
    "朝济而夕设版",
    "杀人如不能举",
    "由此可见一斑",
    "秋毫不敢有所近",
    "言有尽而意无穷",
    "不积跬步无以至千里",
    "九死不悔", "九死未悔",
    "偭规越矩",
    "方枘圆凿",
    "二者必居其一",
    "修身齐家治国平天下",
    "好马不鞴双鞍，烈女不更二夫",  # will be garbage if too long
    "一人飞升，仙及鸡犬",
    "一方有难，八方支援",
    "四两拨千斤",
    "化干戈为玉帛",
    "一物降一物",
    "水火不相容",
    "置人于死地",
    "拒人于千里之外",
}


def extract_idiom_name(name: str) -> str:
    parts = [p.strip() for p in name.split("·")]
    if len(parts) >= 3 and parts[1] == "成语":
        return parts[2]
    if len(parts) >= 2 and parts[0] == "成语":
        return parts[1]
    if len(parts) >= 2:
        return parts[0]
    return name.strip()


def char_len(s: str) -> int:
    return len(re.sub(r"[\s，。、；：]", "", s))


def clean_bracket_name(name: str):
    """返回 (cleaned_name, source_note_or_None)"""
    # 去掉「（成语）」标注
    cleaned = ANNOTATION_BRACKET_RE.sub("", name).strip()
    # 去掉来源括号并提取
    m = SOURCE_BRACKET_RE.search(cleaned)
    source = m.group(1) if m else None
    cleaned = SOURCE_BRACKET_RE.sub("", cleaned).strip()
    # 去掉其他残留括号（如「（蝉）」「（老王）」）
    cleaned = re.sub(r"（[^）]{1,10}）", "", cleaned).strip()
    cleaned = re.sub(r"\([^\)]{1,10}\)", "", cleaned).strip()
    return cleaned, source


async def run():
    conn = await asyncpg.connect(DB_URL)

    rows = await conn.fetch("""
        SELECT ku.id, ku.name, ku.description, ku.rich_content, ku.ku_type,
               t.book_name
        FROM knowledge_units ku
        JOIN textbooks t ON ku.textbook_id = t.id
        WHERE ku.ku_type = 'chengyu'
          AND t.subject = 'chinese'
          AND ku.textbook_id != 'GAOKAO-CHINESE-GAOKAO'
        ORDER BY ku.id
    """)

    print(f"课内成语总条数: {len(rows)}\n")

    cat_a = []   # ≤2字词汇 → 转类型
    cat_b = []   # 名字带括号 → 清理
    cat_c_ming = []  # 诗句/名言 → 转mingpian
    cat_c_keep = []  # 多字熟语 → 留chengyu
    cat_d = []   # 垃圾 → 删除
    cat_ok = []  # 正常四字成语

    for row in rows:
        iname = extract_idiom_name(row["name"])
        clen = char_len(iname)

        # ── A: ≤2字词汇 ────────────────────────────────────────────
        if clen <= 2:
            suggested = "zixing_ziyin" if iname in ZIXING_HINTS else "cizu_yunyong"
            cat_a.append((row["id"], iname, suggested, row["book_name"]))
            continue

        # ── D: 垃圾（最先筛，避免误分类）─────────────────────────
        is_garbage = any(re.search(p, iname) for p in GARBAGE_PATTERNS)
        if iname in MODERN_CONCEPTS:
            is_garbage = True
        if is_garbage:
            cat_d.append((row["id"], iname, row["book_name"]))
            continue

        # ── B: 名字带括号 ──────────────────────────────────────────
        has_bracket = "（" in iname or "(" in iname
        if has_bracket:
            cleaned, source = clean_bracket_name(iname)
            cat_b.append((row["id"], iname, cleaned, source, row["book_name"]))
            continue

        # ── C: 多字条目分类 ────────────────────────────────────────
        if clen >= 5:
            norm = iname.replace("，", "").replace("。", "")
            if iname in POETRY_LINES or norm in POETRY_LINES:
                cat_c_ming.append((row["id"], iname, row["book_name"]))
            elif iname in KEEP_AS_CHENGYU or norm in KEEP_AS_CHENGYU:
                cat_c_keep.append((row["id"], iname, row["book_name"]))
            else:
                # 未分类的多字条目 → 按长度判断
                if clen >= 8:
                    # 长句子很可能是名句，默认归mingpian候选
                    cat_c_ming.append((row["id"], iname, row["book_name"]))
                else:
                    cat_c_keep.append((row["id"], iname, row["book_name"]))
            continue

        cat_ok.append(iname)

    await conn.close()

    # ──────────────────────────────────────────────────────────────
    # 输出清单
    # ──────────────────────────────────────────────────────────────

    print("=" * 65)
    print(f"【A类】≤2字词汇 → 转类型（共{len(cat_a)}条）")
    print("=" * 65)
    print(f"{'词汇':<8} {'建议类型':<16} {'来源教材'}")
    print("-" * 65)
    for _, iname, suggested, book in cat_a:
        print(f"{iname:<8} {suggested:<16} {book}")

    print()
    print("=" * 65)
    print(f"【B类】名字带括号 → 清理名字（共{len(cat_b)}条）")
    print("=" * 65)
    print(f"{'原名字':<28} → {'清理后':<16} {'来源'}")
    print("-" * 65)
    for _, orig, cleaned, source, book in cat_b:
        src_str = f"[{source}]" if source else ""
        print(f"{orig:<28} → {cleaned:<16} {src_str}")

    print()
    print("=" * 65)
    print(f"【C1类】诗句/名言 → 转mingpian（共{len(cat_c_ming)}条）")
    print("=" * 65)
    for _, iname, book in cat_c_ming:
        print(f"  {iname}  ({book})")

    print()
    print("=" * 65)
    print(f"【C2类】多字熟语 → 留chengyu（共{len(cat_c_keep)}条）")
    print("=" * 65)
    for _, iname, book in cat_c_keep:
        print(f"  {iname}")

    print()
    print("=" * 65)
    print(f"【D类】垃圾/文本残留 → 删除（共{len(cat_d)}条）")
    print("=" * 65)
    for _, iname, book in cat_d:
        print(f"  [{book}] {iname}")

    print()
    print("=" * 65)
    print(f"【正常四字成语】{len(cat_ok)} 条（不动）")
    print("=" * 65)
    print(f"  样本（前30）: {', '.join(cat_ok[:30])}")

    print()
    print("─" * 65)
    print("汇总:")
    print(f"  A-转类型:     {len(cat_a):>4} 条")
    print(f"  B-清理括号:   {len(cat_b):>4} 条")
    print(f"  C1-转mingpian:{len(cat_c_ming):>4} 条")
    print(f"  C2-留chengyu: {len(cat_c_keep):>4} 条")
    print(f"  D-删除:       {len(cat_d):>4} 条")
    print(f"  正常四字:     {len(cat_ok):>4} 条")
    print(f"  总计:         {len(cat_a)+len(cat_b)+len(cat_c_ming)+len(cat_c_keep)+len(cat_d)+len(cat_ok):>4} 条")


if __name__ == "__main__":
    asyncio.run(run())
