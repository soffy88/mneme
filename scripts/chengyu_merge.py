"""
成语去重合并脚本
- 同一成语（不同课文出现）合并为一条
- 出处教材列表写入 rich_content["sources"]
- 保留策略：优先 cluster=成语典故，其次 name 最短（最干净），最后按 id 排序
- 无 FK 约束，直接 DELETE 冗余条目
"""
import asyncio
import json
import sys
import asyncpg

DB_URL = "postgresql://postgres:postgres@localhost:5433/mneme"

def extract_idiom_name(name: str) -> str:
    """提取真实成语名（处理各种格式）"""
    parts = [p.strip() for p in name.split("·")]
    # 篇名·成语·真实成语名（含 《》 或不含）
    if len(parts) >= 3 and parts[1] == "成语":
        return parts[2]
    # 成语·xxx（分类前缀）
    if len(parts) >= 2 and parts[0] == "成语":
        return parts[1]
    # xxx·附注（拼音/释义后缀）→ 第一部分是成语
    if len(parts) >= 2:
        return parts[0]
    return name.strip()


async def run(dry_run: bool = True):
    conn = await asyncpg.connect(DB_URL)

    # 1. 拉取所有 chengyu
    rows = await conn.fetch("""
        SELECT ku.id, ku.name, ku.description, ku.rich_content,
               t.book_name, kc.name AS cluster_name
        FROM knowledge_units ku
        JOIN textbooks t ON ku.textbook_id = t.id
        JOIN knowledge_clusters kc ON ku.cluster_id = kc.id
        WHERE ku.ku_type = 'chengyu' AND t.subject = 'chinese'
        ORDER BY ku.id
    """)

    # 2. 按真实成语名分组
    groups: dict[str, list] = {}
    for r in rows:
        key = extract_idiom_name(r["name"])
        if key not in groups:
            groups[key] = []
        groups[key].append(dict(r))

    singles = {k: v for k, v in groups.items() if len(v) == 1}
    dupes   = {k: v for k, v in groups.items() if len(v) > 1}

    print(f"总条数: {len(rows)}")
    print(f"唯一成语: {len(groups)}")
    print(f"无重复: {len(singles)}")
    print(f"有重复成语: {len(dupes)}，冗余条数: {sum(len(v)-1 for v in dupes.values())}")
    print()

    merge_ops = []  # (keep_id, delete_ids, books_list, idiom_name)

    for idiom, entries in sorted(dupes.items()):
        # 排序：成语典故 cluster 优先，然后 name 最短，然后 id 字典序
        def sort_key(e):
            return (
                0 if e["cluster_name"] == "成语典故" else 1,
                len(e["name"]),
                e["id"],
            )
        entries.sort(key=sort_key)
        keep   = entries[0]
        others = entries[1:]

        books = sorted({e["book_name"] for e in entries})
        delete_ids = [e["id"] for e in others]

        merge_ops.append((keep["id"], delete_ids, books, idiom))

        if dry_run:
            print(f"  成语: {idiom}  重复={len(entries)}")
            print(f"    ✅ 保留: {keep['id']}  [{keep['name']}]  @{keep['cluster_name']}")
            for o in others:
                print(f"    🗑  删除: {o['id']}  [{o['name']}]")
            print(f"    📚 出处: {' / '.join(books)}")
            print()

    if dry_run:
        print(f"=== DRY-RUN 完毕，共 {len(merge_ops)} 组合并，可减少 {sum(len(d) for _,d,_,_ in merge_ops)} 条 ===")
        await conn.close()
        return

    # 3. 执行合并
    merged = 0
    deleted = 0
    async with conn.transaction():
        for keep_id, delete_ids, books, idiom in merge_ops:
            # 更新 rich_content 写入 sources 列表
            existing_rc = await conn.fetchval(
                "SELECT rich_content FROM knowledge_units WHERE id=$1", keep_id
            )
            rc = json.loads(existing_rc) if existing_rc else {}
            rc["sources"] = books
            await conn.execute(
                "UPDATE knowledge_units SET rich_content=$1 WHERE id=$2",
                json.dumps(rc, ensure_ascii=False), keep_id,
            )
            # 删除冗余
            for did in delete_ids:
                await conn.execute("DELETE FROM knowledge_units WHERE id=$1", did)
            merged  += 1
            deleted += len(delete_ids)

    print(f"合并完成: {merged} 组，删除 {deleted} 条冗余，剩余 {len(rows)-deleted} 条")
    await conn.close()


if __name__ == "__main__":
    dry = "--execute" not in sys.argv
    if dry:
        print("=== DRY-RUN 模式（传 --execute 正式执行）===\n")
    asyncio.run(run(dry_run=dry))
