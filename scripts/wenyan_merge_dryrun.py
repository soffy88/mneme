"""
wenyan_merge_dryrun.py  —— 文言实词 同词多条合并 dry-run预览
输出 scripts/wenyan_merge_preview.md，不改数据库。

合并规则:
  Key = (textbook_id, 真词根)
  真词根判断:
    - Pattern A: name中·前的字就是真词(如"以·因为")
    - Pattern B: ·前是篇目名，真词在描述里(如"劝学·中"→真词=中)
  同Key多条 → 合并为一条,义项去重后入数组
  跨textbook不合并
"""

import asyncio, asyncpg, re, os, json
from collections import defaultdict
from difflib import SequenceMatcher

DB_URL = os.getenv("DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5433/mneme").replace(
    "postgresql+asyncpg://", "postgresql://")

# ── 描述解析 ──────────────────────────────────────────────────────────

def is_002(desc: str) -> bool:
    return bool(desc and ("know-what:" in desc or "[文言]:" in desc))

def parse_yixiang_002(desc: str) -> dict:
    r = {"pos": "", "yixiang": "", "liju": "", "tongja": "", "source": ""}
    for line in desc.split("\n"):
        l = line.strip()
        if l.startswith("[文言]:"):
            wenyan = l[5:].strip()
            for seg in wenyan.split("；"):
                s = seg.strip()
                if s.startswith("词性:"): r["pos"] = s[3:].strip()
                elif s.startswith("义项:"): r["yixiang"] = s[3:].strip()
                elif s.startswith("例句:"): r["liju"] = s[3:].strip()
                elif "通假" in s: r["tongja"] = s
        elif l.startswith("来源:"):
            r["source"] = l[3:].strip()
    # know-what 作为释义兜底
    for line in desc.split("\n"):
        l = line.strip()
        if l.startswith("know-what:"):
            r["know_what"] = l[10:].strip()
            break
    return r

def parse_yixiang_old(desc: str) -> dict:
    r = {"pos": "", "yixiang": "", "liju": "", "tongja": "", "source": ""}
    for line in desc.split("\n"):
        l = line.strip()
        if l.startswith("【来源】"): r["source"] = l[4:].strip()
        elif l.startswith("【文言】"):
            wenyan = l[4:].strip()
            for seg in wenyan.split("；"):
                s = seg.strip()
                if s.startswith("词性："): r["pos"] = s[3:].strip()
                elif s.startswith("义项："): r["yixiang"] = s[3:].strip()
                elif s.startswith("例句："): r["liju"] = s[3:].strip()
    first = desc.split("\n")[0].strip()
    r["know_what"] = first
    return r

def parse_yixiang(desc: str) -> dict:
    if not desc:
        return {}
    return parse_yixiang_002(desc) if is_002(desc) else parse_yixiang_old(desc)

# ── 真词根提取 ────────────────────────────────────────────────────────

def actual_word_from_desc(desc: str) -> str:
    """从描述里提取真实被描述的词（描述第一个词）"""
    if not desc:
        return ""
    # 002: know-what: 中，动词，合乎 → 中
    if is_002(desc):
        for line in desc.split("\n"):
            l = line.strip()
            if l.startswith("know-what:"):
                content = l[10:].strip()
                m = re.match(r"^([^，,、\s（(【\[「『]+)", content)
                return m.group(1).strip("·") if m else ""
    # old: 中：动词，合乎 → 中
    else:
        first = desc.split("\n")[0].strip()
        m = re.match(r"^([^：:\s，,（(【\[「]+)[：:]", first)
        return m.group(1).strip("·") if m else ""
    return ""

# 判断词根是篇目名还是真词:
#   - 词根长度 > 4 → 基本是篇目名
#   - 或 entries 里描述的词与词根不同 → 篇目名前缀
def classify_root(root: str, entries: list) -> tuple[str, list]:
    """
    返回 (mode, items)
    mode = 'word'   → root 就是真词，义项合并
    mode = 'title'  → root 是篇目名，entries 各自的真词不同，不合并
    items: 在 title 模式下，每个 entry 的真词
    """
    if len(root) > 4:
        # 长前缀几乎肯定是篇目名
        true_words = [actual_word_from_desc(e["description"]) for e in entries]
        return "title", true_words

    # 短前缀：检查描述里的词是否就是 root
    mismatches = 0
    true_words = []
    for e in entries:
        w = actual_word_from_desc(e["description"])
        true_words.append(w)
        if w and w != root:
            mismatches += 1

    if mismatches >= len(entries) // 2 + 1:
        return "title", true_words
    return "word", true_words

