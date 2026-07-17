# AA.9b 题库相关性重匹配 —— 操作记录（prod 数据变更）

**时间**：2026-07-17
**对象**：prod `mneme-db-1` / `wrong_questions.knowledge_points`
**授权**：用户 2026-07-17 选"题库彻底修·分两步"，第二步 = LLM 相关性重匹配剔错链。

## 做了什么
对 g10-a 教材下、`profiler.grade='高一'`、非图形的 **392 个 (题, KC) 对**，用 qwen
（qwen3.7-plus，关思维链）逐对判"这道题是否主要考查该 KC"：
- **判相关（保留）**：126
- **判跑题（移除该链）**：266 → 从对应题的 `knowledge_points` 移除该 KC key
- **判别出错**：0（出错则保守保留，不误删）

移除方式：`UPDATE wrong_questions SET knowledge_points = knowledge_points - :kc WHERE id=:id`
（只删 KC key，不删题；题若还挂着别的相关 KC 仍在那 KC 下可服务）。

## 效果
- 清洗后 ku001(集合) 等 KC 只剩本知识点的题（坐标几何/程序框图等跑题已剔）。
- 有 ≥1 高一可服务题的 g10-a KC：**30 / 78**（其余 KC 由 RequestQuestion 的 LLM 自足生成兜底）。

## 可回滚
- **快照**：`outputs/aa9b_relink_snapshot.json` = {question_id: 原 knowledge_points}（265 题全量原值）。
- **报告**：`outputs/aa9b_relink_report.json` = {pairs, relevant, removed, removed_pairs[...]}。
- 回滚：遍历快照，对每个 question_id 用原 knowledge_points 覆盖回写即可。

## 遗留 / 后续
- 未做"重挂"（把跑题的题重新匹配到其**正确** KC）——只做了剔除。若要把这些题也用起来，
  再跑一轮"给无正确链的题找对 KC"的匹配（更大活）。
- 未成年/合规无关（题库题非 PII）。
