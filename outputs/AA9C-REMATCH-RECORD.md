# AA.9c 题库重挂（re-link）—— 操作记录（prod 数据变更）

**时间**：2026-07-17
**对象**：prod `mneme-db-1` / `wrong_questions.knowledge_points`
**授权**：用户 2026-07-17 选"重挂"（AA.9b 剔除后把孤儿题找回正确 KC）。

## 做了什么
AA.9b 剔错链后，批次 265 题里 **162 道高一题彻底掉出 g10-a**（孤儿）。对每道孤儿题：
1. **匹配**：qwen 从 165 个 g10-a KC 目录里选最契合的一个（或 idx=0 表示无契合）；
2. **验证**：再用相关性判别确认"该题确实主要考查所选 KC"；
3. 两道门都过 → **新增**该 g10-a 链（`knowledge_points || {kc_id: name}`，只增不删不改）。

结果：**重挂 32 / 孤儿 162**；其余 130 道无契合 g10-a KC（多为跨课程：立体几何 / 算法框图 /
数论 / 解析几何），**正确留孤儿**。抽查通过（如"映射 f:x→-x²+2x…"重挂到 ku004 函数的概念）。
有高一可服务题的 g10-a KC：**30 → 35**。

## 可回滚
- **报告**：`outputs/aa9c_rematch_report.json` = {orphans, relinked, added_pairs:[[qid,kc_id,name]...]}。
- 回滚：对每个 added_pair `UPDATE wrong_questions SET knowledge_points = knowledge_points - kc_id
  WHERE id=qid`（只删本次新增的 key）。
- 注：本次是**纯新增链**，不影响 AA.9b 的剔除（那份快照 aa9b_relink_snapshot.json 仍是更早的
  全量原值回滚点）。

## 备注
- 匹配保守（两道门）：宁可留孤儿也不误挂，故只救回 ~20%；这符合"题库本就大量跨课程噪声"的现实。
- 第一次运行因 jsonb_build_object 参数类型未 cast 报错、0 写入（已回滚）；本记录对应修 cast 后的重跑。
