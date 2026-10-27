# Exam Cram 三嫁接（分支 feat/exam-cram-graft）

Exam Cram Coach 方法论的 Mneme 干净实现：方法可学，代码自己写，
未复制对方代码。生产部署不在本分支授权内，等 Soffy 另行拍板。

## 改动清单

嫁接 1 —— 溯源标签 + 超纲拒答门 + 资料防注入
- 新建 `services/provenance.py`（纯函数，无 DB/网络/LLM）：
  三档标签 MATERIAL / SUPPLEMENT / GENERATED；`certify_reply` 门禁
  （未标注段 = 未完成，不得交付；空回复亦不通过）；
  `gate_retrieval` + `build_refusal` 定型拒答（类型化 dict，不用
  HTTP 状态码 hack）；`scan_injected_instructions` 转向语句启发式
  + `fence_material` MATERIAL 围栏（检出只标记、不执行、不隐藏）。
- 接线：`services/chat_router.py` 的 `tool_chat_turn` 在结果上附加
  `provenance` 块（gate / certified / steering_hits / notice）；
  `services/socratic_service.py` 的 SSE done 事件附加同名 `provenance`
  块（来源：错题 id + KU id + 教材 id）。

嫁接 2 —— 错题优先重测队列 + 确定性小抄
- `services/wrongbook_review_service.py` 追加（既有
  `build_today_session` / `schedule_after_answer` / `answer_item` 未动）：
  `rank_review_items`（纯函数：到期 FSRS 项 → 错次多者 → 最近错者）、
  `build_priority_queue`（只读；错次取 question_records 里
  is_correct=False 的记录数，错题本行本身保底为 1）、
  `render_cheatsheet` / `build_cheatsheet`（确定性拼装：KU 描述 +
  未关闭错题；小结/困惑点仓内无存储，固定留空，绝不现编）。
- 接线：`services/routers/questions.py` 新增 `GET /v1/review/priority`
  与 `GET /v1/review/cheatsheet`（学生本人鉴权）；
  `services/mcp_router.py` 新增 `tool_get_wrongbook_priority_queue` +
  `GetWrongbookPriorityQueueReq` + `/GetWrongbookPriorityQueue`。

嫁接 3 —— 讲义 / 题目插图裁剪
- 新建 `services/figure_crop.py`：pypdfium2 可选依赖（缺失返回
  available=False 降级，不崩）；向量图区域聚类裁图（Pillow 裁切）；
  扫描页（无文字 + 单图盖大半页）整页跳过；对象键
  `figures/<doc>/p<页>_<号>.png`；`figures_for_message` 给出 tutor
  消息里的图引用字段。
- 存储：`services/storage.py` 按 question-images 同款模式新增
  lesson-figures 私有桶（ensure/upload/download/delete，只存键，
  不出签名 URL；桶在首次上传时惰性创建）。

测试：`tests/test_examcram_provenance.py`（16）、
`tests/test_examcram_wrongbook_graft.py`（12，含 mneme_test 库上
队列/小抄/路由/FSRS 分工）、`tests/test_examcram_figure_crop.py`
（7，含现场拼装的矢量页/扫描页夹具 PDF）。

## 如实记录的两处偏差（非偷工，是按仓内现状做的取舍）

1. FSRS 引擎：任务书说“调度复用 wordatlas_fsrs”，但错题本行早已
   用 oprim.fsrs_engine（py-fsrs）维护 `fsrs_card_json` 列，两种卡
   格式混写一列会 corrupt 数据。故嫁接 2 未换引擎：复用的是分工
   口径（FSRS 只排期、BKT 才是掌握裁决源，见
   `test_fsrs_schedule_does_not_write_mastery`），排序按任务书三规
   则新实现。如要统一引擎，须另立迁移。
2. chat 严格门默认关：`tool_chat_turn` 的 `strict_provenance`
   默认 False——循环当前只回纯文本，尚无分段标签，默认开会拦截
   全部知识回答。门禁函数本身（`certify_reply`）已对未标注判失败；
   生产切 strict 前，须先让循环输出分段标签。socratic 路因材料
   先天确定（错题 + KU + 教材），来源已如实附在 done 事件里。

## 前端待接点（未验证）

- tutor 聊天消息组件渲染 `figures[]`：每项经鉴权图片接口取字节
  （同 question-images 私有图片接口模式，不拼签名 URL）。后端字
  段 `figures_for_message` 已就绪，前端组件未改——真机展示未验证。
- socratic done 事件的 `provenance` 块、chat 结果的 `provenance`
  块，前端未展示——接口已就绪，展示未验证。

## 生产部署步骤（部署时按此执行，本分支不含迁移）

1. 前置：确认生产 main 在 e15557e（本分支基线）；备份生产库
   （沿用 word-atlas 部署同款整库备份）。
2. 合分支：`git merge feat/exam-cram-graft` 到 main 后 push。
   无 Alembic 迁移（未改任何模型列）；lesson-figures 桶首次上传
   时自动创建；pypdfium2 不装也能跑（裁图降级），要真裁图须把
   pypdfium2 加进生产镜像依赖并重建。
3. 重启 mneme-api（compose 惯例）；冒烟：`GET /v1/review/priority`
   与 `/v1/review/cheatsheet`（登录学生）、socratic done 事件含
   `provenance`、缺 pypdfium2 时裁图接口不崩。
4. 回退点：后端 main e15557e；回退 = revert 合并提交并重启 api。
   无数据迁移，故无数据回滚动作；lesson-figures 桶内对象如已产生
   可保留（新桶，不影响旧数据）。
