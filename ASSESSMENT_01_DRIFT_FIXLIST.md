# 文档–代码漂移修订清单（SSOT 对齐）

> 生成：2026-06-28 · 依据：实地核验 mneme 仓库 + 内核仓库 `platform/3O/`
> 原则：Master 是 SSOT。**事实性漂移 → 改文档对齐代码**；**范围/契约性漂移 → 需人决策后再统一**。
> 用法：逐条勾选；每条给了【证据】+【修法】+【归属】。

---

## ✅ 处理进度（2026-06-28）
- **D1 AUC 0.77 失实** → 改文档：CLAUDE.md / Master(230,647) / README(63) 全改为"合成数据 AUC≥0.65，0.77 为目标"。✅
- **D3 API 契约漂移** → 修 Master `mastery-curve`→`mastery/curve`；新增 `scripts/dump_routes.py`（从 FastAPI 导出实际 66 条路由，根治手抄）；§8 加"以代码为准"说明。✅
- **D4 longitudinal_analysis_workflow** → 改 Master §6.4：标注现状由 `oskill.longitudinal_pattern`+`/v1/patterns` 实现，未单独建 omodul。✅
- **D5 BKT 双源** → 已收敛单源（R.3，`bkt.py` re-export `_cognitive` + 守卫测试）。✅
- **D7 KC 计数** → 改 Master 附录A：澄清 KC(建模) vs KU(内容,数学~2395/物理~1551) 两套粒度。✅
- **D8 test_engine.py 双份** → 删根目录死文件（`from core import bkt` 已失效）；文档指向 `tests/`。✅
- **D2 MVP 范围（战略）** → 已决策：数学单科聚焦、其它冻结（R.1/R.4）。
- **D6 socratic_loop/verify_step 接线** → 仍需核验（红线相关，未在本轮处理）。

---

---

## 🔴 高优先（影响对外可信度 / 战略判断）

### [ ] D1 · AUC 0.77 失实（应为 0.65，且是合成数据）
- **文档侧**：`MNEME_MASTER_DESIGN.md:230`「下一题预测 **AUC ≈ 0.77**」、`:647`「实现并验证（AUC≈0.77）」；`CLAUDE.md:19`「已验证（AUC≈0.77）」；`README.md:63`。
- **代码侧**：`platform/3O/oprim/tests/test_cognitive.py:166` `assert auc >= 0.65`；mneme 内 `tests/test_engine.py` / 根 `test_engine.py` 同为 `> 0.65`。且该测试用 `np.random` **合成数据**（`test_cognitive.py:126-166`），不是真实学生数据。
- **修法（改文档）**：统一表述为「合成数据回归 AUC ≥ 0.65（真实数据待验证）」。**不要**在没有真实数据前对外写 0.77。把 0.77 作为"目标"而非"已验证结果"。
- **归属**：文档 · 立即可改。

### [ ] D2 · MVP 范围漂移：文档"广东数学单科" vs 代码"四科扩张"
- **文档侧**：`MNEME_MASTER_DESIGN.md:616`「MVP 收窄单地区单科，验证后复制」；`:623` 附录A「广东高中数学…」；Epic 0–5 全标 MVP 且围绕数学。
- **代码侧**：`services/main.py` 已上线物理(受力分析 1363-1398)、阅读引导(1401)、作文(1261)、口语(1299)、教材阅读器(1446+)；数学 KU 2395 / 物理 KU 1551 已入库。
- **本质**：这不是"文档过时"，是**战略问题**——MVP 验证闭环（数学+冷启动钩子+真实用户）从未闭合，资源摊到了多科半成品。
- **修法（需人决策）**：二选一并写回 Master —— (A) 正式承认"多科平行"为新策略，更新路线图与风险表；或 (B) 冻结其余学科，回收到数学单科先验证。**推荐 B**（见交付物②）。
- **归属**：产品决策 · 阻塞，需你拍板。

### [ ] D3 · API 契约不全/路径不符
- **文档侧**：`MNEME_MASTER_DESIGN.md:476` 写 `GET /v1/mastery-curve/{sid}/{kc}`（中划线）。§8 共列约 20–25 条路由。
- **代码侧**：`services/main.py:243` 实际是 `/v1/mastery/curve/...`（斜杠）；实际路由 **62 条**，文档缺 `/v1/knowledge-points`、`/v1/physics/*`、`/v1/reading/*`、`/v1/essay/*`、`/v1/speaking/*`、`/v1/textbook-files/*`、`/v1/highlights`、`/v1/reading-notes`、`/v1/instant-solve`、`/v1/error-journal`、`/v1/daily-plan` 等。
- **修法（改文档）**：把 §8 标题改为「核心 API（节选）」并补一节"实际路由全表（自动生成）"，或用 `scripts/dump_routes.py` 从 FastAPI `app.routes` 导出 openapi 贴附，避免手抄漂移。修正 `mastery-curve` → `mastery/curve`。
- **归属**：文档 · 立即可改（建议加一个导出脚本根治）。

