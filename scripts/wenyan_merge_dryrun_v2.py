"""
wenyan_merge_dryrun_v2.py  —— v2 dry-run

vs v1 新增:
  1. 例句完全相同 → 视为重复义项（不管词性措辞）
  2. Pattern B (篇目名前缀) → 每条提取真词改 name，再重跑册内合并
  3. 改名不确定的条目 → 标记"需人工"，不改、不合并
"""

import asyncio, asyncpg, re, os, json
from collections import defaultdict
from difflib import SequenceMatcher

DB_URL = os.getenv(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/mneme"
).replace("postgresql+asyncpg://", "postgresql://")

# 文言词类分类标签（在 name 的分段里会出现）
CATEGORY_LABELS = {
    "文言词语", "文言实词", "文言虚词", "文言词汇",
    "古今异义", "通假字", "词类活用", "文言句式",
}

# ── 描述解析 ──────────────────────────────────────────────────────────

def is_002(desc: str) -> bool:
    return bool(desc and ("know-what:" in desc or "[文言]:" in desc))

def parse_yixiang_002(desc: str) -> dict:
    r = {"pos": "", "yixiang": "", "liju": "", "tongja": "", "source": "", "know_what": ""}
    for line in desc.split("\n"):
        l = line.strip()
        if l.startswith("[文言]:"):
            for seg in l[5:].strip().split("；"):
                s = seg.strip()
                if s.startswith("词性:"): r["pos"] = s[3:].strip()
                elif s.startswith("义项:"): r["yixiang"] = s[3:].strip()
                elif s.startswith("例句:"): r["liju"] = s[3:].strip()
                elif "通假" in s: r["tongja"] = s
        elif l.startswith("来源:"):
            r["source"] = l[3:].strip()
        elif l.startswith("know-what:") and not r["know_what"]:
            r["know_what"] = l[10:].strip()
    return r

def parse_yixiang_old(desc: str) -> dict:
    r = {"pos": "", "yixiang": "", "liju": "", "tongja": "", "source": "", "know_what": ""}
    for line in desc.split("\n"):
        l = line.strip()
        if l.startswith("【来源】"): r["source"] = l[4:].strip()
        elif l.startswith("【文言】"):
            for seg in l[4:].strip().split("；"):
                s = seg.strip()
                if s.startswith("词性："): r["pos"] = s[3:].strip()
                elif s.startswith("义项："): r["yixiang"] = s[3:].strip()
                elif s.startswith("例句："): r["liju"] = s[3:].strip()
    r["know_what"] = desc.split("\n")[0].strip()
    return r

def parse_yixiang(desc: str) -> dict:
    if not desc:
        return {}
    return parse_yixiang_002(desc) if is_002(desc) else parse_yixiang_old(desc)

# ── 真词提取 ─────────────────────────────────────────────────────────

# 不含 ：: 的中文字符匹配（修复「木叶：...」提取过多的 bug）
_WORD_PAT = re.compile(r"^([^，,、\s（(【\[「『：:]+)")

def actual_word_from_desc(desc: str) -> str:
    """从描述里提取被描述的词（修复版，排除：后内容）。"""
    if not desc:
        return ""
    if is_002(desc):
        for line in desc.split("\n"):
            l = line.strip()
            if l.startswith("know-what:"):
                m = _WORD_PAT.match(l[10:].strip())
                return m.group(1).strip("·") if m else ""
    else:
        first = desc.split("\n")[0].strip()
        # 格式：词：释义 或 词，释义
        m = re.match(r"^([^，,、\s（(【\[「『：:]+)[：:]", first)
        return m.group(1).strip("·") if m else ""
    return ""


