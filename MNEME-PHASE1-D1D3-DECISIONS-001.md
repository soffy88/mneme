# MNEME-PHASE1-D1D3-DECISIONS-001

**类型**：决策落定（喂给 PHASE1-IMPL-SPEC-002；不写实现代码）
**范围**：SPEC-002 隐含"已给定"、实则缺失的三处前置决策 D1/D2/D3
**依据**：全部基于对生产库 `mneme`（Postgres）+ 共享主库 `/data/soffy/projects/platform/3O` 的实测，非假设。
**铁律继承**：不动 mneme 既有模块/表；新增只落 `gate` schema；期望答案永不出 mneme 侧；verdict_guard 三拒。

**评审状态（rev.1）**：D1 通过、D3 通过；D2 发现内部矛盾（gate_type 白名单规则会判 ku004=quantitative，assess 永不触发，DoD 第三桩必挂）+ 连带活锁洞，已在 rev.1 修复（见 D2.2 三层解析、D1.3 建 path 校验、D2.1 fill 路由）。文末新增《SPEC-002 实质修正清单》。

**评审状态（rev.2，实测 packages/ 现状后）**：发现 `packages/mneme-core`+`mneme-agent` 已有一套 SPEC-002 的**内存 mock walking-skeleton**，据此两处拍板：
- **集成模型 = 现在就接真 DB+BKT**：gate schema 走 Alembic；`mneme-core` 停止自写 BKT，改调既有 `services.cognitive_service.process_interaction`；DoD 换真广东 KC+题库。满足 SPEC 铁律与 DoD。
- **元素归属 = 留 mneme-core**：放弃 D3 的 platform/3O RFC 路线（**D3 作废**）；mneme-core 即 7 元素之家。遗留单源风险：与 platform/3O 的 oprim/oskill 可能重复，留待后议。
- **🔴 新发现红线 bug**：`packages/mneme-core/mneme_core/app.py` 的 `GetNextObjective` 把 `pending_question.expected`（期望答案）直接回传 agent —— 违反"期望答案永不出 mneme 侧"。集成时必堵：next 只暴露 `has_pending`，不出内容。
- **集成边界待定（A/B）**：MCP 工具面要调 `process_interaction` + 拥有 mneme Postgres 的 gate.*，须跨进 mneme app 的 DB/service。见文末《集成边界决策》。

---

## 背景实测结论（三条硬事实，决定下列决策形态）

1. **`ku_type` 已退化**：数学 KU 一律是默认值 `concept`；全库 29 个 `ku_type` 里**只有 `concept` 类在题库有题**（1,540 个），其余 28 类题库覆盖为 0。→ `ku_type` 不能当判分路由键。
2. **`question_types` 基本为空**：全库仅 ~2040 个 KU 有值，主值 `short_answer`。→ 同样不能当路由信号。
3. **题库全是数学 RENJIAO/cmm**：18,472 道可用题里 17,145 道数学，且含选择/填空/解答多型（实测样题："…经过原点的( )" 答案 `A`）。→ DoD 三桩可全部落在真实数学 KC 上。

---

## D1 — rubric 存放方案 + 首个 concept rubric

### D1.1 存放决策：新建 `gate.rubric` 表（纯新增，唯一写入者 = mneme/mcp）

理由：rubric 是 `qualitative_verifier` 的**门控判据输入**，与 `gate.qualitative_mastery` 同域；按 SPEC-002 对 001 的护栏修正精神（过门判据落 mneme 侧、防 agent 篡改），rubric 不能落 KU 字典/agent 侧。**不改 `knowledge_units` 表结构**（守铁律）。

```sql
-- 追加进 mneme/mcp/ddl/gate_schema.sql
CREATE TABLE gate.rubric (
    kc_id       varchar(100) PRIMARY KEY,
    dimensions  jsonb NOT NULL,          -- [{name, criterion, weight}]，与 SPEC §2 Rubric 对齐
    author      varchar(50)  NOT NULL,   -- 'handwritten' | 人工署名
    created_at  timestamptz  NOT NULL DEFAULT now()
);
```

`GetKCInfo(kc_id)` 对 `gate.rubric` 做 LEFT JOIN：命中 → 返回 `rubric`；未命中 → `rubric=None`，该 KC **不可走 assess 路径**（fail-safe，宁缺毋滥）。

### D1.2 首个手写 rubric（DoD 的 concept 桩）

