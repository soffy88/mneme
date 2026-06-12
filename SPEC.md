# SPEC · 自我助学系统（实施规格）

> 本文档是交给 Claude Code 施工的**唯一事实来源（SSOT）**。
> 配套文件：`CLAUDE.md`（项目约定）、`TASKS.md`（任务看板）。
> 产品背景见 PRD v1.2（战略）/ v1.3（算法内核）。本 spec 只管「怎么造」。

---

## 0. 当前状态（已完成，禁止重写，只能在其上扩展）

| 模块 | 文件 | 状态 |
|------|------|------|
| 广东数学 KC 字典（29 个知识点） | `data/guangdong_math_kc.py` | ✅ 完成，待落库+扩展 |
| BKT 知识追踪引擎（forgetting-aware + 粗心/不会判定） | `core/bkt.py` | ✅ 完成 |
| FSRS 间隔重复封装（基于 py-fsrs） | `core/fsrs_engine.py` | ✅ 完成 |
| KT+FSRS 协调器（内存存储） | `core/cognitive_state.py` | ✅ 完成，待换 PostgreSQL |
| FastAPI 服务（5 接口，内存） | `api/main.py` | ✅ 雏形，待重构 |
| 引擎验证测试（含 AUC） | `tests/test_engine.py` | ✅ 完成 |

**核心契约（不可破坏）**：
- 掌握度模型：BKT，掌握度 `P(L)` ∈ (0, 0.97]，封顶 0.97。
- forgetting-aware：`effective_mastery = long_term_mastery × R_fsrs`。
- 错误分类：`careless` ∝ P(L)·P(S)；`dontknow` ∝ (1-P(L))·(1-P(G))。
- 复习调度：FSRS（py-fsrs），评分映射见 `fsrs_engine.map_performance_to_rating`。
- 算法与 LLM 分工：掌握度/复习/粗心判定走算法；错误细分/共同断点/苏格拉底走 LLM。

---

## 1. 目标（本期 spec 的范围）

把当前的「算法内核 demo」完善为「单科（广东数学）可用的 MVP 后端 + 最小前端」，达到：

1. 数据持久化（PostgreSQL），内核状态与答题事件流落库。
2. 真实数据入口：试卷上传 → OCR → 批改 → 自动产生 interaction 事件 → 驱动内核。
3. 用户体系与合规：学生/家长、JWT、未成年人监护人同意、数据导出/删除。
4. 认知应用层：今日目标、掌握度总览、复习队列、成长曲线、纵向分析。
5. 苏格拉底对话：接基础模型（流式）、情绪感知、逃生出口。
6. 家长端：成长摘要、微信日报、5 类预警、多孩子。
7. 最小前端：学生端核心流程 + 家长端摘要。
8. 可部署：Docker Compose 一键起。

**非目标（本期不做，留给后续）**：DKT 深度模型、AI 出题、志愿填报、真题题库接入、APP 原生端。

---

## 2. 技术栈与全局约束

| 层 | 选型 | 约束 |
|----|------|------|
| 后端 | Python 3.12 + FastAPI | 全异步 `async def`；类型注解必填 |
| ORM | SQLAlchemy 2.0 (async) + Alembic | 所有 schema 变更走 migration，禁止手改库 |
| 数据库 | PostgreSQL 16 | 时间序列用普通表；UUID 主键 |
| 缓存/队列 | Redis 7 | 会话、Celery broker、Streak |
| 异步任务 | Celery | OCR、纵向分析、日报推送 |
| 对象存储 | S3 兼容（开发用 MinIO，生产用阿里云 OSS） | 试卷原图，冷热分层 |
| LLM | Anthropic Claude API | OCR/批改/苏格拉底/共同断点；key 走环境变量 |
| 间隔重复 | py-fsrs | 不自研 |
| 前端 | React + TypeScript + Vite + Tailwind | PWA；状态用 React Query |
| 部署 | Docker Compose | 开发生产同构 |
| 测试 | pytest + pytest-asyncio | 每个 service 层有单测；关键链路有集成测试 |

**全局规则**：
- 配置全部走环境变量（`pydantic-settings`），禁止硬编码密钥。
- 所有金额/分数/掌握度等数值字段在 API 层统一 round 处理。
- 所有面向未成年人的数据操作必须经过合规检查（见 §9）。
- 错误返回统一 `{detail: str}` + 合适 HTTP 状态码。

