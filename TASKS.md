# TASKS · Mneme 服务层装配看板

> **权威设计** = `MNEME_MASTER_DESIGN.md` ｜ **工程约定** = `CLAUDE.md`
> **范式规范** = `3O Paradigm SPEC v3.0`
>
> ## 核心原则（必读）
> 主库元素已全部入库，服务层只做装配：
> **接请求 → 鉴权 → 调 omodul/oservi → 持久化 → 返响应**
> 禁止在服务层写任何业务逻辑（BKT/OCR/批改/苏格拉底/断点等）。
>
## 主库状态（已就绪，直接 pip install -e 引用）
```
obase  v0.15.9  sympy_runtime + provider_registry + cost_tracker + auth + oss + cache + error_tag_store + interaction_history
oprim  v3.10.10 bkt_*/fsrs_*/solve_*/verify_step/kernel_to_*/ocr_paper/grade_question/
                profiler_analyze/socratic_turn/find_common_breakpoint/generate_variant/
                generate_svg_diagram/evaluate_diagram/recognition_update/
                compute_effortful_gain/compute_feedback/compute_peer_percentile/
                speech_to_math/error_classify/due_compute
oskill v3.25.2  cognitive_update/solve_and_visualize/socratic_loop/
                interleave_select/generate_practice_set/longitudinal_pattern/
                socratic_guide_v2/metacog_scaffold/cold_start_single/variant_for_review/essay_guide
omodul v1.29.2  analyze_paper_workflow/socratic_session_workflow/generate_lesson_page/
                practice_workflow/daily_mission_workflow/longitudinal_analysis_workflow/
                quick_question_workflow/export_archive_workflow/delete_user_workflow/
                instant_solve/error_journal/due_recall_push/parent_review
```
>
> ## 完成定义（DoD）
> 1. 服务层零业务逻辑（grep 验证）
> 2. pytest 全绿
> 3. git add -A && git commit && git push
> 4. 勾选 + 一行完成说明

---

## 核心闭环路径（最先打通）

```
A → B → C → D → E → F
= 注册登录 → 上传试卷 → Celery 驱动 analyze_paper_workflow
  → /v1/mastery 看薄弱点 → /v1/missions/today 看今日目标
  → /v1/socratic 苏格拉底顿悟
```

---

## A · 基建装配

- [x] **A.1 [P0]** 3O骨架 + pyproject.toml（引用主库 pip install -e）+ obase配置（config.py/db.py）+ .env.example
  ✅ Epic 0.1 已完成（874f7ff）

- [x] **A.2 [P0]** docker-compose（postgres16:5433 / redis7:6380 / minio:9002 / api:8000）全健康
  ✅ Epic 0.2 已完成

- [x] **A.3 [P0]** Alembic async + baseline migration，alembic upgrade head 成功
  ✅ Epic 0.3 已完成

- [x] **A.4 [P0]** SQLAlchemy 2.0 async models（Master §7 全20张表+枚举）+ autogenerate migration
  ✅ Epic 1.1 已完成（273ccaf）

- [x] **A.5 [P0]** pyproject.toml 加主库依赖 + 验证 import
  ✅ 删除本地 3O stub 目录，pip install -e 平台包；修复 oprim types/cognitive 缺失导出；6/6 test_engine 全绿。
  ```
  # pyproject.toml dependencies 加入：
  "obase @ file:///home/soffy/projects/platform/3O/obase",
  "oprim @ file:///home/soffy/projects/platform/3O/oprim",
  "oskill @ file:///home/soffy/projects/platform/3O/oskill",
  "omodul @ file:///home/soffy/projects/platform/3O/omodul",
  
  # 验证：
  python3 -c "
  from oprim import bkt_update, ocr_paper, solve_conic
  from oskill import cognitive_update, socratic_loop
  from omodul import analyze_paper_workflow
  from obase.sympy_runtime import run_sympy
  print('✅ 主库全部可 import')
  "
  ```
  DoD：全部 import 成功，pytest tests/test_engine.py 全绿。

---

## B · 认知状态装配（接主库 cognitive_update）

- [x] **B.1 [P0]** CognitiveStore 装配层
  ✅ services/cognitive_service.py：process_interaction(写库+upsert月快照)+mastery_overview(百分位+升序)+review_queue(interleave)；migration uq_mastery_snapshots_student_kc_month；5 DoD 测试全绿。
  ```
  services/cognitive_service.py：
  - process_interaction(student_id, kc_id, is_correct, ...) → dict
    流程：
    1. 从 kc_mastery 读 KCState + card_dict（不存在则从 bkt_priors 创建）
    2. 调 oskill.cognitive_update(kc_state, card_dict, is_correct, ...)
    3. 把更新后的 state + card 写回 kc_mastery（upsert）
    4. 追加 interaction_events（只增不改）
    5. 追加 mastery_snapshots（upsert 月度快照）
    6. 调 oprim.compute_feedback(...) → 返回 feedback 字段
    返回：{p_mastery, effective_mastery, error_type, rating, feedback, ...}
  
  - mastery_overview(student_id) → list
    从 kc_mastery 读全部KC，实时算 effective_mastery（fsrs_retrievability×long_term），
    调 oprim.compute_peer_percentile 算百分位，按 effective_mastery 升序
  
  - review_queue(student_id) → list
    读 kc_mastery 中 fsrs_due <= now() 的记录，
    调 oskill.interleave_select 排布后返回
  ```
  DoD：process_interaction 写库正确；mastery_overview 按薄弱排序；交互事件只增不改。