KC = `renjiao-math-g10-a-ku004`（**函数的概念与表示**，人教A版必修一，题库 43 题）：

```json
{
  "kc_id": "renjiao-math-g10-a-ku004",
  "author": "handwritten",
  "dimensions": [
    {"name": "对应关系本质", "weight": 0.35,
     "criterion": "能说明函数是两个非空数集间『每个 x 唯一对应一个 y』的对应关系，而非仅一个公式或图象"},
    {"name": "三要素完整", "weight": 0.25,
     "criterion": "指出定义域、对应法则、值域三要素，并说明定义域与对应法则共同决定值域"},
    {"name": "表示法辨识", "weight": 0.20,
     "criterion": "能区分解析法/列表法/图象法，并意识到同一函数可有多种表示"},
    {"name": "反例判别", "weight": 0.20,
     "criterion": "能用『一对多不构成函数』判断给定对应是否为函数（给反例即算达标）"}
  ]
}
```

`qualitative_verifier` 产出的 `evidence_spans` 必须锚定到学生自我解释的原文区间；无法锚定任一维度 → `passed=False`（SPEC §3 已定）。

### D1.3（连带修正）活锁防护：路径构建期校验，不在循环里

**洞**：`next_objective` 若遇到"gate_type=qualitative 但该 KC 无 rubric"，会派 `assess` → 工具因无 rubric 拒绝 → 下回合又派 `assess` → **活锁**。
**W1 最简解**：把校验前移到**建 path 时**——构建学习 path 时断言每个入 path 的 KC 其 (gate_type, rubric) 自洽：**qualitative KC 必须有 rubric 才允许入 path**，不满足**在建 path 时 raise**，绝不进回合循环。
（rev.1 的 D2.2 净规则已从结构上排除"qualitative 无 rubric"这一状态；本校验作为**防御性冗余**，防 config 漂移/会话中途删 rubric。）`NextStep` 增加 `blocked` 语义（把"缺 rubric"作为可返回状态而非异常）**留 W2**。

---

## D2 — 判分路由 + gate_type 映射（29→2）+ DoD 三桩

### D2.1 判分路由（scoring）：按 `qtype`，不按 `ku_type`

`SubmitAnswer` 已带 `qtype`。路由（**fill 需分学科**）：

| qtype（+学科） | 判分器 | verdict_source | 说明 |
|---|---|---|---|
| 数学 `solve` | 既有 sympy 内核 | deterministic | |
| **数学 `fill`** | 既有 sympy 内核 | deterministic | **数学填空一律走 sympy，绝不进 answer_match**（避免符号等价被字符串比对误判） |
| `choice` | `oprim.answer_match(choice)` | deterministic | 归一化精确 |
| `short` | `oprim.answer_match(short)` | deterministic | SequenceMatcher≥0.85 |
| **非数学 `fill`** | `oprim.answer_match(fill)` | deterministic | 归一化精确比对（**answer_match 域新增 `fill`，见 D3.5**） |
| `open`（自我解释/作文） | `oskill.qualitative_verifier` + rubric | llm_verified | |

`ku_type` **不参与判分路由**，仅作"该出哪类题"的弱提示。

### D2.2 gate_type 三层解析（rev.1，供 `oprim.is_mastered` 决定读下界还是读定性旗标）

`is_mastered` 需每 KC 的 gate 类别。**三层，高优先覆盖低：**

1. **override（最高）＝ rubric 存在性**：`gate.rubric` 命中该 kc_id → `qualitative`。即 **rubric 表本身就是 qualitative 注册表**——写一份 rubric ＝ 显式把该 KC 注册为定性门控。与 D1 fail-safe 天然自洽（有 rubric ⟺ 能 assess ⟺ qualitative）。
2. **whitelist（中）＝ 撰写待办，非运行时判据**：12 类开放/表达型 `ku_type`（`xiezuo`、所有 `*_yuedu` 阅读、`shici_jianshang`、`kouyu_jiaoji`、`goutong_chushi`）是**应当**成为 qualitative 的清单，但**拿到 rubric 前不生效**（无 rubric 无法 assess）。W1 它只作 authoring backlog；补上 rubric 即经第 1 层升级。
3. **default（最低）＝ quantitative**：其余全部（含数学 `concept`、`method`、`formula`、`chengyu`、`physical_*`、`mingju` …）。

**运行时净规则：`gate_type(kc) = qualitative ⟺ gate.rubric 命中该 kc；否则 quantitative`。** 一条规则同时消解两个隐患：