def extract_word_from_name_parts(name: str, root: str) -> tuple[str, str]:
    """
    从 name 的分段中提取真词，返回 (word, confidence)。
    confidence: 'high' | 'low' | 'fail'
    """
    parts = [p.strip() for p in name.split("·")]
    candidates: list[tuple[str, str]] = []  # (word, confidence)

    for part in parts[1:]:  # 跳过 root
        if part in CATEGORY_LABELS:
            continue

        # "X（同Y）" → word=X
        m_before_paren = re.match(r"^([^（(]+)[（(]", part)
        if m_before_paren:
            w = m_before_paren.group(1).strip()
            if w and w not in CATEGORY_LABELS:
                candidates.append((w, "high"))
                continue

        # "category（word）" 或 "text（word）" → word from parens
        m_in_paren = re.match(r"^[^（(]*[（(]([^）)]+)[）)]", part)
        if m_in_paren:
            w = m_in_paren.group(1).strip()
            # 排除书名 《...》 和长引用
            if not w.startswith("《") and len(w) <= 8:
                candidates.append((w, "high"))
                continue

        # 纯文本：短的视为词，长的视为义项描述（需人工）
        if len(part) <= 5:
            candidates.append((part, "high"))
        elif len(part) <= 10:
            candidates.append((part, "low"))
        else:
            candidates.append((part, "fail"))

    if not candidates:
        return "", "fail"

    word, conf = candidates[0]
    # 若候选词含义项描述类词（"暮春", "天亮" 等动宾短语），降级
    if conf == "high" and len(word) > 4:
        conf = "low"
    return word, conf


def is_pattern_b(entry: dict, root: str) -> bool:
    """判断单条是否为篇目名前缀（Pattern B）。"""
    # 长前缀基本是篇目名
    if len(root) > 4:
        return True
    # 描述里的词和 root 不一样
    w = actual_word_from_desc(entry["description"])
    return bool(w and w != root)


# ── 义项去重 ─────────────────────────────────────────────────────────

def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def dedup_yixiangs(yis: list[dict]) -> tuple[list[dict], int]:
    """去重：精确匹配 + 例句相同 + 相似度 > 0.85。"""
    seen_keys: list[str] = []
    seen_liju: list[str] = []
    kept: list[dict] = []
    removed = 0

    for yi in yis:
        key = f"{yi.get('pos','')}|{yi.get('yixiang','')}|{yi.get('liju','')[:30]}"
        liju = yi.get("liju", "").strip()

        # 精确重复
        if key in seen_keys:
            removed += 1
            continue

        # 例句完全相同（新规则）
        if liju and liju in seen_liju:
            removed += 1
            continue

        # 相似度 > 0.85
        yi_str = yi.get("yixiang", "") + yi.get("liju", "")
        is_dup = False
        for sk in seen_keys:
            sk_parts = sk.split("|")
            sk_str = (sk_parts[1] if len(sk_parts) > 1 else "") + (sk_parts[2] if len(sk_parts) > 2 else "")
            if yi_str and sk_str and similar(yi_str, sk_str) > 0.85:
                is_dup = True
                removed += 1
                break

        if not is_dup:
            seen_keys.append(key)
            if liju:
                seen_liju.append(liju)
            kept.append(yi)

    return kept, removed