# ── 义项去重 ─────────────────────────────────────────────────────────

def yixiang_key(yi: dict) -> str:
    return f"{yi.get('pos','')}|{yi.get('yixiang','')}|{yi.get('liju','')[:30]}"

def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def dedup_yixiangs(yis: list[dict]) -> tuple[list[dict], int]:
    """去重义项，返回 (去重后列表, 去掉的数量)"""
    seen_keys: list[str] = []
    kept: list[dict] = []
    removed = 0
    for yi in yis:
        key = yixiang_key(yi)
        # 精确重复
        if key in seen_keys:
            removed += 1
            continue
        # 近似重复：释义相似度 > 0.85
        yi_str = yi.get("yixiang", "") + yi.get("liju", "")
        is_dup = False
        for sk in seen_keys:
            sk_str = sk.split("|")[1] + sk.split("|")[2]
            if yi_str and sk_str and similar(yi_str, sk_str) > 0.85:
                is_dup = True
                removed += 1
                break
        if not is_dup:
            seen_keys.append(key)
            kept.append(yi)
    return kept, removed

# ── 主逻辑 ───────────────────────────────────────────────────────────

async def run():
    conn = await asyncpg.connect(DB_URL)

    rows = await conn.fetch("""
        SELECT ku.id, ku.name, ku.description, ku.difficulty, ku.textbook_id,
               t.book_name, t.grade
        FROM knowledge_units ku
        JOIN textbooks t ON ku.textbook_id = t.id
        WHERE ku.ku_type = 'wenyan_word' AND t.subject = 'chinese'
        ORDER BY t.grade, ku.textbook_id, ku.name
    """)

    await conn.close()

    total_before = len(rows)

    # Group by (textbook_id, root)
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        root = r["name"].split("·")[0].strip() if "·" in r["name"] else r["name"].strip()
        groups[(r["textbook_id"], root)].append(dict(r))

    # ── 分析每组 ──────────────────────────────────────────────────────

    # 统计
    merge_plans   = []   # 将被合并的组 (mode=word, cnt>1)
    title_plans   = []   # 篇目名前缀组 (mode=title, cnt>1)
    single_groups = []   # 单条，无需处理

    total_after = 0
    total_removed_dup = 0
    total_merged_groups = 0

    for (textbook_id, root), entries in sorted(groups.items()):
        if len(entries) == 1:
            single_groups.append((textbook_id, root, entries))
            total_after += 1
            continue

        mode, true_words = classify_root(root, entries)

        if mode == "title":
            title_plans.append((textbook_id, root, entries, true_words))
            total_after += len(entries)  # 篇目名前缀，各自保留
        else:
            # 合并这组
            all_yi = []
            all_sources = []
            for e in entries:
                yi = parse_yixiang(e["description"])
                all_yi.append(yi)
                src = yi.get("source", "")
                if src and src not in all_sources:
                    all_sources.append(src)

            deduped, n_removed = dedup_yixiangs(all_yi)
            total_removed_dup += n_removed
            total_merged_groups += 1
            total_after += 1

            book_name = entries[0]["book_name"]
            merge_plans.append({
                "textbook_id": textbook_id,
                "book_name": book_name,
                "root": root,
                "before_cnt": len(entries),
                "before_names": [e["name"] for e in entries],
                "yixiangs": deduped,
                "sources": all_sources,
                "n_removed_dup": n_removed,
            })

    # ── 跨册重复确认 ─────────────────────────────────────────────────
    # (名字完全相同的, 跨textbook)
    name_textbooks: dict[str, list] = defaultdict(list)
    for r in rows:
        name_textbooks[r["name"]].append(r["textbook_id"])
    cross_dups = {name: tbs for name, tbs in name_textbooks.items() if len(set(tbs)) > 1}

    # ── 生成报告 ─────────────────────────────────────────────────────
    lines = []
    lines.append("# 文言实词 合并 Dry-Run 预览\n")
    lines.append(f"**数据库**: {DB_URL.split('@')[-1]}\n")

    lines.append("## 1. 总量变化\n")
    lines.append(f"| 指标 | 数量 |")
    lines.append(f"|---|---|")
    lines.append(f"| 合并前总条数 | {total_before} |")
    lines.append(f"| 合并后总条数 | {total_after} |")
    lines.append(f"| 减少条数 | {total_before - total_after} |")
    lines.append(f"| 需合并的(textbook+词根)组数 | {total_merged_groups} |")
    lines.append(f"| 义项内真重复去掉 | {total_removed_dup} |")
    lines.append(f"| 篇目名前缀组(不合并) | {len(title_plans)} |")
    lines.append(f"| 跨册同名对(保留) | {len(cross_dups)} |")
    lines.append("")

    lines.append("## 2. 合并样例：「以」字\n")
    yi_example = [p for p in merge_plans if p["root"] == "以"]
    if yi_example:
        for plan in yi_example:
            lines.append(f"### 册次: {plan['book_name']}\n")
            lines.append(f"合并前 {plan['before_cnt']} 条:")
            for n in plan["before_names"]:
                lines.append(f"  - {n}")
            lines.append(f"\n合并后 name = `以`，义项数 = {len(plan['yixiangs'])}（去重 {plan['n_removed_dup']} 条）:\n")
            for i, yi in enumerate(plan["yixiangs"], 1):
                lines.append(f"  **义项{i}**: [{yi.get('pos','-')}] {yi.get('yixiang','-')} | 例：{yi.get('liju','-')}")
                if yi.get('tongja'):
                    lines.append(f"    通假：{yi['tongja']}")
            lines.append(f"\n出处: {' · '.join(plan['sources'])}\n")
    else:
        lines.append("（「以」在当前库无多条记录）\n")

    lines.append("## 3. 篇目名前缀（不合并）\n")
    lines.append("这些组的·前是篇目名，每条是不同词，不做合并:\n")
    for textbook_id, root, entries, true_words in title_plans[:15]:
        book = entries[0]["book_name"]
        pairs = [f"{e['name']}→真词:{w}" for e, w in zip(entries, true_words)]
        lines.append(f"- **{book}** | 前缀=`{root}` | {len(entries)}条")
        lines.append(f"  - {' , '.join(pairs[:5])}" + (" ..." if len(pairs) > 5 else ""))
    if len(title_plans) > 15:
        lines.append(f"  _（共 {len(title_plans)} 组，仅列前15）_")
    lines.append("")

    lines.append("## 4. 真重复去掉的案例（同义项提取两遍）\n")
    dup_examples = [p for p in merge_plans if p["n_removed_dup"] > 0]
    for plan in dup_examples[:10]:
        lines.append(f"- **{plan['book_name']}** `{plan['root']}`: "
                     f"合并前{plan['before_cnt']}条 → 去掉{plan['n_removed_dup']}重复义项")
        lines.append(f"  原始: {' | '.join(plan['before_names'])}")
    if not dup_examples:
        lines.append("（无义项级真重复，义项内容各有不同）\n")
    lines.append("")

    lines.append("## 5. 跨册同名（保留，不合并）\n")
    for name, tbs in list(cross_dups.items())[:10]:
        lines.append(f"- `{name}` 出现在 {len(set(tbs))} 册（保留各自条目）")
    lines.append("")

    lines.append("## 6. 合并计划概览（多条组，抽样50）\n")
    lines.append("| 册次 | 词根 | 合并前 | 合并后义项数 |")
    lines.append("|---|---|---|---|")
    for plan in sorted(merge_plans, key=lambda p: -p["before_cnt"])[:50]:
        lines.append(f"| {plan['book_name'][:12]} | {plan['root']} | {plan['before_cnt']}条 | {len(plan['yixiangs'])}义项 |")
    lines.append("")

    lines.append("## 7. 全部合并计划（JSON，供核查）\n")
    lines.append("```json")
    # 仅输出关键字段
    summary = []
    for p in merge_plans:
        summary.append({
            "book": p["book_name"],
            "root": p["root"],
            "before": p["before_cnt"],
            "after_yixiang": len(p["yixiangs"]),
            "removed_dup": p["n_removed_dup"],
            "names": p["before_names"],
        })
    lines.append(json.dumps(summary, ensure_ascii=False, indent=2))
    lines.append("```")

    report = "\n".join(lines)
    out_path = os.path.join(os.path.dirname(__file__), "wenyan_merge_preview.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(report[:3000])
    print(f"\n\n--- 完整报告已写入 {out_path} ---")
    print(f"合并前: {total_before}  合并后: {total_after}  减少: {total_before - total_after}")
    print(f"合并组数: {total_merged_groups}  义项真重复去除: {total_removed_dup}")
    print(f"篇目名前缀（不合并）: {len(title_plans)}  跨册保留: {len(cross_dups)}")

if __name__ == "__main__":
    asyncio.run(run())