---

## 3. 目标目录结构

```
self_learning_os/
├── CLAUDE.md                  # Claude Code 项目约定
├── SPEC.md                    # 本文档
├── TASKS.md                   # 任务看板
├── docker-compose.yml
├── .env.example
├── pyproject.toml
├── alembic/                   # 数据库迁移
│   └── versions/
├── app/
│   ├── main.py                # FastAPI 入口（替代旧 api/main.py）
│   ├── config.py              # pydantic-settings
│   ├── db.py                  # async engine / session
│   ├── deps.py                # 依赖注入（当前用户、db session）
│   ├── models/                # SQLAlchemy models
│   │   ├── user.py            # users, parent_student, guardian_consents
│   │   ├── learning.py        # exams, papers, wrong_questions
│   │   ├── cognitive.py       # kc_mastery, interaction_events, mastery_snapshots
│   │   └── parent.py          # parent_alerts, daily_reports
│   ├── schemas/               # pydantic I/O schemas
│   ├── routers/               # API 路由（按域拆分）
│   │   ├── auth.py
│   │   ├── papers.py
│   │   ├── cognitive.py
│   │   ├── socratic.py
│   │   ├── missions.py
│   │   └── parent.py
│   ├── services/              # 业务逻辑
│   │   ├── cognitive_service.py   # 包装 core/，落库
│   │   ├── ocr_service.py
│   │   ├── grading_service.py
│   │   ├── socratic_service.py
│   │   ├── mission_service.py
│   │   ├── analysis_service.py    # 纵向分析、共同断点
│   │   └── parent_service.py
│   ├── core/                  # 【已有】算法内核（保留）
│   │   ├── bkt.py
│   │   ├── fsrs_engine.py
│   │   └── cognitive_state.py # 重构：存储抽象为接口，PG 实现注入
│   ├── data/
│   │   └── guangdong_math_kc.py   # 【已有】，迁移为可入库的 seed
│   ├── llm/                   # LLM 封装与 prompt
│   │   ├── client.py
│   │   └── prompts.py
│   └── tasks/                 # Celery 任务
│       ├── ocr_tasks.py
│       ├── analysis_tasks.py
│       └── notify_tasks.py
├── tests/
│   ├── test_engine.py         # 【已有】
│   ├── test_cognitive_service.py
│   ├── test_papers_flow.py
│   └── test_compliance.py
└── frontend/                  # React PWA
    └── src/
```

> 迁移说明：旧 `core/`、`data/`、`tests/test_engine.py` 迁入 `app/core`、`app/data`，保持逻辑不变；旧 `api/main.py` 被 `app/main.py` 取代。

---

## 4. 数据模型（完整 DDL，权威）

> CC 用 SQLAlchemy 2.0 model + Alembic 实现以下表。字段不可随意增删，新增需在 TASKS 注明。

