# 数学单科闭环 · 前端任务分解（P0）

> 目标：把"上传试卷 → 看见薄弱 → 看见成长 → 今日目标 → 苏格拉底顿悟 → 努力看板"这条**学生认知闭环**在数学学科端到端做出来。
> 战略理由：数学是 Master 钦定 MVP 主科，后端数据/引擎已就绪（KU 2395 + rich_content + BKT/FSRS），但 `frontend/src/pages/math/` **为空**——护城河（纵向档案可视化）目前完全不可见。
> 依据：实地核验 `frontend/`（App.tsx 路由、physics 页面、components/、api.ts、types.ts）与 `services/main.py` 端点。

---

## ✅ 实施进度（2026-06-28，`tsc -b && vite build` 通过，新文件 0 lint 问题）

**已完成**（数学单科前端闭环，物理/语文零改动）：
- 阶段1：`types.ts` 加 `MATH_KU_TYPE_META`；`pages/math/MathHome.tsx`、`MathLesson.tsx`；`App.tsx` 数学路由+导航；默认落地页改 `/subjects/math`。
- 阶段2：通用 `pages/SocraticDialog.tsx`（SSE 流式 + 逃生出口 + 结束）；动态路由 `/subjects/:subject/socratic`。
- 阶段3：`components/MasteryOverview.tsx`、`GrowthCurve.tsx`（手写 SVG，零图表依赖）、`DailyPlanCard.tsx`；`pages/math/MathDashboard.tsx`（薄弱排序↔成长曲线联动，"镜子"）。
- 阶段4：`pages/math/PaperUpload.tsx`（冷启动钩子，multipart 上传）、`ErrorJournal.tsx`（检索约束，重练走苏格拉底）。
- `api.ts` 扩：`currentStudentId/getMasteryOverview/getMasteryCurve/getDailyPlan/startSocraticForKu/sendSocraticMessage(SSE)/escapeSocratic/endSocratic/uploadPaper/getErrorJournal`。

**有意未做**（不属"数学单科"或需后端环境）：
- M-F7 去 `subject="math"` 硬编码 —— 这是为**其它学科**解阻塞，本次"其它不动"故跳过。
- M-F14 努力看板 —— 依赖的 `GET /v1/effortful-gains` 端点疑缺（后端待补），未建。
- 运行时联调（真实 OCR/SSE/DB）—— 需 `docker compose up` + LLM key，本次以构建+类型为验收，未跑真实后端。

---


---

## 0. 现状结论（可复用度）

| 资产 | 状态 | 对数学的复用度 |
|---|---|---|
| 路由框架 `App.tsx` | 物理/语文已有 `/subjects/<x>/...` 模式 | ⭐⭐⭐⭐ 加几行即可 |
| 知识体系页 `PhysicsLesson.tsx` | 已参数化 `listKUs(subject, studentId)` | ⭐⭐⭐⭐⭐ 改 `subject="math"` |
| 卡片组件 `KCGroup/KUDetailPanel/KUTypeTag/MasteryDot` | 全参数化、学科无关 | ⭐⭐⭐⭐⭐ 直接用 |
| API 客户端 `api.ts` | 统一 `req<T>` + Bearer | ⭐⭐⭐⭐⭐ 扩端点即可 |
| `RichContentView`（讲透内容） | 已接 KU rich_content | ⭐⭐⭐⭐⭐ 数学 1469 条已就绪 |
| **认知闭环 UI**（成长曲线/今日目标/苏格拉底对话/错题本/努力看板） | **全部不存在** | 需新建（但跨学科通用） |
| **数学 `KU_TYPE_META`**（types.ts） | 缺 | 需定义 |

**关键洞察**：知识体系浏览页几乎零成本就能给数学复用；真正的工作量在**认知闭环那五个组件**——而它们正是产品价值所在，且做完可同时点亮物理/语文。所以这不是"给数学补页面"，是"把全平台缺的学生闭环一次补齐，首发数学"。

---

## 阶段 1 · 知识体系可见（0.5–1 天，极低风险）
打通"数学学科入口 + 知识点地图 + 讲透内容"。

- [ ] **M-F1** `types.ts` 加 `MATH_KU_TYPE_META`（参考物理 6 类：concept/law/model/method/formula/… → 数学用 概念/定理/方法/公式/模型/题型；以 DB 里数学 KU 实际 `ku_type` 取值为准，先 `grep` 真实枚举再定）。
- [ ] **M-F2** 新建 `pages/math/MathHome.tsx`（复制 `PhysicsHome.tsx`，改文案+入口卡片，零 API）。
- [ ] **M-F3** 新建 `pages/math/MathLesson.tsx`（复制 `PhysicsLesson.tsx`，`listKUs("math", studentId)`，复用 `KCGroup/KUDetailPanel/RichContentView`）。
- [ ] **M-F4** `App.tsx` 加路由 `/subjects/math`、`/subjects/math/lesson` + 顶部导航项。
- **验收**：登录后能进数学主页 → 看到知识点地图（带掌握度色点）→ 点开看"讲透"内容。