- **D2 原矛盾（第三桩必挂）**：ku004 是数学 `concept`，不在 12 类白名单，旧规则判 `quantitative` → `assess` 永不触发 → rubric 白写 → DoD 第三桩挂。新规则下 ku004 因 D1.2 已写 rubric → 自动 `qualitative` → 第三桩通。✅
- **活锁**："qualitative 但无 rubric" 在新规则下**不存在**（定性 ⟺ 有 rubric），`next_objective` 不可能派出一个无 rubric 的 `assess`。

> ⚠️ 反向纪律：给一个本该确定性的 KC 误写 rubric 会把它翻成 qualitative。**只给真正走自我解释/开放评判的 KC 写 rubric。**
> SPEC §3 `is_mastered(kp.type=...)` 与 `KpView.type` 一律读**本规则产出的 gate_type**，不读 raw `ku_type`。规则实现（查 `gate.rubric` 存在性 + 默认量化）落 `mneme/mcp`，非主库元素。

### D2.3 DoD 三桩（全为广东人教A版必修一真实 KC，e2e 可直接跑）

| DoD 角色 | KC id | 名称 | 题量 | 判分路径 | gate_type |
|---|---|---|---|---|---|
| procedure（确定性·解答） | `renjiao-math-g10-a-ku-二次函数的零点` | 二次函数的零点 | 48 | sympy | quantitative |
| memory（确定性·客观） | `renjiao-math-g10-a-ku-三角函数的定义-单位圆` | 三角函数的定义（单位圆） | 69 | answer_match(choice) | quantitative |
| concept（定性·自我解释） | `renjiao-math-g10-a-ku004` | 函数的概念与表示 | 43 | qualitative_verifier + D1.2 rubric | qualitative |

> 附带收益：DoD 跑通 = 广东高中数学主线（必修一 函数/三角/二次函数）真正端到端可练可测，正好回填最初"该知识点暂无练习"的痛点。

---

## D3 — platform/3O 的 7 元素 RFC（草稿骨架，待你走治理流程提交）

**RFC 标题**：`RFC: mneme Phase1 门控内核 7 元素（4 oprim + 3 oskill）`
**目标库**：`/data/soffy/projects/platform/3O`（主库，跨仓）

### D3.1 单源自检（写前 grep，附录 A 要求）

| 元素 | 主库现状 | 处置 |
|---|---|---|
| `oprim.due_compute` | **已存在**（`oprim/due_compute.py:9`，单卡到期 bool） | 复用；`due_reviews` 内部**可**调它？→ 否（oprim 互调禁）；`due_reviews` 自行内联到期判定或只做排序，不 import due_compute |
| `oprim.answer_match` | 不存在（仅 oskill/llm/cot.py 有同名正则变量） | 新建，无冲突 |
| `oprim.mastery_lower_bound` / `is_mastered` | 不存在 | 新建 |
| `oskill.next_objective` / `map_summary` / `qualitative_verifier` | 不存在 | 新建 |

### D3.2 元素契约（照搬 SPEC §3，附 3O 合规点）

- 4 oprim：签名遵 3O §4.4（≤1 位置参，余 keyword-only；oprim 可 raise）。
- **`is_mastered` 下界公式内联**，不调用 `mastery_lower_bound`（H1-prim 互调禁）——SPEC §3 已注明，RFC 需在评审点复述。
- `qualitative_verifier`（oskill）：LLM 经 `obase.provider_registry.LLMCaller` Protocol 注入，**不 import 任何 provider SDK**；组合清单写进 docstring（≥2 oprim/形态）。
- 阈值 `z=0.84 / n_min=2 / gates` 均为**参数默认值**，主库元素不带项目配置（mneme 侧 config 注入）。

### D3.3 测试门槛（附录 A）
oprim 各 ≥5 场景、oskill 各 ≥8 场景；关键断言见 SPEC §10（`open→ValueError`、`n_obs<n_min→False`、`evidence_spans 必锚原文`、`门控即游标`等）。

### D3.4 依赖方向合规
`oskill.next_objective` 组合 `due_reviews + is_mastered`；`map_summary` 组合 `is_mastered + mastery_lower_bound`——均 oskill→oprim 单向，符合 3O。I/O schema（Pydantic frozen）随元素入库。