```sql
-- ========== 用户与合规 ==========
CREATE TYPE user_role AS ENUM ('student', 'parent');

CREATE TABLE users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone         VARCHAR(11) UNIQUE NOT NULL,
  role          user_role NOT NULL,
  name          VARCHAR(40),
  birth_date    DATE,                       -- 用于判定是否<14岁（合规）
  grade         VARCHAR(10),                -- 高一/高二/高三（student）
  province      VARCHAR(10) DEFAULT '广东',
  invite_code   VARCHAR(6) UNIQUE,          -- student 生成供家长绑定
  created_at    TIMESTAMPTZ DEFAULT now(),
  deleted_at    TIMESTAMPTZ                 -- 软删除（合规：可注销）
);

CREATE TABLE parent_student (
  parent_id     UUID REFERENCES users(id),
  student_id    UUID REFERENCES users(id),
  nickname      VARCHAR(20),
  display_order INT DEFAULT 0,
  created_at    TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (parent_id, student_id)
);

CREATE TABLE guardian_consents (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id     UUID REFERENCES users(id),
  guardian_phone VARCHAR(11) NOT NULL,
  consent_type   VARCHAR(50) NOT NULL,      -- data_collection/permanent_storage/...
  consent_version VARCHAR(20) NOT NULL,
  consented_at   TIMESTAMPTZ DEFAULT now(),
  ip_address     VARCHAR(45)
);

-- ========== 学习数据 ==========
CREATE TYPE paper_status AS ENUM ('processing', 'done', 'failed');
CREATE TYPE error_type AS ENUM ('conceptual','transfer','careless','logic_break','dontknow');
CREATE TYPE storage_tier AS ENUM ('hot','warm','cold','archived');

CREATE TABLE exams (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id    UUID REFERENCES users(id),
  exam_name     VARCHAR(100),
  exam_date     DATE,
  subject       VARCHAR(20) DEFAULT 'math',
  total_score   INT,
  scores        JSONB,
  created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE papers (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  exam_id       UUID REFERENCES exams(id),
  student_id    UUID REFERENCES users(id),
  subject       VARCHAR(20) DEFAULT 'math',
  grade         VARCHAR(10),
  image_urls    JSONB,                      -- OSS 地址列表
  ocr_result    JSONB,                      -- 结构化识别结果
  status        paper_status DEFAULT 'processing',
  storage_tier  storage_tier DEFAULT 'hot',
  created_at    TIMESTAMPTZ DEFAULT now(),
  archived_at   TIMESTAMPTZ
);

CREATE TABLE wrong_questions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  paper_id        UUID REFERENCES papers(id),
  student_id      UUID REFERENCES users(id),
  subject         VARCHAR(20) DEFAULT 'math',
  question_text   TEXT,
  student_answer  TEXT,
  correct_answer  TEXT,
  knowledge_points JSONB,                   -- ['GDMATH-CONIC-01', ...]
  error_type      error_type,
  profiler_analysis JSONB,                  -- LLM 错误细分输出
  -- FSRS 字段
  fsrs_card_json  JSONB,                    -- py-fsrs Card 序列化
  fsrs_due        TIMESTAMPTZ,
  fsrs_state      VARCHAR(20),
  created_at      TIMESTAMPTZ DEFAULT now()
);

-- ========== 认知状态（内核落库）==========
CREATE TABLE kc_mastery (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id         UUID REFERENCES users(id),
  knowledge_point    VARCHAR(100) NOT NULL,
  p_mastery          FLOAT,                 -- 当前 P(L)，NULL=用先验
  p_init             FLOAT NOT NULL,
  p_transit          FLOAT NOT NULL,
  p_guess            FLOAT NOT NULL,
  p_slip             FLOAT NOT NULL,
  long_term_mastery  FLOAT,
  last_interaction_at TIMESTAMPTZ,
  n_attempts         INT DEFAULT 0,
  updated_at         TIMESTAMPTZ DEFAULT now(),
  UNIQUE (student_id, knowledge_point)
);

CREATE TABLE bkt_priors (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subject         VARCHAR(20),
  grade           VARCHAR(10),
  knowledge_point VARCHAR(100),
  question_type   VARCHAR(20),
  p_init FLOAT, p_transit FLOAT, p_guess FLOAT, p_slip FLOAT,
  calibrated_from_n INT DEFAULT 0,
  updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TYPE interaction_source AS ENUM ('paper','quick','review','socratic');

CREATE TABLE interaction_events (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id      UUID REFERENCES users(id),
  knowledge_point VARCHAR(100) NOT NULL,
  question_id     UUID,                     -- 可空
  source          interaction_source NOT NULL,
  is_correct      BOOLEAN NOT NULL,
  fsrs_rating     SMALLINT,                 -- 1-4
  time_spent_seconds INT,
  days_since_last FLOAT,
  occurred_at     TIMESTAMPTZ DEFAULT now()
);
-- 这张表是未来 DKT 的训练数据，只增不改。

CREATE TABLE mastery_snapshots (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id      UUID REFERENCES users(id),
  knowledge_point VARCHAR(100),
  long_term_mastery FLOAT,
  dominant_error_type VARCHAR(20),
  grade           VARCHAR(10),
  snapshot_month  DATE,
  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE learning_patterns (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id      UUID REFERENCES users(id),
  pattern_type    VARCHAR(50),              -- reasoning_chain/topic_pref/time_of_day/cross_stage
  description     TEXT,
  confidence      FLOAT,
  evidence        JSONB,
  suggestion      TEXT,
  detected_at     TIMESTAMPTZ DEFAULT now(),
  user_marked_useful BOOLEAN
);

-- ========== 苏格拉底与目标 ==========
CREATE TYPE socratic_mode AS ENUM ('deep','mixed','sprint');
CREATE TYPE socratic_outcome AS ENUM ('success','partial','failed','abandoned');

CREATE TABLE socratic_sessions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id      UUID REFERENCES users(id),
  question_id     UUID REFERENCES wrong_questions(id),
  mode            socratic_mode,
  messages        JSONB,                    -- [{role, content, ts}]
  emotion_log     JSONB,
  outcome         socratic_outcome,
  used_escape_hatch BOOLEAN DEFAULT FALSE,
  duration_seconds INT,
  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TYPE mission_type AS ENUM ('review','socratic','upload','knowledge_focus');

CREATE TABLE daily_missions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id      UUID REFERENCES users(id),
  date            DATE,
  mission_type    mission_type,
  content         JSONB,
  estimated_minutes INT,
  completed       BOOLEAN DEFAULT FALSE,
  completed_at    TIMESTAMPTZ,
  created_at      TIMESTAMPTZ DEFAULT now(),
  UNIQUE (student_id, date)
);

CREATE TABLE streaks (
  student_id      UUID PRIMARY KEY REFERENCES users(id),
  current_streak  INT DEFAULT 0,
  longest_streak  INT DEFAULT 0,
  last_completed_date DATE,
  escape_count    INT DEFAULT 0,
  updated_at      TIMESTAMPTZ DEFAULT now()
);

-- ========== 家长端 ==========
CREATE TYPE alert_type AS ENUM ('emotion','score_drop','task_missing','time_drop','late_night');
CREATE TYPE alert_level AS ENUM ('notice','attention','important');

CREATE TABLE parent_alerts (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_id   UUID REFERENCES users(id),
  student_id  UUID REFERENCES users(id),
  alert_type  alert_type,
  alert_level alert_level,
  content     TEXT,
  sent_via    JSONB,
  is_read     BOOLEAN DEFAULT FALSE,
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE daily_reports (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id  UUID REFERENCES users(id),
  date        DATE,
  report_text TEXT,
  sent_at     TIMESTAMPTZ,
  delivery_status VARCHAR(20),
  UNIQUE (student_id, date)
);
```