---

## 🟠 中优先（架构契约 / 验证证据）

### [ ] D4 · `longitudinal_analysis_workflow`（omodul）不存在
- **文档侧**：`MNEME_MASTER_DESIGN.md:313` 列其为 omodul（带 decision_trail 支柱）。
- **代码侧**：`platform/3O/omodul/` 无此文件；实际是 `platform/3O/oskill/oskill/longitudinal_pattern.py`（**oskill 纯算法**，非 omodul 业务事务）。服务层 `GET /v1/patterns` 经它产出。
- **修法（改文档 or 补码）**：(A) 改 Master §6.4 把它从 omodul 表移除，在 §6.3 注明 `longitudinal_pattern` 为现状；或 (B) 若确需 omodul 级事务（持久化 learning_patterns + decision_trail），补 `longitudinal_analysis_workflow.py` 薄包装。**推荐 A**（当前 oskill+服务层已够用）。
- **归属**：文档为主。

### [ ] D5 · 内核存在 BKT/KCState 双份实现（隐患）
- **代码侧**：`platform/3O/oprim/oprim/bkt.py` 与 `platform/3O/oprim/oprim/_cognitive.py` **各自定义** `KCState` 与 `bkt_update`。两份默认先验还不同（`bkt.py` 注释 vs `_cognitive.py:26-29` `p_init=0.20/p_transit=0.20/p_guess=0.15/p_slip=0.12`）。
- **风险**：未来改一份漏另一份；AUC 测试用的是哪份需确认（`test_cognitive.py` 导入 `bkt_new_state/bkt_predict_correct`，疑似 `_cognitive.py`）。
- **修法（补码）**：确定唯一权威实现，另一份改为 re-export；加一条测试断言两入口指向同一函数。**这是交付物③ BKT+IRT 的前置项**——改之前必须先收敛到单源。
- **归属**：内核代码 · 需先做。

### [ ] D6 · `socratic_loop` / `verify_step` 集成 —— 需核验
- **文档侧**：`MNEME_MASTER_DESIGN.md:301` 把 `socratic_loop` 列为 oskill = `socratic_turn`(循环)+`verify_step`+情绪检测；`:261`「`socratic_loop` 调 `verify_step` 校验每一步」。
- **代码侧（两次探查结论不一致，故标核验）**：一次探查未找到独立 `socratic_loop` 函数；另一次报告 `platform/3O/oskill/oskill/socratic_loop.py` 存在但 `verify_step` 是否真接线存疑。**红线**「错误中间步由 verify_step 拦截」是合规级要求，不能停留在框架。
- **修法（先核验再定）**：人工确认 `socratic_loop.py` 是否真实调用 `verify_step` 且有"诱导也不泄露/错误步被拦截"测试（CLAUDE.md 红线要求）。无则补码+补测试；有则文档无需改。
- **归属**：内核代码 · 先核验。

---

## 🟡 低优先（叙述性 / 计数）

### [ ] D7 · KC 计数口径不一
- **文档侧**：`MNEME_MASTER_DESIGN.md:623`「已实现 29 个二级知识点…MVP 扩展目标 ≥50」。
- **代码侧**：`data/guangdong_math_kc.py` 实际 KC 数 + DB KU（数学 2395 / 物理 1551）已远超。KC（粗粒度）与 KU（细粒度）两套粒度并存（见记忆 `project_knowledge_system_refactor`）。
- **修法（改文档）**：附录A 更新为现状计数，并明确 KC vs KU 的粒度关系（避免读者混淆"29"与"2395"）。
- **归属**：文档。

### [ ] D8 · `test_engine.py` 双份且根目录版过时
- **代码侧**：根 `test_engine.py`（`from core import bkt`，已失效路径）与 `tests/test_engine.py`（`from oprim import bkt`）并存。文档/README 引用混乱（`README.md:16` 指 `tests/test_engine.py`）。
- **修法（删码+对齐文档）**：删根目录过时副本，文档统一指向 `tests/test_engine.py`。
- **归属**：代码+文档。

---

## 建议的处理顺序
1. **先做无争议的文档修正**：D1、D3、D7（半天）。
2. **核验类**：D6（先看代码再决定），D5（收敛 BKT 单源，BKT+IRT 前置）。
3. **薄改**：D4、D8。
4. **战略决策**：D2 —— 需你拍板，决定后整段重写 Master §12 路线图。
