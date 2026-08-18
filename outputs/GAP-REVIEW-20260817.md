# GAP-REVIEW-20260817 · 对标标杆差距审查（代码级实证）

> 审查方式：通读算法内核源码（`oprim/_cognitive`、`fsrs_engine`、`oskill/cognitive_state`）、
> 护城河实证（`scripts/moat_eval` exp1–4）、判分 CI 数据（`outputs/s1_grading_failures.json`）、
> `BENCHMARK_REPORT.md`（30+ 竞品）、服务层关键文件。所有结论均有代码/数据出处，非猜测。
> 执行看板：TASKS.md Epic GH。

---

## 一、核验后确认的真优势（代码里确实有，非 PPT）

| 主张 | 代码证据 |
|------|---------|
| 掌握度唯一路径 | `tests/test_partner_no_self_judged_mastery.py` AST 结构性断言；`PgStore.get_or_create` `FOR UPDATE`；双 BKT 写路径守卫 `test_mastery_write_path_guards` |
| 确定性优先 | 7 个 `solve_*` 内核 + `sandbox_selfcheck.check_or_die()` 全仓 AST 扫描；红线测试含"mock LLM 给错值仍以内核为准" |
| 诚实的负结果 | exp4 FIRe-lite 未达接线门槛（压缩 4.7–6% < 10%，对抗世界保留率 -4.8pp）→ 默认关；exp2 Powell 过拟合如实记录为负结果 |
| 判分 CI 门 | 真题 fixture 119 题，准确率 92.4%（阈值 90%） |
| 合规内建 | purge/grants/audit 三件套 + <14 岁闸门测试 |

## 二、差距清单（按致命度排序）

### 🔴 P0 — 护城河是"图纸"，还没通水

**P0-1 零真实学生数据 → 所有核心指标都是合成数**
- AUC：合成 ≥0.65（CI 门），目标 0.77，对标线 0.80（ASSISTments BKT 水平）——真实数据一次没跑过
- FSRS 个性化：`_MIN_SPACED_REVIEWS=400` 门槛，无真实用户永远触发不了
- FIRe / RCT / Cohen's d > 0.35：全部以真实数据为前提，全部未启动
- 竞品对照：Cognitive Tutor 数十年 RCT（g=0.3–0.5）、ASSISTments g=0.33、松鼠AI 对照实验。Mneme 效果证据目前为 0
- **可立即推进的子项**：用 ASSISTments 公开数据集做外部效标验证（不需要真实学生）→ Epic GH-1

**P0-2 线上 tutor/chat 链路断裂**
- 活容器 `import oservi` 失败（vendor/obase 无 `IDaemon_Bus`），线上 OpenAPI 24 个 /mcp、0 个 chat
- 三个选项（A 补符号+挂载需重启 api / B chat 去 oservi 化 / C 接受仅 dev）挂起等人决策
- ⚠️ 需人决策，不擅动（本机即生产）

### 🟠 P1 — 内容/覆盖度差距

**P1-1 题库规模差 4–5 个数量级**：猿辅导 15 亿 / 学而思 10 亿+；Mneme 22,248 条 CMM + 3,019 条已挂 KU
**P1-2 `solve_*` 只覆盖 7 类高中题族**：初中几何证明/应用题/选择填空确定性覆盖空白，红线之外大量题型实际靠 LLM
**P1-3 多学科虚胖**：英语 KU 空、Stratum 语料空、语文靠成语脚本、物理变式 prompt 未调优
**P1-4 判分 92.4% vs ALEKS 97%**：fixture 仅 119 题，样本小置信区间宽；9 题失败未解

### 🟡 P2 — 产品/增长机制差距

**P2-1 无留存引擎**：无游戏化闭环、零留存数据验证（对标 Duolingo Birdbrain + 每周百次 A/B）
**P2-2 分发渠道为零**：PA-2 真实 webhook 至今未验（等用户提供 WeCom/Feishu URL）
**P2-3 单一模型依赖**：只接阿里云 Qwen，无垂类微调；自家 benchmark §5.4 把此列为反模式
**P2-4 可观测性缺位**：自定 P99 < 500ms 目标，无压测/延迟监控落地

### 🟢 P3 — 工程质量尾巴

**P3-1** 全量 26 failed + 2 errors 长期挂账（ship-gate 四条之一"测试=生产 CI 收敛"）
**P3-2** DKT 影子模型未启动，连影子评估管道都没预建
**P3-3** recognition 维度（M-G）无独立验证实验（moat_eval 4 实验没一个测它）

## 三、结论

> **飞轮的每一个齿轮都验证过了，唯独没有水。** 白盒双内核是真的（工程纪律罕见地严），
> 但对标指标（AUC 0.80 / RMSE 0.15 / Cohen's d 0.35 / Top-3 命中 85%）一个都没有
> 真实数据支撑。最接近的开源基准（OATutor/ASSISTments）恰有公开真实数据集——
> 用公开数据集做外部效标验证是不需要真实学生就能推进的第一步。

## 四、执行优先级（Epic GH）

1. **GH-1 ASSISTments 外部 AUC 对标**（零生产风险，纯回放）——本轮立即执行
2. **GH-2 recognition 维度独立验证实验**（exp6，纯模拟）——本轮立即执行
3. **GH-3 DKT 影子评估管道预建**（不训练，只建回放+对比脚手架）——本轮立即执行
4. P0-2 chat 断链修复 —— ⚠️ 需人决策（重启活容器）
5. 真人 pilot 启动 —— ⚠️ 需人决策（运营动作）
6. 题库/判分扩面 —— pilot 后按真实缺口定向补