---

## 5. API 契约（权威）

> 全部前缀 `/v1`。鉴权：除 auth 外，需 `Authorization: Bearer <jwt>`。
> CC 必须严格按此契约实现 request/response schema。

### 5.1 认证 `routers/auth.py`
```
POST /v1/auth/send-code        {phone}                       → {ok}
POST /v1/auth/register/student {phone, code, name, birth_date, grade,
                                guardian_phone?, guardian_consent?}  → {token, user}
POST /v1/auth/register/parent  {phone, code, name, invite_code}     → {token, user}
POST /v1/auth/login            {phone, code}                 → {token, user}
GET  /v1/auth/me                                             → {user}
```
合规：`register/student` 若 `birth_date` 显示 <14 岁，**必须**带 `guardian_phone`+`guardian_consent=true`，否则 422，并写入 `guardian_consents`。

### 5.2 试卷 `routers/papers.py`
```
POST /v1/papers/upload         multipart(images[], exam_name?, grade)
                               → {paper_id, status:'processing'}     # 异步OCR
GET  /v1/papers/{paper_id}                                   → {paper, wrong_questions[]}
GET  /v1/papers                ?student_id&from&to            → {papers[]}
POST /v1/papers/quick          multipart(image, kc_hint?)
                               → {question_id, socratic_session_id} # 单题快速录入
```
处理流程（异步 Celery）：见 §6.3。

### 5.3 认知状态 `routers/cognitive.py`（包装已有内核）
```
POST /v1/interaction           {kc_id, is_correct, used_answer?, struggled?,
                                effortless?, source, question_id?}
                               → {p_mastery, long_term_mastery,
                                  effective_mastery, error_type?, rating,
                                  next_review_due, n_attempts}
GET  /v1/mastery/{student_id}                                → {knowledge_points[]}  # 按薄弱排序
GET  /v1/mastery-curve/{student_id}/{kc_id}                  → {points:[{month,mastery}]}
GET  /v1/review-queue/{student_id}                           → {due_today[]}
GET  /v1/patterns/{student_id}                               → {patterns[]}  # 纵向分析
GET  /v1/kc · GET /v1/kc/{kc_id}                             → KC 字典（已有）
```

