# Brief 3: CTSF 文本内容导入 Mneme 生产库（tag: CTSF3）

前两轮（codex，目录 /data/soffy/projects/mneme-ctsf）报告完成但生产库实际 0 条，报告是编造的。这一轮只做文本内容，媒体以后再说（/data 只剩约 7G，不要下载音频/图片包）。

## 背景
- Mneme 后端：/data/soffy/projects/mneme（生产！容器 mneme-api-1、mneme-db-1）。先读 STATUS.md、CLAUDE.md、alembic 模型（textbooks、knowledge_units、question_records、reading_passages 等）和已有的内容导入脚本（scripts/ 下 import/ingest/ku 相关），照现有入库路径走。
- 上游：git clone --depth 1 https://github.com/wuwangzhang1216/ChinaTextbookStudyFree 到本目录 upstream/（约 150MB，含 output/*/outlines、output/*/quizzes）。另从 release v1.2.0-assets 只下载 data.zip 和 data-source.zip（共约 6MB，含 passages/stories 源 JSON），用 gh 或 curl。不要下载 audio/story-images/textbook-pages。
- 前两轮的 scripts/import_ctsf*.py 在 /data/soffy/projects/mneme-ctsf/scripts，可参考但不可信。

## 步骤
1. pg_dump 生产库到 /data/soffy/backups/mneme-pre-ctsf3-<时间>.sql.gz，确认 >100MB。
2. 写 scripts/import_ctsf.py（幂等）：四科教材（数学人教1-6、语文统编1-6、英语PEP3-6、科学教科1-6，共 44 册）→ 教材/单元/课节/KU；6,545 道单元练习 + 1,226 道故事阅读题 → question_records；779 篇课文 + 284 篇故事 → reading_passages。每行都要有可查询的来源标记 'ctsf-v1.2.0'：表里有 source 列就用；没有就用 metadata/JSON 字段或 id 前缀 ctsf-，并在报告写明每张表用哪种标记。已有非 CTSF 数据一律不改不删。
3. 先清掉前两轮可能残留的 CTSF 行（只删带 ctsf 标记的），再导入。
4. 写 scripts/verify_ctsf.sql：每张表按标记 count(*)，再各抽 2 条样本（题干/标题前 40 字）。执行：`docker exec -i mneme-db-1 psql ... < scripts/verify_ctsf.sql > verify_ctsf.out 2>&1`，把 verify_ctsf.out 原样贴进报告。数字必须来自这个文件，不得手写。
5. 写 scripts/remove_ctsf.py（按标记删除，不执行）。

## 验收
- verify_ctsf.out 中题目 ≥ 7,000、课文+故事 ≥ 1,000、教材 = 44。达不到就写清原因并标 BLOCKED，不要谎报。

## 规则
不 downgrade，不重启/重建活容器，不改 tunnel；需要 alembic 加列/加表时可以写迁移并执行（只加不删），报告写明。不 push/merge，CPU-only，不调付费 API，禁止 mock，只在本目录工作，每步 commit。/data <5G 立即停。

## 报告
CTSF3_REPORT.md：备份路径、每表标记方式、verify_ctsf.out 原文、remove 用法、遗留问题。最后一行 `CTSF3 DONE` 或 `CTSF3 BLOCKED: <原因>`。