### D3.5（rev.1）`answer_match` 的 `fill` 域必须钉死
D2.1 给 `answer_match` 新增 `fill` 类型，但 SPEC-002 §3 的 `qtype: Literal["choice","short"]` 未含它。RFC 里把规则钉死：
- 域扩为 `Literal["choice","short","fill"]`；
- **`fill` = 归一化精确比对**（同 `choice` 语义：去空白/全半角/大小写归一后 `==`），不用 short 的模糊阈值；
- **数学填空一律在上游路由到 sympy，永不进 `answer_match`**（D2.1 已定）——故 `answer_match(fill)` 只处理非数学填空；
- 类型域外（如 `open`）仍 `raise ValueError`（护栏第一道闸，SPEC §3 不变）。

---

## SPEC-002 实质修正清单（4 处，D1/D2 引入，需并入 SPEC/Master）

| # | 修正 | 位置 | 性质 |
|---|---|---|---|
| 1 | 新增 `gate.rubric` 表（rubric 唯一存储 = qualitative 注册表） | SPEC §6.2 gate schema DDL | 纯新增，附加表 |
| 2 | `KpView.type` / `is_mastered(kp.type)` 改读**三层解析产出的 gate_type**（rubric 存在性 > 白名单 > 默认 quantitative），不读 raw `ku_type` | SPEC §2 KpView / §3 is_mastered | 契约语义修正 |
| 3 | `answer_match` 域扩 `fill`（归一化精确）；数学 fill 路由 sympy | SPEC §3 answer_match Literal | 契约域扩展 |
| 4 | DoD 三桩换广东人教A版真题（二次函数的零点 / 三角函数定义-单位圆 / 函数的概念） | SPEC §0 DoD | fixture 具体化 |

---

## 集成边界决策（rev.2 待拍板 A/B）

MCP 工具面要"调既有 `process_interaction` + 拥有 mneme Postgres 的 gate.*"，须触达 mneme app 的 DB/service。两案：

- **A（推荐）＝ MCP 工具面并入 mneme app**：`/mcp/*` 路由挂到 `services`（复用既有 DB session 依赖），工具面直接调 `process_interaction` + gate_store；`mneme-core` 的 oprim（mastery_gate/models/grade/spacing）作为**纯库**被 import。agent 仍走 HTTP、零 DB，CORE_URL 指向 mneme app。**优点**：复用既有 engine/session/models，一进程内事务一致，DoD"写入经 process_interaction"天然满足，接线最少。**代价**：mneme-core 的 mcp 层不再是零依赖独立服务（但 3O §6.3 本就允许 Layer4 调既有 service）。
- **B ＝ mneme-core 独立服务 + 自建到同一 Postgres 的 engine**，import `services.*`。**优点**：贴近 SPEC §1.3 的独立 core 形态。**代价**：两进程/同库、跨进程事务、迁移协调、import 边界更绕。

> 铁律"调既有 process_interaction 不重实现" + DoD"写入经既有 process_interaction" + 最小风险 → **倾向 A**。待确认后进 D2/集成。

---

## 待办（决策落定后，按 SPEC 顺序推进）