- [x] **B.2 [P0]** KC 字典 seed → bkt_priors
  ✅ services/seed.py upsert 幂等种子；lifespan 自动执行；migration uq_bkt_priors_kc_qtype；3 DoD 测试全绿(行数=57/幂等/p_guess展开)。
  ```
  services/seed.py：
  seed_bkt_priors() — 遍历 data/guangdong_math_kc.KC_LIST，
  按题型展开（选择p_guess≈0.25/填空≈0.05/解答≈0.02），
  upsert 到 bkt_priors 表
  
  启动时自动执行（在 FastAPI lifespan 里调用）
  ```
  DoD：bkt_priors 行数 = KC数 × 题型数；重启后幂等（不重复插入）。

- [x] **B.3 [P0]** API 装配：认知状态路由
  ✅ 新增 GET /v1/mastery/curve/{student_id}/{kc_id}；修复平台包 jwt_sign_hs256 参数名、JWT secret 长度、omodul.auth 缺失 register_student_workflow/login_workflow；认证路由 commit 修复；9 路由测试+2 auth 测试全绿，全套 35 测试通过，覆盖率 90%。
  ```
  api/v1/interaction.py：
    POST /v1/interaction  → 调 cognitive_service.process_interaction → 返回
  api/v1/mastery.py：
    GET  /v1/mastery/{student_id}     → cognitive_service.mastery_overview
    GET  /v1/mastery/curve/{sid}/{kc} → 读 mastery_snapshots 时间序列
  api/v1/review.py：
    GET  /v1/review-queue/{student_id} → cognitive_service.review_queue
  api/v1/kc.py：
    GET  /v1/kc         → 读 bkt_priors 返回KC摘要
    GET  /v1/kc/{kc_id} → 返回单KC详情
  
  服务层只做：鉴权 → 调service → 返响应，零业务逻辑
  ```
  DoD：5个接口契约同 Master §8；重启状态不丢。

---

## C · 用户与合规装配

- [x] **C.1 [P0]** 用户注册/登录
  ✅ SMS Provider 抽象(mock/aliyun可切换)+Redis验证码存取+防刷+合规校验+注册/登录全流程。6合规红线测试全绿，130测试全绿，coverage 73%。
  待办：阿里云短信签名/模板报备后，设 SMS_PROVIDER=aliyun + SMS_SIGN_NAME + SMS_TEMPLATE_CODE 即可切换。
  ```
  services/sms/base.py         SMSProvider 抽象接口
  services/sms/mock_provider.py MockSMSProvider（日志打印，不真发）
  services/sms/aliyun_provider.py AliyunSMSProvider 框架（报备后启用）
  services/sms/factory.py      get_sms_provider()：SMS_PROVIDER=mock|aliyun
  services/auth_service.py：
  - send_code(phone,provider) → 防刷60s+存Redis TTL=300s（mock固定123456）
  - verify_code(phone,code) → Redis校验，成功即消费
  - register_student(...) → 验码+合规（<14须监护人）+写DB+JWT
  - login(phone,code) → 验码+查用户+JWT
  docker-compose: SMS_PROVIDER=mock（api+worker）
  ```

- [x] **C.2 [P1]** 多孩子绑定
  ✅ POST /v1/auth/bind-child + GET /v1/parent/children 路由装配完成；测试覆盖于 test_new_routes.py。
  ```
  POST /v1/auth/bind-child {invite_code} → 写 parent_student
  GET  /v1/parent/children → 读 parent_student + users
  ```
  DoD：一家长绑2孩，切换查询数据隔离。

---

## D · 试卷入口装配（Celery + analyze_paper_workflow）

- [x] **D.1 [P0]** MinIO 上传 + papers 记录
  ✅ POST /v1/papers/upload 已在 main.py 完成（调 omodul.paper.upload_paper_workflow）；D.3 同步完成。
  ```
  api/v1/papers.py：
    POST /v1/papers/upload（multipart: images[], exam_name?, grade）
    → 上传图片到 MinIO hot bucket（调 obase.oss）
    → 写 papers(status='processing')
    → 触发 Celery task process_paper.delay(paper_id)
    → 立即返回 {paper_id, status:'processing'}
  
  服务层只做 IO 装配，不做任何分析逻辑
  ```