### 5.4 苏格拉底 `routers/socratic.py`
```
POST /v1/socratic/start        {question_id}                 → {session_id, mode, first_question}
POST /v1/socratic/{session_id}/message  {text|voice_text}
                               → SSE 流式：{delta} ... {done, emotion?, outcome?}
POST /v1/socratic/{session_id}/escape                        → {answer_outline}  # 逃生出口
POST /v1/socratic/{session_id}/end                           → {outcome, mastery_updated}
```

### 5.5 今日目标 `routers/missions.py`
```
GET  /v1/missions/today/{student_id}      → {mission, streak}
POST /v1/missions/{mission_id}/complete    → {streak, next_preview}
```

### 5.6 家长端 `routers/parent.py`
```
GET  /v1/parent/children                              → {children[]}
GET  /v1/parent/overview/{student_id}                 → {growth_summary, streak, emotion}
GET  /v1/parent/alerts/{student_id}                   → {alerts[]}
GET  /v1/parent/report/{student_id}?date              → {report_text}
GET  /v1/parent/export/{student_id}                   → 触发档案导出（PDF/JSON，合规）
POST /v1/parent/delete-request/{student_id}           → 触发数据删除流程（合规）
```

---

## 6. 各模块详细需求

### 6.1 认知 service（包装内核落库）
- 重构 `core/cognitive_state.py`：把 `CognitiveStore` 抽象成接口 `StateStore`，提供 `InMemoryStore`（测试）与 `PgStore`（生产，读写 `kc_mastery` + `wrong_questions.fsrs_card_json`）两种实现。
- `cognitive_service.process_interaction()`：调用内核 → 落库 `kc_mastery` → **追加 `interaction_events`**（只增不改）→ 返回快照。
- 每次更新顺序严格遵守 v1.3 §4：先用旧卡片算 R → forgetting-aware BKT 更新 → 答错则 classify_error → FSRS review → 落库。
- 月度 Celery 任务把 `long_term_mastery` 写入 `mastery_snapshots`（成长曲线数据源）。

### 6.2 KC 字典落库与扩展
- 把 `guangdong_math_kc.py` 的 `KC_LIST` 做成 seed，启动时 upsert 到 `bkt_priors`（按题型展开先验）。
- 扩展任务：补全二级知识点到 ≥ 50 个；权重按真实高考占比归一化（当前 222 分需校准到合理结构）。

### 6.3 试卷处理链（Celery）
```
upload → 存 OSS（hot）→ 创建 papers(processing)
  → [Celery] ocr_service: Claude Vision 结构化识别题目/学生答案/标准答案
  → grading_service: 逐题判对错
  → 对每道错题：analysis_service.profiler() (LLM 错误细分) + 关联 KC
  → 对每道错题：cognitive_service.process_interaction(source='paper', is_correct=False)
  → analysis_service.common_breakpoint()  # 共同断点（冷启动钩子）
  → papers(done)
```
- OCR/批改的 LLM prompt 放 `llm/prompts.py`，版本化。
- 失败重试 3 次；超时 papers(failed) 并允许用户手动纠错。

### 6.4 苏格拉底 service
- 直接调用 Claude API（`llm/client.py`），模式由 `mode` 决定（deep/mixed/sprint）。
- Prompt 铁律见 PRD v1.3：不给答案、每次一问、自主推导才推进。
- 流式 SSE 输出。
- 情绪感知：检测焦虑/崩溃关键词 → 暂停学术、记 `emotion_log`、≥3 次触发家长 `parent_alerts`。
- 逃生出口：`/escape` 记 `used_escape_hatch=true`，不影响 streak。
- 对话结束：判定 outcome → 映射 FSRS rating → `cognitive_service.process_interaction(source='socratic')`。

### 6.5 今日目标生成
优先级（见 PRD v1.2 M0）：
```
1. 有 FSRS 到期复习 → mission_type='review'
2. 当前最薄弱且未练的 KC → 'socratic' 或 'knowledge_focus'
3. >3 天未上传 → 'upload'
预计时长 ≤ 30 分钟（高三 sprint ≤ 15）；晚 23:00 后降级为「明天继续」。
```

