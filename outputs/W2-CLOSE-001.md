# W2 关闭记录（W2-CLOSE-001）

**日期**：2026-07-17
**状态**：W2 **收口**（功能就绪、全部上线 sxueji.com）。
**收口性质**：用户对 studio **功能验收通过**。收口 **≠** 完整真人链路证实。

---

## ⚠️ W8–W12 判定：维持红

- **W8–W12 未转绿。** 完整 S3-C 真人 pilot（Wiki + 孩子经 sxueji.com/studio/learn 走
  P1–P5）**未跑**。
- 用户 2026-07-17 对 studio 功能直接判"验证通过"以收口 W2 —— 但**功能验收 ≠ 真人链路证实**。
- **收口不因此改判定**：W8–W12 保持红，待真人 pilot 实跑后方可转绿。

---

## 19 提交清单（0524b37 → 84e2fe6）

| commit | 内容 |
|---|---|
| 0524b37 | AA.1 一套登录 + /mcp 每用户鉴权（关 IDOR） |
| c5d804c | 修 API base（同源空串被 `||` 回退成 localhost） |
| 221d0e9 | 缺省路径改定量 KC（修"提交后不动了"） |
| e96c1dd | AA.2 定性 verifier 接线 |
| 78d880c | AA.3 KaTeX 数学渲染 |
| c6d7b47 | 缺省路径加回 ku004（定性） |
| 8057df3 | TASKS 归档 AA 段 |
| 931e184 | AA.7 题库自足过滤（修占位"标识"） |
| f796f51 | TASKS AA.7/AA.8 |
| 2b78290 | AA.8 判分提速 50s→~7s（关思维链） |
| fbca5a8 | 出题 LLM 兜底也关思维链 ~50s→~2s |
| bbc85e9 | NextObjective 自愈坏 pending |
| dc78d06 | TASKS AA.6 功能验收收口 |
| 76283b5 | AA.5 GetPath 按档案拉学习路径 |
| bbfd536 | AA.9 题库清洗第一步（恢复选项+只出高一） |
| 9d3e87c | AA.9b 相关性重匹配（剔 266 错链） |
| 1d0e7c4 | AA.9c 重挂（32 孤儿题） |
| 6623654 | AA.9c 撤存疑 #17 → 净重挂 31 |
| 84e2fe6 | AA.10 判分核查+修 10%→90% |

（更早：8d74e47 = W2b S3-B studio 镜像+容器落地 + Caddy 需求交 aegis。）

---

## AA 段成果

| 项 | 内容 | 结果 |
|---|---|---|
| AA.1 | 一套登录 + /mcp 每用户鉴权 | 复用 mneme 会话；**关掉现存 IDOR**；auth 抽 services/auth_deps.py 单源 |
| AA.2 | 定性 verifier 接线 | 概念解释题真判分（含 evidence 锚定 + span 偏移修）、清 pending、前进 |
| AA.3 | KaTeX 数学渲染 | 题干 `$…$`/`$$…$$` 正常显示（OMarkdownRenderer 崩，直用 katex） |
| AA.5 | GetPath 按档案拉路径 | 120 KC 课程路径、按 cluster 章节序、起点集合基础；派生式不落表 |
| AA.7 | 题库自足过滤 | 排图形/占位"标识"题 |
| AA.8 | 判分/出题提速 | **50s→~7s / ~2s**（qwen3.7-plus 关思维链） |
| AA.9 | 题库清洗第一步 | 恢复选项（profiler.options）+ 只出高一 |
| AA.9b | 相关性重匹配 | 剔 266 条错链（68% 跑题，可回滚快照） |
| AA.9c | 重挂 | 净重挂 31 孤儿题（match+verify 两道门，抽查后撤 1 存疑） |
| AA.10 | 判分核查+修 | **判对率 10%→90%**（grade_math LaTeX 归一 + serve 只出可判分题） |

---

## 四项遗留

1. **S3-C 完整真人 pilot 未跑** —— Wiki + 孩子实操走 P1–P5，W8–W12 真人转绿。CC 不代跑。
2. **判分残 ~10%** —— 嵌套 LaTeX / 丢符号脏数据 / 文字答案，难修，不影响主流。
3. **题库真题覆盖 34/165 KC** —— 其余 KC 由 LLM 自足生成兜底（数据本身噪声大，非清洗不到位）。
4. **选择题 UI** —— 仍是文本框（选项拼在题干里），未做单选按钮。

---

## 可回滚快照 / 记录索引（outputs/）

| 文件 | 用途 |
|---|---|
| aa9b_relink_snapshot.json | AA.9b 剔链前 265 题原 knowledge_points（回滚点） |
| aa9b_relink_report.json | AA.9b 剔除对清单 |
| AA9B-RELINK-RECORD.md | AA.9b 操作记录 + 回滚法 |
| aa9c_rematch_report.json | AA.9c 重挂新增对（回滚=删新增 key） |
| AA9C-REMATCH-RECORD.md | AA.9c 操作记录（含撤 #17） |
| seed_purge_snapshot.json / SEED-PURGE-RECORD.md | 199 种子用户清理记录 |
| S3B-CADDY-REQUIREMENT.md | 交 aegis 的 caddy 路径路由需求 |
| BLOCKS-BUG-OMarkdownRenderer-runSync.md | blocks bug（数学改用 katex） |
| S3-BLOCKER-REPORT.md | 早期 S3 阻断报告 |

---

## 挂起项交接 W3

1. **3× daily_plan 测试失败** —— 时间依赖/环境相关，nightly 会红（见 Z.5 语境）。
2. **oservi assemble 双注册 bug** —— `agentic_loop` 重复注册致 AgenticLoopEngine 缺 turn_handler；
   W2a 用实例 `.assemble()`+`.session()` 绕过，真修留 W3（已报 Wiki）。
3. **blocks OMarkdownRenderer bug** —— Next16/React19 下 `runSync finished async` 崩；studio 数学
   改用 katex 绕过；待 blocks 修（BLOCKS-BUG-OMarkdownRenderer-runSync.md）。
4. **main.py pre-session 簇** —— main.py working tree 里混着 Wiki 未提交改动（SPA 挂载/端点等）；
   AA.1 只提交了 auth 抽取的 3 个 hunk，其余未提交，需 Wiki 认领。
5. **knowledge_points 漂移修未提交** —— schema 漂移（knowledge_points ↔ knowledge_units）相关修
   未提交，需梳理。
6. **docker-compose.override.yml** —— 挂 /opt/oservi_pkg + PYTHONPATH，现活在 prod api；来源/去留
   需确认。