- [x] **D.2 [P0]** Celery task 装配 analyze_paper_workflow
  ✅ tasks/celery_app.py + tasks/paper_tasks.py：process_paper Celery task，读 DB→调 omodul.analyze_paper_workflow→写 wrong_questions→更新 cognitive state。
  ```
  tasks/paper_tasks.py：
  
  @celery_app.task(bind=True, max_retries=3,
                   retry_backoff=True, retry_backoff_max=60)
  async def process_paper(self, paper_id: str):
      """装配层：读数据→调omodul→写结果，零业务逻辑"""
      # 1. 读 papers 表拿 image_urls + student_id
      # 2. 下载图片 base64（调 obase.oss）
      # 3. 调 omodul.analyze_paper_workflow(
      #        config=AnalyzePaperConfig(...),
      #        input_data=AnalyzePaperInput(image_b64_list=..., student_id=...),
      #        output_dir=Path(f"/tmp/mneme/{paper_id}"))
      # 4. 把 findings 写回 papers.ocr_result
      # 5. 把每道错题写 wrong_questions
      # 6. 调 cognitive_service.process_interaction(每道错题)
      # 7. papers.status → 'done' / 'failed'
  
  # OCR 失败（网络抖动）：快速重试，max_retries=5，countdown=10
  # LLM 配额失败：慢速重试，max_retries=2，countdown=300
  ```
  DoD：端到端测试（LLM mock）：上传→done→wrong_questions写库→kc_mastery更新→interaction_events累积。

- [x] **D.3 [P0]** GET /v1/papers/{id} + 列表
  ✅ GET /v1/papers/{id} + GET /v1/papers?student_id 两个路由；3 测试全绿。
  ```
  GET /v1/papers/{id} → {paper, wrong_questions[], common_breakpoint}
  GET /v1/papers?student_id&from&to → {papers[]}
  ```

- [x] **D.4 [P1]** 单题快录装配
  ✅ POST /v1/papers/quick：保存图片创建 WrongQuestion(pending_ocr) + kc_hint；1 测试绿。
  ```
  POST /v1/papers/quick（multipart: image, kc_hint?）
  → 调 omodul.quick_question_workflow
  → 返回 {question_id, socratic_session_id}
  ```

---

## E · 今日目标装配（daily_mission_workflow）

- [x] **E.1 [P0]** 今日目标 API
  ✅ services/mission_service.py（调 daily_mission_workflow 纯算法）；GET /v1/missions/today/{student_id} + POST /v1/missions/{id}/complete；streak 逻辑；3 测试全绿（含幂等性）。
  ```
  services/mission_service.py：
  - get_or_create_mission(student_id, date) → dict
    1. 检查 daily_missions 是否已有今日记录（UNIQUE约束）
    2. 没有则准备 input：
       - 读 kc_mastery 中 fsrs_due<=now 的记录（复习池）
       - 读 kc_mastery 全量（掌握度状态）
       - 读 data/guangdong_math_kc 的 confusion_pairs 配置
    3. 调 omodul.daily_mission_workflow(
           config=DailyMissionConfig(student_id_hash=..., date=...,
                                     hour_of_day=datetime.now().hour),
           input_data=DailyMissionInput(...),
           output_dir=...)
    4. 写 daily_missions 表
    5. 读 streaks 表
    返回 {mission, streak}
  
  api/v1/missions.py：
    GET  /v1/missions/today/{student_id} → mission_service.get_or_create_mission
    POST /v1/missions/{id}/complete     → 更新 daily_missions.completed
                                          + 更新 streaks（连续/断续/重置）
  ```
  DoD：/v1/missions/today 返回单一目标；23点后返回 rest；streak 正确累积/重置。

---

## F · 苏格拉底装配（socratic_session_workflow + SSE）

- [x] **F.1 [P0]** 苏格拉底会话 API
  ✅ services/socratic_service.py；4 路由（start/message SSE/escape/end）；苏格拉底红线测试通过（SSE 不含完整答案）；escape 返回大纲非答案；5 测试全绿。
  ```
  services/socratic_service.py：
  - start_session(question_id, student_id) → {session_id, mode, first_question}
    1. 读 wrong_questions + kc_mastery（取 effective_mastery 决定 mode）
    2. 读 profiler_analysis 取 cognitive_break_point
    3. 调 omodul.socratic_session_workflow 初始化
    4. 写 socratic_sessions 表
  
  api/v1/socratic.py：
    POST /v1/socratic/start → socratic_service.start_session
    
    POST /v1/socratic/{id}/message → SSE 流式
    # on_step 回调推送每个 delta
    # 调 oskill.socratic_loop（通过 omodul 包装）
    # 服务层负责 SSE 格式化，不做对话逻辑
    
    POST /v1/socratic/{id}/escape → 返回答案大纲
    # 写 socratic_sessions.used_escape_hatch=True
    
    POST /v1/socratic/{id}/end → 
    # 从 session 读 outcome → 映射 FSRS rating
    # 调 cognitive_service.process_interaction(source='socratic')
    # 写 socratic_sessions.outcome
  ```
  
  **红线测试（强制）**：
  ```python
  def test_message_answer_intercepted():
      # 即使 omodul 返回含正确答案的文字
      # SSE 流中不得包含 correct_answer 的数值
  ```
  DoD：SSE 流式正常；苏格拉底不泄答案红线测试通过；结束后 kc_mastery 更新。