- [x] **D1 完成**：`gate` schema（rubric/pending_question/qualitative_mastery/evidence）经 Alembic 迁移 `c4d5e6f7a8b9`（**改用 Alembic 而非裸 `gate_schema.sql`**，守黄金规则 #5）；ku004 rubric 入库、4 维权重和 1.00；迁移可逆验证通过
- [x] **D2.2 净规则完成**：`services/gate_store.py`（`resolve_gate_type`/`get_rubric`/`get_qualitative_mastery_map`）对真 gate.* 表；`tests/test_gate_store.py` 3 passed（ku004→qualitative+4维权重1、未知kc→quantitative+None、空map）
- [x] **②-1 gate_store 写路径**：`pose_question`/`get_pending`/`clear_pending`/`save_evidence`/`upsert_qualitative_mastery`（`services/gate_store.py`）；`test_gate_store.py` 6 passed（expected 只存 pending、student 作用域、evidence+定性 upsert 幂等）
- [x] **②-0 打包（compose PYTHONPATH）完成**：`docker-compose.yml` 给 api/worker/beat 加 `PYTHONPATH=/app:/app/packages/mneme-core`，重建三服务；in-app `import mneme_core`+assembler OK、api /health 200、测试免前缀 10 passed。**遗留**：稳定后固化为 Dockerfile `pip install`（与 obase/oprim 平价），届时可去掉 `importorskip` 守卫
- [x] **②-2 ProgressView 组装器完成**：`services/progress_assembler.py` 投影 `kc_mastery`+`interaction_events`+`fsrs`+`gate.qualitative_mastery`→ mneme-core `LearningProgress`，rubric 存在性设 `kp.type`；`test_progress_assembler.py` 4 passed（gate_type 分派、量化下界过门、定性 gate flag、证据不足不过门），端到端验证纯库 `is_mastered` 未改而吃到正确 gate_type；测试用 `importorskip` 守卫（②-0 前 CI 跳过不报错）
- [x] **②-3a 读工具完成**：`services/mcp_router.py`（`NextObjective`/`GetKCInfo`/`CheckMastery`）挂进 `main.py`（guarded include，mneme-core 不可用则优雅降级）；`get_active_pending`+组装器填 `pending_question`；**堵 `expected` 回传红线**（`test_mcp_router.py` 4 passed 含红线测试）；api 重启 /health 200、HTTP `/mcp/GetKCInfo` 真打通
- [x] **②-3b-i 数学判分器**：`services/math_grade.py`（sympy 符号等价 + 多根集合比对 + 非数学归一化回落）；`test_math_grade.py` 7 passed。sympy 放 app 侧（mneme-core 零依赖）
- [x] **②-3b-ii 确定性写路径完成**：`mcp_router` 加 `PoseQuestion`/`SubmitAnswer`（tool 无 commit 可测、route commit）；判分路由 solve/fill→`grade_math`、choice/short→`answer_match`、open→needs_qualitative；guard(origin=core)→既有 `process_interaction`→clear。`test_mcp_write_path.py` 4 passed：**确认 process_interaction 冷启动建 kc_mastery（DoD 铁律满足）**、答错判负、choice 走 answer_match、open 零写入留 pending。api 重启 5 条 /mcp 路由全注册、/health 200
- [x] **②-3c 定性写路径完成**：`mcp_router` 加 `ReportResult`——guard 三拒（agent 不得 deterministic、llm_verified 必须带 evidence，均零写入）→ `save_evidence` → 按 gate_type 分流（qualitative→`upsert_qualitative_mastery`；quantitative→`process_interaction`）。`test_mcp_report_result.py` 4 passed（含两红线）。6 条 /mcp 路由全上线；Phase1 app 测试合计 29 passed、mneme-core 32 passed
- [ ] **GetReviewQueue**（第 7 工具，minor）：`due_reviews` 便捷读；DoD 复习经 NextObjective 已可驱动，可后补
- [x] **DoD 全闭环 e2e 完成（capstone）**：`test_dod_e2e.py` 1 passed——工具序列驱动 3 桩广东真 KC（二次函数的零点/solve、三角函数定义/choice、函数的概念/rubric）跑到 `complete`；量化桩反复答对→`process_interaction`→`kc_mastery` 下界过门 mastered、定性桩→`ReportResult`→`gate.qualitative_mastery` mastered；真 DB 写入全断言通过。**SPEC-002 DoD 核心闭环验证成立**（agent 零 DB 由架构 A 的 HTTP 边界保证——mneme-agent 包无任何 db import）
- [ ] **D3 qualitative_verifier 真实装**：替 `mneme-agent/verifier.py` 规则桩 → rubric 解析 + evidence_spans 锚定 + 注入 LLMCaller
- [ ] **D1.3 建 path 校验**：qualitative KC 无 rubric → 建 path 时 raise
- [ ] `is_mastered` 消费 gate_type：ProgressView 组装器投影 `kc_mastery`/`interaction_events`/`fsrs`+`gate.qualitative_mastery`，按 rubric 存在性设 `kp.type`
- [x] **D2.1 answer_match 完成（纯函数部分）**：mneme-core `grade.py` 扩 `fill`（NFKC 归一化精确）、`short`≥0.85、solve/open→ValueError；单源保留 `grade_objective` 委托；`test_grade.py` 13 passed / 全套 32 passed。（数学 solve/fill→sympy 的**路由**属服务层，归下条集成）
- [ ] D3（qualitative_verifier 真实装）：rubric 解析 + evidence_spans 锚定（替换 `verifier.py` 规则桩）
- [ ] D1.3 建 path 校验：qualitative KC 无 rubric → 建 path 时 raise（不进循环）
- [ ] DoD e2e 三桩换广东人教A版真题（二次函数的零点/三角函数定义-单位圆/函数的概念），跑通真 DB 写入
- [x] ~~D3 platform/3O RFC~~ **作废**（rev.2：元素留 mneme-core）