### 6.6 家长端 service
- `growth_summary`：用 `long_term_mastery` 趋势 + 薄弱点数量变化（**不展示绝对分数**）。
- 微信日报：Celery 每晚生成（LLM prompt 见 PRD v1.3 §9.4），微信模板消息，失败降级短信。
- 5 类预警：emotion/score_drop/task_missing/time_drop/late_night（触发条件见 PRD v1.2 M7.4）。
- 多孩子：`parent_student` 已支持，前端切换。

---

## 7. 验收标准（每个 Epic 完成的硬指标）

| Epic | 验收 |
|------|------|
| 基建 | `docker compose up` 一键起全栈；`pytest` 全绿；`/docs` 可访问 |
| 持久化 | 重启服务后掌握度/复习状态不丢；`interaction_events` 正确累积 |
| 用户合规 | <14 岁无监护人同意无法注册（422 + 测试覆盖）；可导出/删除自己全部数据 |
| 试卷入口 | 上传一张样卷 → 异步处理 → 产生错题 + KC 关联 + interaction 事件 + 共同断点 |
| 认知层 | `/mastery` 按薄弱排序正确；成长曲线返回月度序列；`/patterns` 在足量数据下产出洞察 |
| 苏格拉底 | 流式可用；不泄露答案（红线测试）；情绪触发预警；逃生出口不影响 streak |
| 家长端 | 摘要不含绝对分数；日报生成；5 类预警可触发；多孩子切换 |
| 前端 | 学生：今日目标→拍题→苏格拉底→成长曲线 跑通；家长：摘要+预警 |
| 算法回归 | `test_engine.py` 持续通过；AUC ≥ 0.70 不退化 |

---

## 8. 关键质量门（CI 必须卡）

- `pytest` 全绿，覆盖率 ≥ 70%（service 层 ≥ 80%）。
- 苏格拉底「不泄露答案」红线测试：构造诱导 prompt，断言响应不含标准答案。
- 合规红线测试：<14 岁无同意注册必失败；删除请求后数据不可再查询。
- 算法回归：AUC ≥ 0.70；掌握度封顶 ≤ 0.97；连续答对单调不降。
- lint：ruff + mypy 通过。

---

## 9. 合规检查清单（未成年人，强制）

- [ ] 注册按 `birth_date` 判定 <14 岁，强制监护人手机验证 + 单独同意，写 `guardian_consents`。
- [ ] 《儿童个人信息处理规则》文案页。
- [ ] 数据加密：传输 TLS；OSS 服务端加密；DB 敏感字段加密存储。
- [ ] 数据可携带：`/parent/export` 导出全部档案（JSON + PDF）。
- [ ] 删除权：`/parent/delete-request` 触发软删 + 异步硬删（含 OSS 归档层）。
- [ ] 数据本地化：全部存储境内节点。
- [ ] 不得将未成年人数据用于广告或对外训练。

---

## 10. 环境变量（`.env.example` 必须包含）

```
DATABASE_URL=postgresql+asyncpg://user:pass@db:5432/selflearn
REDIS_URL=redis://redis:6379/0
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-4-6
S3_ENDPOINT=http://minio:9000
S3_BUCKET=papers
S3_ACCESS_KEY=
S3_SECRET_KEY=
JWT_SECRET=
JWT_EXPIRE_HOURS=720
WECHAT_TEMPLATE_ID=
SMS_PROVIDER_KEY=
ENV=dev
```

> LLM 模型字符串以实际可用版本为准，CC 应从配置读取，不写死在代码里。

---

## 11. 实施顺序（详见 TASKS.md）

```
Epic 0 基建 → Epic 1 持久化（接已有内核）→ Epic 2 用户与合规
→ Epic 3 试卷入口 → Epic 4 认知应用层 → Epic 5 苏格拉底
→ Epic 6 家长端 → Epic 7 前端 → Epic 8 部署/可观测 → Epic 9 合规收口
```
关键路径：0 → 1 → 3 → 4 是核心闭环（上传→内核→看见成长），优先打通。

---

**SPEC 结束。任何与本文档冲突的实现以本文档为准；需要偏离时先更新本文档再编码。**