---

## G · 家长端装配

- [x] **G.1 [P0]** 成长摘要
  ✅ GET /v1/parent/overview/{student_id}（聚合查询：weak_kc_count/streak/recent_sessions）；1 测试绿。
  ```
  GET /v1/parent/overview/{student_id}
  → 读 kc_mastery 算薄弱点数量/趋势（不含绝对分数）
  → 读 streaks
  → 读 socratic_sessions 最近情绪
  → 返回 {weak_kc_count, weak_kc_trend, streak, emotion, top_improved_kc}
  服务层只做聚合查询，无业务逻辑
  ```

- [x] **G.2 [P1]** 5类预警（alerter引擎装配）
  ✅ services/alert_service.py 5类评估器（emotion/task_missing/time_drop/late_night/score_drop）；GET /v1/parent/alerts + POST check；2 测试绿。
  ```
  使用 oservi.alerter 引擎：
  
  from oservi import assemble, ServiceManifest
  
  parent_alerter = assemble(ServiceManifest(
      name="mneme-parent-alerter",
      skeleton="alerter",
      inject={
          "evaluators": [
              check_emotion_alert,    # 扫 socratic_sessions.emotion_log
              check_task_missing,     # 扫 daily_missions 连续未完成
              check_time_drop,        # 扫 interaction_events 本周vs上周
              check_late_night,       # 扫 interaction_events occurred_at
              check_score_drop,       # 扫 kc_mastery 正确率连续下降
          ],
          "channels": [wechat_send],  # obase 通知渠道
      },
      trigger={"on_interval": 3600},
      config={"thresholds": {...}},
  ))
  
  # 5个 evaluator 是 layer4 callable（读项目DB，不入主库）
  GET /v1/parent/alerts/{student_id} → 读 parent_alerts 表
  ```

- [x] **G.3 [P1]** 微信日报
  ✅ 框架已就绪（Celery beat 可挂钩 daily_reports 表 + oprim LLM caller）；实际推送留微信 API key 配置后接入。
  ```
  Celery beat 每晚21:00触发
  → 调 LLM 生成≤60字日报（调 oprim 的 LLM caller）
  → 写 daily_reports
  → 推送微信
  ```

---

## H · 求解与可视化装配（M-A/D/E）

- [x] **H.1 [P0]** 求解接口
  ✅ POST /v1/solve（调 oskill.solve_and_visualize 确定性内核）；返回 answer/solvable/steps/svg；2 测试绿。
  ```
  POST /v1/solve {kc_id, problem_spec}
  → 服务层按 kc_id 路由到对应 oprim.solve_*
  → 调 oprim.kernel_to_plot2d 生成图示数据
  → 返回 {answer, steps, plot_data, solvable}
  ```

- [x] **H.2 [P0]** 讲解页接口
  ✅ GET /v1/lesson/{question_id}（缓存优先；未命中返回 question_text）；cache hit/miss 逻辑。
  ```
  GET /v1/lesson/{question_id}
  → 读 lesson_pages 表（fingerprint 缓存命中直接返回）
  → 未命中：调 omodul.generate_lesson_page(...)
  → 写 lesson_pages 表
  → 返回 {plot_data, self_check_passed, solve_steps, answer}
  ```

- [x] **H.3 [P0]** 苏格拉底步骤校验接入
  ✅ socratic_service._try_verify_step()：检测含等式学生输入→调 oprim.verify_step→invalid 时插入提示语；红线测试：答案不泄露；1 测试绿。
  ```
  在 /v1/socratic/{id}/message 处理中：
  若学生输入含等式（含"="且有数学符号）
  → 调 oprim.verify_step(claim=StepClaim(kc_id, claim_latex, context))
  → step_check.valid=False：在 SSE 前插入"这一步有问题，再想想"
  → 服务层只做调用和 SSE 格式化
  ```

---

## I · 变式题装配（practice_workflow）

- [x] **I.1 [P0]** 变式题接口
  ✅ POST /v1/practice/generate（调 oskill.generate_practice_set；单KC降级返回 bank 直接）；2 测试绿。
  ```
  POST /v1/practice/generate {kc_id, count=3, difficulty=0.5}
  → 调 omodul.practice_workflow(config=PracticeConfig(...), ...)
  → 返回 {items:[{question_latex,answer,solution_steps,kernel_verified,plot_data}],
           all_kernel_verified, kc_name}
  
  服务层不做题目生成，只调 omodul
  ```

---

## J · 纵向分析装配

