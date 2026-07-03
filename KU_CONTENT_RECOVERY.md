# KU 内容资产：丢失复盘 + 复现机制 + 再生成 Runbook

> 审计 2026-07-03 头号缺陷记录与收口。**权威设计** = `MNEME_MASTER_DESIGN.md`。

## 发生了什么

运行库 `knowledge_units` / `knowledge_clusters` **实测 0 行**，MinIO 教材桶为空。
git 历史证明 12,573 个 KU（数学 ~2395、物理 ~1551，含 `rich_content`"讲透"内容）确实产出过。

**根因**：`docker-compose.yml` 的 db 用**匿名卷**、minio/redis **无卷** → `docker compose down`/重建即清零。
且 KU 全部由一次性脚本（`extract_*_ku_batch.py`、`enrich_ku_content.py`）直接写库，
**从未固化进 migration/seed** → `alembic upgrade head` 到全新库只会得到 0 KU。

## 已修复的部分（本批次）

1. **不再易失**：db/minio/redis 全部改**命名卷**（`audit-fix/p0-1`），`docker compose down` 不再清零。
2. **可备份**：`scripts/backup.sh`（pg_dump + MinIO 快照 + 轮转），建议挂 crontab 每日跑。
3. **可复现为 git 资产**：
   - `scripts/export_ku_package.py` — 库内 KU → 每教材一个 JSON 包（**含 rich_content 等全部内容字段**）。
   - `scripts/import_ku_package.py` — 幂等回放 JSON 包（已扩展支持 rich_content 往复）。
   - `tests/test_ku_package_roundtrip.py` — 守卫 export/import 字段契约对称，防单侧漂移。

## ⚠️ 仍需人处理（Needs Human）：再生成丢失的 12,573 KU

**为何未在本批次完成**：再生成依赖 LLM 抽取 + rich_content 生成——
- DeepSeek key 当前 401（余额不足/失效）；
- 本机 Ollama `qwen2.5:7b` 走 CPU，单 KU >120s，全量 ~数天且质量降级。

属**外部依赖阻塞**（有效 LLM key 或空闲 GPU），非工程缺口。

### 再生成步骤（拿到 LLM key / GPU 后）

```bash
set -a; . ./.env; set +a
# 1. 教材 PDF 已在 MinIO（见 scripts/import_textbooks.py / P0-3）。抽取 KU：
#    数学/物理参照现有 extract_*_ku_batch.py 流程
# 2. 生成"讲透" rich_content（8 线程/幂等/断点续传）：
LLM_BASE_URL=... LLM_MODEL=... LLM_API_KEY=... \
  python scripts/enrich_ku_content.py --subject math --all-grades
python scripts/qc_rich_content.py          # 内容质检门（破损/拒答/LaTeX 不配对/过薄）
```

### 再生成后：固化为永久资产（关键，别再丢）

```bash
# 导出为 git 可追踪的内容包并提交
docker compose exec -T -e DATABASE_URL_SYNC=postgresql://postgres:postgres@db:5432/mneme \
  api python scripts/export_ku_package.py --out data/ku_packages
git add data/ku_packages && git commit -m "content: KU 内容包快照"
# 从此新库可 100% 复现：for f in data/ku_packages/*.json; do import_ku_package.py "$f"; done
```

> 注：脚本用 psycopg2（同步驱动，与既有 import 脚本单源一致）。容器内需
> `pip install psycopg2-binary`（未进镜像依赖，避免改 Master §9 技术栈；如需常驻请先改 Master 再加）。
> `build_package` 为纯函数、无 DB 依赖，往复测试不需驱动。
