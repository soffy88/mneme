# CLAUDE.md · Mneme（善学记）项目约定

> Claude Code 在本仓库工作时**首先读取本文件**。
> **唯一权威设计** = `MNEME_MASTER_DESIGN.md`（SSOT）。**执行看板** = `TASKS.md`。
> 本文件是"怎么干活"的规矩；"做什么/契约"一律以 Master 为准。

## 这是什么项目

Mneme（对外名**善学记**，旧名"学鉴"已废弃）：面向全年级学生的个人学习成长档案 + 自主学习工具。
线上真前端在独立仓库 `/data/soffy/projects/mneme-web`（Next.js App Router PWA）；本仓库 `frontend/` 是废弃旧版，勿开发勿审计。
核心是 **KT(知识追踪 BKT)+ FSRS(间隔重复)算法内核**，先做**广东数学**。
按 **3O 范式** 组织代码。产品理念三主线（详见 Master §1.2）：
1. 确定性内核兜住"算"和"图"，LLM 只"问"和"讲"。
2. 学习科学机制（交错/检索/努力错觉/识别）做进调度。
3. 永久档案 + KT/FSRS 是护城河。

## 黄金规则

1. **`MNEME_MASTER_DESIGN.md` 是唯一事实来源。** 实现与之冲突，先改 Master 再写代码，禁止擅自偏离契约（数据模型/API/算法/3O 分层）。
2. **不重写已验证内核。** `oprim/bkt.py`、`oprim/fsrs_engine.py`、`oskill/cognitive_state.py` 已验证（合成数据回归 AUC≥0.65；0.77 为目标，真实数据待验证），只能扩展，不能推翻其算法契约。
3. **一次只做一个 `TASKS.md` 的 task。** 完成后勾选 `[x]` + 写一行完成说明。
4. **每个改动都要能自测。** 写代码必带测试。
5. **数据库只走 Alembic migration。** 禁止手改库。
6. **密钥只走环境变量。** 硬编码 key 视为缺陷。
7. **未成年人数据操作必过合规校验**（Master §10）。涉及儿童数据的 task，合规测试不过 = 未完成。

## 3O 范式约定（本项目的代码组织法）

层级与组合硬约束：

| 层 | 是什么 | 硬约束 |
|----|--------|--------|
| **oprim** | 单次原子操作（一次计算/一次外部调用/单 LLM 调用） | 互不调用（H1-prim 严格禁）；纯函数倾向 |
| **oskill** | ≥2 个不同 oprim 组合的算法 | 可受限互调 sibling（深度≤2、被调 stateless、docstring 列出、无循环）；stateless；不持久化 |
| **omodul** | ≥2 oskill/oprim 组合的业务事务 | 不调 sibling omodul（H1-modul 严格，含"包装模式"）；标准签名 `(config,input,output_dir)→dict`；失败不 raise 返回 status；显式声明 `_enabled_pillars`（4 支柱按需）|
| **obase** | 基础设施横切（与 3O 平行） | 不反向调 3O |
| **服务层** | Layer 4 对外运行边界 | 不替 omodul 算 fingerprint/写 report/累计 cost；不让 omodul 知道 user_id |

- **命名扁平**：`from oprim import bkt_update`，不按领域分子模块；元素名不带项目前缀（`solve_conic` 不是 `mneme_solve_conic`）。
- **单 LLM 调用 = oprim**，不是 oskill（复杂≠层级）。oskill 必须 ≥2 个不同 oprim。
- **依赖方向**：omodul→oskill→oprim 单向；3O→obase 允许，obase→3O 严禁。
- **渲染不入主库**：图示数据由 oprim产出，Mafs/Three.js 渲染在前端（3O 不覆盖 UI）。

**写要求升级（2026-06 实战修复后；权威见 `platform/3O/HELIOS_3O_SPEC_v3_0.md` §1.4/§5.5.1/§7.4）：**
- **单源**：写新元素前先 grep 有无同源；同一逻辑禁两份实现，历史双份须留一份 canonical、另一份改 re-export/委托 + `test_*_single_source` 守卫。
- **obase 不反向依赖**：基础设施需要的"状态/数据类型"归 obase，算法归 oprim（`obase/cognitive_types.py` 是范例）；判据"数据长什么样 vs 怎么算"。
- **指纹/轨迹禁真实 PII**：`_fingerprint_fields`/decision_trail 不得含真实 user_id；服务层调 omodul 前用 `services/anon.py` 伪名化（涉未成年人 MUST）。
- **omodul 必填 `_enabled_pillars`**（≥1）。

## 技术栈（不要自行更换）

Python 3.12 / FastAPI(async) / SQLAlchemy 2.0 async + Alembic / PostgreSQL 16 / Redis 7 / Celery / py-fsrs / sympy / Anthropic SDK / React+TS+Vite+Tailwind+Mafs+Three.js / Docker Compose / pytest。详见 Master §9。