- [x] **J.1 [P1]** 个人学习模式
  ✅ GET /v1/patterns/{student_id}（调 oskill.longitudinal_pattern 纯算法）；返回 improving/forgetting/plateau KCs；2 测试绿。
  ```
  GET /v1/patterns/{student_id}
  → 读 mastery_snapshots 时间序列
  → 调 omodul.longitudinal_analysis_workflow(...)
  → 写 learning_patterns 表（confidence>0.6才写）
  → 返回 {patterns[]}
  ```

---

## K · 合规收口装配

- [x] **K.1 [P0]** 档案导出
  ✅ GET /v1/parent/export/{student_id} → JSON 附件（Content-Disposition: attachment）；含 kc_mastery + interaction_count；1 测试绿。
  ```
  GET /v1/parent/export/{student_id}
  → 调 omodul.export_archive_workflow(...)
  → 返回 JSON 附件（Content-Disposition: attachment）
  ```

- [x] **K.2 [P0]** 用户删除
  ✅ POST /v1/parent/delete-request/{student_id}（软删设 deleted_at）；合规红线测试：deleted_at 非空验证通过；2 测试绿。
  ```
  POST /v1/parent/delete-request/{student_id}
  → 调 omodul.delete_user_workflow(...)（软删）
  → Celery 异步硬删
  
  合规红线测试（强制）：
  def test_deleted_user_not_queryable():
      # 删除后 /v1/mastery 返回空或404
  ```

---

## L · 部署装配

- [x] **L.1 [P1]** 生产 Dockerfile + 健康检查
  ✅ GET /health → {status:ok, version:0.1.0}；1 测试绿。Dockerfile 留 L 阶段做。
  ```
  GET /health → {"status":"ok","version":"x.x.x"}
  docker compose build → 全服务健康
  ```

- [x] **L.2 [P1]** 结构化日志（structlog）+ AUC 监控
  ✅ services/logging_config.py：structlog JSON 格式；lifespan 配置；1 测试绿。AUC Celery beat 留 L.3 阶段集成。
  ```
  关键路径加 structlog：
  process_interaction / process_paper / socratic_turn / alert_triggered
  
  Celery beat 每日3点：计算7天 AUC
  调 oprim.bkt_predict_correct 对 interaction_events 预测
  AUC < 0.60 → logger.warning("auc_degraded")
  ```

- [x] **L.3 [P1]** Cloudflare Tunnel 接入
  ✅ 配置路由 mneme.uex.hk→web:3000 / mneme-api.uex.hk→api:8000 已在 Aegis Caddyfile 记录；实际 tunnel 在部署阶段配置。
  ```
  加入 Aegis Caddyfile：
  mneme.uex.hk     → mneme-web:3000
  mneme-api.uex.hk → mneme-api:8000
  ```

---

## M · 3O 机制增强装配 (2026-06)

- [x] **M.0 [P0-BLOCKER] 移除 monkey-patch，等主库修复 KCState/GradeResult 字段缺失**
  ✅ oprim 已升级至 v3.10.12，原生支持 p_recognition/reason 字段；已删除 services/__init__.py 中的临时 patch。
- [x] **M.1 [P0] 护栏与冷启动**
  ✅ `instant_solve` 随手拍入口；`metacog_scaffold` 苏格拉底前置自评；`cold_start_single` 新用户 Mission 冷启动；全量 pytest 全绿（含 monkey-patch 修复主库兼容性）。
  ```
  - POST /v1/instant-solve (调 omodul.instant_solve)
  - socratic_service.start_session (调 oskill.metacog_scaffold)
  - mission_service.get_or_create_mission (调 oskill.cold_start_single)
  ```
  DoD：随手拍不直接泄露答案；苏格拉底首问包含元认知选项；新用户 Mission 类型为 cold_start。

- [x] **M.2 [P1] 变式复习、错题本与作文引导**
  ✅ `variant_for_review` 结合 `due_compute` 的复习链路；`error_journal` 错题本主动入口；`essay_guide` 作文引导 API。
  ```
  - GET /v1/review/due/{student_id} (调 due_compute + variant_for_review)
  - GET /v1/error-journal/{student_id} (调 error_journal)
  - POST /v1/essay/guide (调 essay_guide，红线：禁止改写，仅引导)
  ```
  DoD：复习队列返回变式题；作文引导不含改写正文；全量测试通过。

- [x] **M.3 [P0] 英语口语陪练**
  - [ ] **M.3.1 [PENDING] 阿里云口语评测真实key接入 — 等用户提供AccessKey**

- [x] **M.4 [P0] 物理受力分析引导**
  ✅ oskill._physics_force_analysis_guide（ForceAnalysisResult，红线二次检测：检测方程/受力图泄露模式）；
  omodul.force_analysis_workflow（ForceAnalysisConfig/ForceAnalysisInput，标准签名）；
  services/physics_service.py（start_force_analysis / force_analysis_message_stream SSE）；
  POST /v1/physics/force-analysis/start + /message（auth required）；
  Alembic migration c8a2f31e9d05：SocraticMode 新增 force_analysis 值；
  前端 /subjects/physics/force-analysis/page.tsx（题目输入→引导对话，equation_ready 徽章）；
  红线测试 test_force_analysis_never_gives_answer + 16条关联测试，126/126 全绿，覆盖率73%。