# ── 主流程 ───────────────────────────────────────────────────────────

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

    # ── Phase 1: 对每条判断 Pattern B，提取真词 ───────────────────────
    name_map: dict[int, str] = {}   # ku_id → 最终使用的 name
    rename_log: list[dict] = []
    needs_review: list[dict] = []

    for r in rows:
        entry = dict(r)
        raw_name = entry["name"]
        has_dot = "·" in raw_name
        root = raw_name.split("·")[0].strip() if has_dot else raw_name.strip()

        if not has_dot or not is_pattern_b(entry, root):
            name_map[entry["id"]] = raw_name
            continue

        # Pattern B: 提取真词
        name_word, name_conf = extract_word_from_name_parts(raw_name, root)
        desc_word = actual_word_from_desc(entry["description"])

        # 综合判断
        if name_conf == "high" and name_word:
            final_word = name_word
            confidence = "high"
        elif name_word and desc_word and name_word == desc_word:
            final_word = name_word
            confidence = "high"
        elif desc_word and not name_word:
            final_word = desc_word
            confidence = "low"
        elif name_word:
            final_word = name_word
            confidence = "low"
        else:
            final_word = ""
            confidence = "fail"

        if not final_word or confidence == "fail":
            # 保留原 name，人工处理
            name_map[entry["id"]] = raw_name
            needs_review.append({
                "id": entry["id"], "name": raw_name,
                "book": entry["book_name"], "grade": entry["grade"],
                "desc_word": desc_word, "name_word": name_word,
                "reason": "无法自动提取真词",
            })
        else:
            name_map[entry["id"]] = final_word
            log_entry = {
                "old": raw_name, "new": final_word,
                "book": entry["book_name"], "grade": entry["grade"],
                "confidence": confidence,
            }
            rename_log.append(log_entry)
            if confidence == "low":
                needs_review.append({
                    "id": entry["id"], "name": raw_name,
                    "book": entry["book_name"], "grade": entry["grade"],
                    "proposed_new": final_word,
                    "desc_word": desc_word, "name_word": name_word,
                    "reason": "提取词可能不准确，请确认",
                })

    # ── Phase 2: 用更新后的 name 重新分组 ────────────────────────────
    groups2: dict[tuple, list] = defaultdict(list)
    for r in rows:
        entry = dict(r)
        final_name = name_map[entry["id"]]
        root2 = final_name.split("·")[0].strip() if "·" in final_name else final_name.strip()
        entry["_final_name"] = final_name
        entry["_root2"] = root2
        groups2[(entry["textbook_id"], root2)].append(entry)

    # ── Phase 3: 合并计划 ─────────────────────────────────────────────
    merge_plans: list[dict] = []
    renamed_ids = {r["id"] for r in rows if name_map.get(r["id"]) != r["name"]}

    total_after = 0
    total_removed_dup = 0
    total_merged_groups = 0

    for (textbook_id, root2), entries in sorted(groups2.items()):
        if len(entries) == 1:
            total_after += 1
            continue

        all_yi: list[dict] = []
        all_sources: list[str] = []
        all_ids = [e["id"] for e in entries]

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

        has_rename = any(i in renamed_ids for i in all_ids)
        merge_plans.append({
            "textbook_id": textbook_id,
            "book_name": entries[0]["book_name"],
            "root": root2,
            "before_cnt": len(entries),
            "before_names": [e["name"] for e in entries],  # 原 name
            "after_name": root2,
            "yixiangs": deduped,
            "sources": all_sources,
            "n_removed_dup": n_removed,
            "ids": all_ids,
            "has_rename": has_rename,  # 是否含改名条目
        })

    # 跨册同名（保留不动）
    name_textbooks: dict[str, list] = defaultdict(list)
    for r in rows:
        name_textbooks[r["name"]].append(r["textbook_id"])
    cross_dups = {nm: tbs for nm, tbs in name_textbooks.items() if len(set(tbs)) > 1}

    # ── 生成报告 ─────────────────────────────────────────────────────
    lines = []
    lines.append("# 文言实词 合并 Dry-Run v2\n")
    lines.append(f"**数据库**: {DB_URL.split('@')[-1]}\n")
    lines.append("**v2 新规则**:\n"
                 "- ① 例句完全相同 → 重复义项\n"
                 "- ② Pattern B 改名（篇目·词 → 词），再重跑册内合并\n\n")

    lines.append("## 1. 总量\n")
    lines.append("| 指标 | 数量 |")
    lines.append("|---|---|")
    lines.append(f"| 合并前总条数 | {total_before} |")
    lines.append(f"| 合并后总条数 | {total_after} |")
    lines.append(f"| 减少条数 | **{total_before - total_after}** |")
    lines.append(f"| 合并组数 | {total_merged_groups} |")
    lines.append(f"| 义项去重（含例句相同规则） | {total_removed_dup} |")
    lines.append(f"| Pattern B 改名条目 | {len(rename_log)} |")
    lines.append(f"| 需人工确认 | {len(needs_review)} |")
    lines.append(f"| 跨册同名（保留不动） | {len(cross_dups)} |")
    lines.append("")

    lines.append("## 2. Pattern B 改名详情\n")
    high_conf = [r for r in rename_log if r["confidence"] == "high"]
    low_conf  = [r for r in rename_log if r["confidence"] == "low"]
    lines.append(f"**自动确认**（confidence=high）: {len(high_conf)} 条")
    for r in high_conf[:25]:
        lines.append(f"  - `{r['old']}` → `{r['new']}` ({r['book'][:12]})")
    if len(high_conf) > 25:
        lines.append(f"  _（共 {len(high_conf)} 条，仅列前25）_")
    lines.append("")
    lines.append(f"**待确认**（confidence=low）: {len(low_conf)} 条")
    for r in low_conf[:20]:
        lines.append(f"  - `{r['old']}` → **`{r['new']}`** ({r['book'][:12]}) ← 请确认")
    lines.append("")

    lines.append("## 3. 合并样例：「以」字\n")
    yi_plans = [p for p in merge_plans if p["root"] == "以"]
    if yi_plans:
        for plan in yi_plans:
            lines.append(f"### {plan['book_name']}\n")
            lines.append(f"合并前 {plan['before_cnt']} 条: {' | '.join(plan['before_names'])}\n")
            lines.append(f"合并后 name=`以`，义项数={len(plan['yixiangs'])}（去重 {plan['n_removed_dup']} 条）:\n")
            for i, yi in enumerate(plan["yixiangs"], 1):
                lines.append(f"  义项{i}: [{yi.get('pos','-')}] {yi.get('yixiang','-')}"
                             f" | 例：{yi.get('liju','-')}")
            lines.append("")
    else:
        lines.append("（无「以」多条记录）\n")

    lines.append("## 4. Pattern B 改名后触发的再合并（重点）\n")
    rename_merges = [p for p in merge_plans if p["has_rename"]]
    lines.append(f"改名后与同册已有词条合并的组：{len(rename_merges)} 组\n")
    for plan in rename_merges[:30]:
        orig = [n for n in plan["before_names"] if "·" in n]
        kept = [n for n in plan["before_names"] if "·" not in n]
        lines.append(f"- **{plan['book_name'][:14]}** `{plan['root']}`:")
        if orig:
            lines.append(f"  改名来源: {' / '.join(orig[:3])}")
        if kept:
            lines.append(f"  原有词条: {' / '.join(kept[:3])}")
        lines.append(f"  合并后义项数: {len(plan['yixiangs'])}（去重{plan['n_removed_dup']}个）")
    if not rename_merges:
        lines.append("（改名后无与原有词条重合的情况）\n")
    lines.append("")

    lines.append("## 5. 例句相同去重案例\n")
    # We report all groups with n_removed_dup > 0
    dup_groups = [p for p in merge_plans if p["n_removed_dup"] > 0]
    lines.append(f"共 {len(dup_groups)} 组有义项去重，样例:\n")
    for plan in dup_groups[:20]:
        lines.append(f"- **{plan['book_name'][:12]}** `{plan['root']}`: "
                     f"去掉{plan['n_removed_dup']}义项 | 原始: {' | '.join(plan['before_names'][:3])}")
    lines.append("")

    lines.append("## 6. 需人工确认列表（不执行改名）\n")
    if needs_review:
        lines.append("| ID | 原名 | 册次 | 提议 | 原因 |")
        lines.append("|---|---|---|---|---|")
        for item in needs_review:
            proposed = item.get("proposed_new", "—")
            lines.append(f"| {item['id']} | `{item['name']}` | {item['book'][:10]} "
                         f"| `{proposed}` | {item['reason']} |")
    else:
        lines.append("（无需人工确认的条目）\n")
    lines.append("")

    lines.append("## 7. 合并计划概览（按条数排序，前 60）\n")
    lines.append("| 册次 | 词根 | 合并前 | 义项数 | 含改名? |")
    lines.append("|---|---|---|---|---|")
    for plan in sorted(merge_plans, key=lambda p: -p["before_cnt"])[:60]:
        flag = "✓改" if plan["has_rename"] else ""
        lines.append(f"| {plan['book_name'][:12]} | {plan['root']} "
                     f"| {plan['before_cnt']}条 | {len(plan['yixiangs'])} | {flag} |")
    lines.append("")

    lines.append("## 8. 完整合并计划 JSON\n")
    lines.append("```json")
    summary = [{
        "book": p["book_name"], "root": p["root"],
        "before": p["before_cnt"], "after_yixiang": len(p["yixiangs"]),
        "removed_dup": p["n_removed_dup"],
        "names_before": p["before_names"],
        "ids": p["ids"],
        "has_rename": p["has_rename"],
    } for p in merge_plans]
    lines.append(json.dumps(summary, ensure_ascii=False, indent=2))
    lines.append("```")

    report = "\n".join(lines)
    out_path = os.path.join(os.path.dirname(__file__), "wenyan_merge_preview_v2.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(report[:5000])
    print(f"\n\n--- 完整报告 → {out_path} ---")
    print(f"合并前: {total_before}  合并后: {total_after}  减少: {total_before - total_after}")
    print(f"合并组数: {total_merged_groups}  义项去重: {total_removed_dup}")
    print(f"Pattern B改名: {len(rename_log)} (high={len(high_conf)}, low={len(low_conf)})")
    print(f"需人工: {len(needs_review)}  跨册保留: {len(cross_dups)}")


if __name__ == "__main__":
    asyncio.run(run())