## 目录约定（MVP 单 repo 内 3O 分层，验证后拆四包）

```
mneme/
├── MNEME_MASTER_DESIGN.md   # 唯一权威
├── CLAUDE.md / TASKS.md
├── oprim/                   # 单次原子操作（含已实现 bkt/fsrs_engine）
│   ├── bkt.py · fsrs_engine.py        # ✅ 已实现
│   ├── solve_*.py                     # 确定性求解(M-A)
│   ├── kernel_viz.py                  # kernel_to_plot2d/three(M-D)
│   └── llm_oprims.py                  # ocr/grade/profiler/socratic_turn/svg(单LLM调用)
├── oskill/                  # ≥2 oprim 组合算法
│   ├── cognitive_state.py             # ✅ cognitive_update(扩展双维度)
│   ├── solve_and_visualize.py · socratic_loop.py · interleave_select.py
├── omodul/                  # 业务事务（标准签名+支柱按需）
│   ├── analyze_paper.py · socratic_session.py · generate_lesson_page.py
│   ├── daily_mission.py · longitudinal_analysis.py
│   └── parent_report.py · export_archive.py · register_student.py
├── obase/                   # 基础设施
│   ├── provider_registry.py · cost_tracker.py · auth.py · oss.py
│   └── sympy_runtime.py               # 求解沙箱(超时/内存/隔离)
├── data/guangdong_math_kc.py          # ✅ KC 字典(地基)
├── services/                # Layer 4：FastAPI/鉴权/合规/SSE/Celery/调度引擎
├── frontend/                # ⚠️ 废弃旧版（学鉴 React+Vite）；真前端见 mneme-web 仓库
├── alembic/ · tests/
```

## 命令

```bash
docker compose up -d
alembic revision --autogenerate -m "xxx" && alembic upgrade head
./scripts/check.sh                 # CI Quality Gate (Ruff + MyPy + Pytest w/ Cov)
uvicorn services.main:app --reload
cd /data/soffy/projects/mneme-web && npm run dev   # 真前端（善学记）；本仓库 frontend/ 已废弃
```

## 编码规范

- 服务层/oskill/omodul 全异步（omodul 主函数同步，内部并发用 ThreadPool，FastAPI 用 `asyncio.to_thread` 调）。
- 类型注解必填；mypy 通过。
- 数值在 API 边界 round（掌握度 4 位）。
- 错误抛 `HTTPException(status,detail)`，统一 `{detail}`。
- 提交信息：`<epic>/<task>: 简述`（如 `epic10/solve-conic: sympy 圆锥曲线求解+10样题自检`）。

## 红线（违反即 task 未完成，改动需先改 Master）

- **算法红线**：P(L)∈(0,0.97]；`effective=long_term×R`；`careless∝P(L)·P(S)`，`dontknow∝(1-P(L))·(1-P(G))`；更新顺序=旧卡片算R→forgetting-aware BKT→答错则classify→FSRS review→落库+追加 interaction_events（只增不改）。
- **确定性优先红线**：有 `solve_*` 覆盖的题型，数值结论必来自内核（mock LLM 给错值，最终仍以内核为准）。
- **苏格拉底/答案分级红线（2026-07-03 松绑，权威见 Master 附录 L2）**：不再是"任何模式永不给"，改**按情境分级**——学生**自带作业/试卷原题**与**写作/作文**永不输出可抄答案/完整步骤（"诱导也不泄露"测试保留）；系统教学**同构新知**必须给完整样例+自我解释提示。每次只问一个问题；错误中间步由 `verify_step` 拦截（确定性，不靠 LLM）；教学引擎全程 feature-flag，RCT 裁决默认值。
- **同源自检**：lesson_page 图示值==答案==末步值，三处不一致不交付。
- **交错/检索红线**：相邻题 KC 不同；回顾未作答不可见答案，看答案=Again。
- **合规红线**：<14 岁无监护人同意注册必失败；删除后数据不可查询。
- **沙箱红线**：病态 sympy 输入必须超时被杀。

## 完成一个 task 的定义（DoD）

1. 符合 Master 契约。2. 有测试且 `pytest` 全绿。3. ruff+mypy 通过。4. 涉及 DB 有 migration。5. 涉及儿童数据合规测试通过。6. 涉及红线的对应红线测试通过。7. 在 `TASKS.md` 勾选 + 一行说明。

## 不要做的事

- 不引入 Master 未列出的新框架/依赖（需先改 Master）。
- 不在路由/服务层写本应属 oprim/oskill/omodul 的业务逻辑。
- 不让 omodul 调 omodul（含包装模式）；多 omodul 协作在服务层。
- 不为了让测试过而弱化任何红线或合规校验。
- 不一次性大改多个 Epic；按 TASKS 顺序推进。