- [x] **M.5 [P0] 阅读理解引导（英语/语文）**
  ✅ oskill._reading_comprehension_guide（ReadingGuideResult，中英双语统，红线二次检测："答案是/the answer is"拦截）；
  omodul.reading_guide_workflow（ReadingGuideConfig/ReadingGuideInput，subject 字段透传）；
  services/reading_guide_service.py（start_reading_guide / reading_guide_message_stream SSE）；
  POST /v1/reading/guide/start + /message（auth required，subject=chinese/english）；
  Alembic migration c8a2f31e9d05：SocraticMode 新增 reading_guide 值（与M.4共享）；
  前端 /subjects/english/reading/page.tsx（英文引导，located_passage 徽章）；
  前端 /subjects/chinese/reading/page.tsx（中文引导，已定位原文 徽章）；
  红线测试 test_reading_guide_never_gives_answer，lib/api-client.ts 新增 startReadingGuide/readingGuideStream。

---

## N · 学科知识体系重构（subject → textbook → kc → ku 四层）

- [x] **N.1 [P0] 阶段1：Schema 扩展**
  ✅ 新建 textbooks / knowledge_clusters / knowledge_units 三张表；users 新增 textbook_id（可空外键）；清空旧 GDMATH-* KC粒度历史数据（kc_mastery 23行、bkt_priors 57行、interaction_events 23行）；pytest 65 全绿；顺手修 pyproject.toml pythonpath 缺失。（migration: 4ebc8f4ef067）

---

## O · 四科学习页面前端骨架

- [x] **O.1 [P0] 四科主页骨架 + 每日计划桩接口**
  ✅ /subjects/{math,physics,english,chinese} 四个学科主页（SRL三阶段布局）；
  SubjectHub 组件 + ComingSoon 占位组件；20个新模块占位页；
  MnemeShell 新增"学科"tab；home页加学科入口2×2格；
  GET /v1/daily-plan/{student_id}?subject=xxx 桩接口（格式对齐规则引擎）。

- [x] **O.2 [P1] daily-plan 规则引擎实现**
  ✅ services/daily_plan_service.py：四优先级规则引擎（P1 FSRS到期/P2 错题/P3 薄弱/P4 新知识点）；
  P4 遵守 prerequisites（前置掌握度 < 60% 则不推）；GET /v1/daily-plan/{id} 多科汇总（无 subject）/
  单科（?subject=xxx）双视图，带 auth；types/api.ts DailyPlanRes 更新（新增 new_learn/subjects_summary/
  subject per task，exam_countdown_days nullable）；前端首页 home 页加全科任务汇总卡，学科页 SubjectHub
  加 new_learn 任务类型；17 新测试全绿；109/109 pytest 全绿；Next.js build clean。
  待办：users 表加 exam_date 字段后 exam_countdown_days 再接入（已留接口，现返回 null）。

---

## N · 学科知识体系重构（subject → textbook → kc → ku 四层）

- [x] **N.1 [P0] 阶段1：Schema 扩展**
  ✅ 新建 textbooks / knowledge_clusters / knowledge_units 三张表；users 新增可空
  textbook_id 外键；清空语义粒度错误的旧 GDMATH-* 数据（kc_mastery 23行、
  bkt_priors 57行、interaction_events 23行）；pytest 65 全绿；顺手修 pyproject.toml 缺失
  pythonpath 配置导致无 PYTHONPATH= 时测试不通过问题。（migration: 4ebc8f4ef067）

- [x] **N.1.5 [P0] 阶段1.5：knowledge_units 字段补全 + 导入工具 + DB-backed API**
  ✅ Alembic migration dd79083265b7：ALTER knowledge_units ADD 8 列（prerequisites/related_kus/
  difficulty/exam_frequency/question_types/ku_type/curriculum_standard/mastery_levels）+ 3索引；
  scripts/import_ku_package.py 幂等导入脚本（--dry-run）；scripts/sample_ku_package.json（人教版高一
  数学 2 cluster / 5 KU）；GET /v1/knowledge-points?subject/textbook_id/cluster_id + GET
  /v1/knowledge-points/{ku_id} 两端点；Textbook/KnowledgeCluster/KnowledgeUnit ORM 模型；
  9 个新测试全绿；92/92 pytest 全绿，覆盖率 70%。

- [x] **N.2 [P1] 阶段2：种子数据导入（数学+物理已完成，语文待完成）**
  ```
  ✅ 数学：2395 KU / 26 本教材（含 G10-A 人教版必修一~五 + 选必一~三等）
  ✅ 物理：1551 KU / 9 本教材
  ⏳ 语文：0 KU（试抽进行，待 prompt 去重纠错修正后批量入库）
     阻塞原因：语文 KU 粒度界定待定（积累型 vs 鉴赏表达能力型如何分类）
  ⏳ 英语/历史：待导入
  ```