## 阶段 2 · 苏格拉底对话（1–2 天，跨学科通用）
补全闭环的"顿悟"环节。注意 physics 页 `handleSocratic` 回调已存在但 **路由缺失会 404**（`PhysicsLesson.tsx:62-67` vs `App.tsx` 无 `/socratic` 路由）——本阶段一并修。

- [ ] **M-F5** 新建通用 `pages/SocraticDialog.tsx`（聊天界面 + SSE 流式）。复用 `/v1/socratic/start`(`:684`)、`/message`(`:698`, SSE)、`/escape`(`:713`)、`/end`(`:721`)。**红线**：前端必须先自评再揭示、看答案=Again、不渲染完整步骤（与后端红线对齐）。
- [ ] **M-F6** `App.tsx` 加动态路由 `/subjects/:subject/socratic/:sessionId`；`KCGroup` 的 `onSocratic` 指向它。物理同时受益。
- [ ] **M-F7（后端小修）** `services/main.py:1008` 与 `:1140` 的 `subject="math"` **硬编码**改为参数（来自 KU 的 subject）。**注意**：对数学本身无害（值正好是 math），但它会阻断物理/语文走同一苏格拉底入口——属顺手解阻塞，非数学必需。
- **验收**：从知识点/错题点"苏格拉底引导" → 流式对话 → 逃生出口可用 → 结束回写掌握度。

## 阶段 3 · 认知闭环看板（2–4 天，价值核心）
把"镜子"做出来。这些组件**全部新建但学科无关**，做完即点亮整条护城河。

- [ ] **M-F8** `components/MasteryOverview.tsx` —— 薄弱知识点排序/热力（`GET /v1/mastery/{sid}` `:267`，按 effective_mastery 升序）。
- [ ] **M-F9** `components/MasteryChart.tsx` —— 成长曲线折线图（`GET /v1/mastery/curve/{sid}/{kc}` `:243`）。需引入轻量图表库（如 `recharts`，先确认 package.json 是否已有图表依赖，无则评估体积）。
- [ ] **M-F10** `components/DailyPlanCard.tsx` —— 今日目标（`GET /v1/daily-plan/{sid}?subject=math` `:664`，展示 P1 到期/P2 错题/P3 薄弱/P4 新知四优先级）+ `POST /v1/missions/{id}/complete`。
- [ ] **M-F11** `pages/math/MathDashboard.tsx` —— 组合 M-F8/9/10 为学科主仪表板（替 MathHome 成为登陆页）。
- **验收**：进数学 → 一屏看到"我哪弱、我在变好、今天做什么"。

## 阶段 4 · 试卷入口 + 错题本 + 努力看板（2–3 天）
冷启动钩子的"上传一张卷→共同断点"在前端落地。

- [ ] **M-F12** `pages/PaperUpload.tsx` —— 多图上传（`POST /v1/papers/upload` `:528`）+ 轮询 `GET /v1/papers/{id}` `:568` 显示 processing→done + 共同断点呈现。
- [ ] **M-F13** `pages/ErrorJournal.tsx` —— 错题本列表（`GET /v1/error-journal/{sid}`）+ 变式复习（`GET /v1/review/due/{sid}`），接 M-C 检索约束（先答后揭示）。
- [ ] **M-F14** `components/EffortBoard.tsx` —— 努力错觉看板（M-F）。**先确认后端是否有 `effortful-gains` 端点**（Master §8 列了 `GET /v1/effortful-gains/{sid}`，但路由盘点未见，可能缺）→ 缺则记入后端待办，本组件先用 `/v1/patterns` 兜底。
- **验收**：上传真卷 → 看到"这些错背后同一个断点" → 进苏格拉底 → 完成后努力看板给正反馈。

---

## 后端待补端点（前端阶段会撞到）
- [ ] `GET /v1/effortful-gains/{student_id}`（Master §8 有契约，路由疑缺）—— M-F14 依赖。
- [ ] `services/main.py:1008/1140` 去硬编码 subject —— M-F7。
- [ ] 确认 `/v1/mastery`、`/v1/review-queue`、`/v1/patterns` 是否需要 `subject` 过滤（当前返回全科）——单科视图下前端可临时过滤，但多科上线前应后端支持。

## 风险与取舍
- **图表库**：M-F9 需图表依赖，先查 `frontend/package.json`；选 `recharts`/`visx` 注意 PWA 体积。
- **不要再铺学科**：本计划只做数学；物理/语文顺带受益于通用组件（苏格拉底/看板），但**不新开物理专属工作**。
- **红线守护**：M-F5 苏格拉底前端必须实现"未作答不可见答案、看答案=Again"，否则违反检索/苏格拉底红线——需对应前端测试。

## 建议节奏
阶段 1（先让数学"有页面"，0.5–1 天）→ 阶段 3（先做看板，价值最高）→ 阶段 2（苏格拉底）→ 阶段 4（试卷+错题+努力）。
> 把阶段 3 提前到 2 之前：成长曲线/今日目标是"镜子"的核心，比对话更能验证差异化价值。