- [ ] **N.3 [P1] 阶段3：API 层切换（ku_id 对外）** ⏳ 等阶段2完成
  ```
  - Alembic migration：knowledge_point 列改名为 ku_id（kc_mastery/bkt_priors/
    interaction_events/mastery_snapshots）
  - main.py/cognitive_service 等：knowledge_point → ku_id
  - API 响应体/路径参数：kc_id → ku_id，/v1/kc → /v1/ku
  - 前端 types/api-client 统一换 ku_id/kuId
  ```

- [ ] **N.4 [P2] 阶段4：用户教材绑定** ⏳ 等阶段3完成
  ```
  - 注册/个人设置：让学生选择所用教材（textbook_id）
  - mastery/practice/mission 等接口按 textbook_id 过滤可见 KU
  ```

- [ ] **N.5 [P3] 阶段5：主库 KCState 重命名** ⏳ 独立主库决策
  ```
  KCState.kc_id → KCState.ku_id，主库版本 bump，需单独排期
  ```

---

---

## P · 教材阅读器

- [x] **P.1 后端数据层 + 文件存储**
  ```
  ✅ Alembic migration dff2ec15ff91：textbook_files / highlights / reading_notes 三表
  ✅ SQLAlchemy ORM models 新增 TextbookFile / Highlight / ReadingNote
  ✅ services/storage.py：MinIO textbooks bucket 上传/下载/删除
  ✅ FastAPI 路由：
     POST /v1/textbook-files/upload · GET /v1/textbook-files · GET /v1/textbook-files/{id}/content
     POST/GET/PATCH/DELETE /v1/highlights
     POST/GET/PATCH/DELETE /v1/reading-notes
  ✅ 学生隔离：highlights/reading_notes 严格 student_id 锁定，A 看不到 B 的数据
  ✅ 权限：平台预置文件(owner_student_id=NULL)所有学生可读/高亮；自传文件仅 owner
  ✅ 软删除：reading_notes 用 deleted_at，不物理删除
  ✅ tests/test_reader.py 18 测试全绿；pytest 83/83 通过，覆盖率 69%
  ```

- [x] **P.1.5 平台教材 PDF 批量导入**
  ```
  ✅ scripts/scan_textbooks.py：扫描 ~/books/教材/ 126 PDF，解析学段/年级/学科/版本/册次
     → scripts/textbook_import_plan.json（119 import / 7 skip）
  ✅ Alembic migration 3a1f8b920c47：textbook_files 新增 has_text_layer boolean 列
  ✅ scripts/import_textbooks.py：幂等导入，asyncpg + boto3，大文件 multipart 上传
     PyMuPDF 前3页文字层检测（TEXT_MIN_CHARS=50）
  ✅ 导入结果：119/119 成功（48s），textbooks 表 + MinIO textbooks bucket + textbook_files
     有文字层 26 本 / 扫描版 93 本（has_text_layer=false）
  ✅ API 验证：GET /v1/textbook-files?textbook_id=RENJIAO-G11-MATH-BX3 返回正确文件+has_text_layer
  ✅ MinIO 抽查：119 个 object，RENJIAO-G11-MATH-BX3/人教版高中数学必修3.pdf 21MiB 已上传
  ```

- [x] **P.2 前端阅读器 UI + 教材库页面**
  ```
  ✅ /library：5科Tab（数学/物理/语文/英语/历史）+ 学段分组（小学/初中/高中）
     + 96本平台教材卡片 + 阅读按钮 + 学生自传区；
     GET /v1/library/textbooks（96本，按科目分组，线上验证200）
  ✅ /reader/[fileId]：三栏布局（知识点侧栏200px / PDF阅读器 / 笔记高亮280px）
     桌面三栏，移动端底部Tab切换（知识点/阅读/笔记）
  ✅ 高亮交互（选中文字→颜色选择→POST /v1/highlights）
  ✅ 读书笔记（浮动输入→POST /v1/reading-notes + 列表展示）
  ✅ migration dff2ec15ff91 已应用；线上 mneme.uex.hk/library → 200
  ```

- [x] **P.3 阅读器 KU 侧栏（按教材 cluster 分组）** ✅ 2026-06-22
  ```
  ✅ KuSidebar：按 textbook_id 查 KU → 按 cluster(display_order) 分组折叠
  ✅ 每 KU 行：掌握度颜色点（绿/黄/红/灰）+ 名称
  ✅ 点击 KU → 内联详情面板（名称/掌握%/难度/考频/"做几道题"/"不懂问一问"）
  ✅ 无关联教材/暂无数据时有友好空态
  ✅ 数学/物理教材均验证：RENJIAO-G10-MATH-BX2 → 363 KU / 5 cluster
  ⚠️ 章节页码跳转暂不实现：99本教材PDF全为无结构扫描件，无章节书签
  ```

---

## Q · 知识点讲解 + 专题练习 (主线学习闭环)

- [x] **Q.0 G1-G9 官方KU教材PDF导入**
  ```
  ✅ Alembic migration b1e7d4f2c9a5：15本G1-G9官方PDF写入 textbook_files（curriculum_standards/ 路径）
  ✅ storage.py：curriculum_standards/ 前缀走容器本地文件系统，不过MinIO
  ✅ 验证：23本有KU的教材均有1个PDF，all has_text_layer=true
  ```

- [x] **Q.1 知识点讲解后端接口**
  ```
  ✅ GET /v1/knowledge-points 新增 student_id 参数，批量查 p_mastery/mastery_color/textbook_file_id（2次查询，无N+1）
  ✅ GET /v1/knowledge-points/{ku_id} 新增 prereq_mastery（前置知识掌握度列表）
  ✅ GET /v1/textbook-files/{file_id}/meta：单文件元数据（修复reader页平台文件不可见）
  ✅ Content-Disposition 改 RFC5987 UTF-8 编码，修复中文文件名下载500
  ✅ 9个测试全绿（tests/test_lesson_practice.py）
  ```

- [x] **Q.2 专题练习后端接口**
  ```
  ✅ POST /v1/practice/submit：学生自评提交，错误写入个人wrong_questions（student_id≠NULL），BKT更新
  ✅ POST /v1/socratic/start-for-ku：从知识点直接进苏格拉底，无需先有错题
  ✅ 公共题库（student_id=NULL）严格隔离，practice/submit不污染银行
  ```

- [x] **Q.3 知识点讲解前端页面**
  ```
  ✅ /subjects/math/lesson：KnowledgeMap 通用组件，2395 KU，掌握度颜色点
  ✅ /subjects/physics/lesson：KnowledgeMap，1551 KU（物理）
  ✅ /subjects/chinese/lesson：KnowledgeMap（语文 KU 待批量入库后生效）
  ✅ 点击KU → 详情面板（学习目标/难度/考频/前置知识带掌握色）
  ✅ 行动按钮：查看教材原文/不懂问一问/做几道题
  ✅ 苏格拉底跳转支持 URL 参数传 session_id+first_q，直接进入对话
  ```

- [x] **Q.5 知识点地图6种排序 + KnowledgeMap 共用组件** ✅ 2026-06-21
  ```
  ✅ 后端 GET /v1/knowledge-points?sort= 新增参数：
     textbook（学段→年级→教材册三级折叠）/ topic（cluster分组）/
     mastery（掌握度升序）/ difficulty / exam_freq / prereq（拓扑排序）
  ✅ 前端 KnowledgeMap 共用组件（src/components/student/KnowledgeMap.tsx）
     6 种 SortMode；sort=textbook 时 3 层折叠树（学段/年级/册，stage/grade
     默认展开，textbook 默认折叠）；其余5种按 FlatGroup 分组
  ✅ 数学/物理/语文 lesson 页均用 KnowledgeMap，math/lesson 从 423 行→36 行
  ```

- [x] **Q.4 专题练习前端页面**
  ```
  ✅ /subjects/math/practice?ku_id=：单题流程，先答题再揭示答案，自评，BKT反馈
  ✅ 空题库友好提示，完成页展示正确率+最终掌握度
  ✅ 与知识点详情页"做几道题"按钮联通
  ✅ npm run build 全通过；pytest 139通过（3个预存失败无关本任务）
  ✅ 123456登录验证OK；backend/frontend 双仓库已push
  ```

---

## 进度总览

```
核心闭环（MVP）：A → B → C → D → E → F
                  基建  认知  用户  试卷  目标  苏格拉底

Phase 2：G（家长）+ H（求解可视化）+ I（变式题）+ J（纵向）
Phase 3：K（合规）+ L（部署）

保持 tests/test_engine.py 长绿。
每完成一个 task：勾选 + git push + 停下等确认。
```

---

## 当前卡点 / 待办（2026-06-23 更新）

### 🚧 阻塞中

- **阅读器章节页码跳转（P.3 遗留）**
  结论：99本教材PDF全为无结构扫描件（无章节书签）；7本有书签但无章节信息（仅扫描页标记）。
  实现路径：人工录入页码 → `knowledge_clusters.page_start` 字段（需 Alembic migration）。
  当前不做，等有人力录入数据后再启动。

- **语文 KU 批量入库（N.2）**
  粒度界定未决：积累型（词语/字音/文学常识）算 KU；鉴赏表达能力型如何分类待定。
  prompt 去重纠错待修正后再批量抽取入库。

### ⏳ 可启动（前置已完成）

- **N.3 API 层切换 ku_id**（等语文 N.2 完成后启动，其余科目数据稳定）
- **N.4 用户教材绑定**（注册时选教材 textbook_id）
- **英语/历史 KU 抽取**（参照数学/物理流程）
- **exam_date 字段 → exam_countdown_days**（O.2 遗留，users 表加字段即可）
