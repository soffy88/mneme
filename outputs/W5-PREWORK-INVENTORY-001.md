# W5 前置查证盘点（W5-PREWORK-INVENTORY-001）

**日期**：2026-07-19
**性质**：五项并行只读调查，均未改动任何代码/生产状态。为可能的 W5
（Partners 多渠道机器人）epic 做准备，同时闭环上一轮记的挂起项
（sympify/eval/exec 全仓 grep）。

**环境说明**：用户提到的 tarball `/tmp/dt` 在本次会话环境里不存在（只有
一份不相关的旧 dump `/tmp/deeptutor_ref`，只含 Book Engine 文件）。凡涉及
DeepTutor 源码的调查，均改为直接从 `github.com/HKUDS/DeepTutor` 上游拉取
（同本会话更早处理"PORT-PLAN-001 不存在"的方式一致），已在各节标注。

---

## 1. Partners 死代码债：`tasks/partner_tasks.py` + `vendor/oskill/socratic_loop.py`

**结论：`tasks/partner_tasks.py` 不是死代码——它挂在生产 Celery beat 里，
每天 17:30（Asia/Shanghai）真实触发，且当前必崩。**

- `tasks/celery_app.py` 把 `tasks.partner_tasks` 列入任务模块表，注册了
  真实 schedule：`"daily-partner-push": {"task": "tasks.partner_push",
  "schedule": crontab(hour=17, minute=30)}`。
- `tasks/partner_tasks.py:39`：`student.last_login or student.created_at`
  ——`User` 模型（`services/models.py`）根本没有 `last_login` 字段，直接
  `AttributeError`，实测对真实 DB 跑过、真实复现。这是第一个符合条件的
  学生就会炸的阻塞性错误。
- `tasks/partner_tasks.py:42,61`：`student.username`——`User` 也没有这个
  字段（只有 `.name`），修完上一条会立刻撞到这条同类错误。
- 好消息：其余逻辑（`WrongQuestion` 字段用法、`email_provider.send_
  notification` 签名）都对得上真实模型；此前已修的 `SessionLocal`
  导入问题也确认生效，`import tasks.partner_tasks` 本身干净。
- 因为生产 `EMAIL_PROVIDER=mock`，就算把上面两个属性错修了，现在也不会
  真的发邮件（只是 mock 记日志）——但这个任务**目前每天都在静默失败**，
  不是"还没启用"，是"启用了但每次都炸"。
- `vendor/oskill/socratic_loop.py`：导入干净，完全不碰 `User`，找不到
  `last_login`/`username` 相关问题；调用的 `retrieve_chunks`/
  `format_chunks_as_context`/`socratic_turn` 签名全部核对一致。未做端到
  端调用（需要真实 LLM caller + 已有教材 chunk，静态审查没发现缺陷）。

---

## 2. DeepTutor Partners 架构盘点（上游直取，非 tarball）

目录不在顶层，都在 `deeptutor/` 包下：`deeptutor/partners/`、
`deeptutor/services/partners/`、`deeptutor/services/subagent/`。文件数
基本对得上（30/8/13），但**渠道适配器实际是 16 个，不是 18 个**——如实
记录这个出入，不强行凑数（可能是之前把 QQ 的两条路径分别计数，或者是
记忆偏差）。

**`deeptutor/partners/`（30 文件）**：
```
bus/(3)  events.py(InboundMessage/OutboundMessage) + queue.py(MessageBus)
channels/(20)  base.py(BaseChannel 抽象) + manager.py(ChannelManager) +
               registry.py(pkgutil+entry_points 动态发现) + 16 个适配器
config/(3)  paths.py + schema.py(每渠道 Pydantic 配置)
helpers.py + network.py + transcription.py(Groq Whisper 语音转写)
```

**`deeptutor/services/partners/`（8 文件）**：`manager.py` 里
`PartnerManager`/`PartnerInstance`（一个 partner = 一个 MessageBus + 一个
ChannelManager + 一个 PartnerRunner）；`runtime.py` 是 agent 侧消费循环。

**`deeptutor/services/subagent/`（13 文件）**：`partner.py` 让一个
partner 把另一个 partner 当"子代理"调用（走对方 web 入口/对话循环，不是
像 Claude Code/Codex 那样起子进程）。

**16 个渠道适配器**：

| 适配器 | 平台 | 外部 SDK |
|---|---|---|
| telegram.py | Telegram | `python-telegram-bot` |
| slack.py | Slack | `slack-sdk`（Socket Mode） |
| feishu.py | 飞书 | `lark-oapi`（惰性可选） |
| dingtalk.py | 钉钉 | `dingtalk-stream` |
| wecom.py | 企业微信 | `wecom-aibot-sdk`（惰性可选） |
| qq.py | QQ 官方机器人 | `botpy` |
| matrix.py | Matrix | `matrix-nio` |
| zulip.py | Zulip | `zulip` 官方绑定 |
| napcat.py | 个人 QQ（OneBot v11） | 无官方 SDK，逆向协议 |
| whatsapp.py | WhatsApp | Node.js 桥接进程 + websockets，无 Python SDK |
| discord.py | Discord | 无——纯 httpx+websockets 自实现 |
| mattermost.py | Mattermost | 无——纯 REST+WS 自实现 |
| msteams.py | MS Teams | 无——内置 HTTP webhook server |
| mochat.py | Mochat | 无 SDK，纯 Socket.IO 协议 |
| weixin.py | 个人微信 | 无官方 SDK，走第三方 HTTP 长轮询接口 |
| email.py | 邮件 | 标准库 imaplib/smtplib |

**事件总线**：纯进程内 `asyncio.Queue` 发布订阅，**没有外部 broker**
（不是 Redis/Kafka）。`MessageBus` 持有 `inbound`/`outbound` 两个队列。
入站：渠道适配器 → `BaseChannel._handle_message` → `publish_inbound` →
`PartnerRunner.run()` 消费、每条消息起一个 `asyncio.Task`（同 session 用
锁串行化）→ 处理完 `publish_outbound`。出站：`ChannelManager._dispatch_
outbound()` 消费队列 → 查渠道实例 → 流式增量合并/去重 → 重试发送。
**关键点：MessageBus 是按 partner 实例化的，不是全局单例**——每个 partner
（机器人身份）有自己独立的总线，渠道适配器按 partner 配置动态加载。

---

## 3. 多用户现状：AA.1 覆盖面 vs DeepTutor multi_user

**Mneme 现状：完全扁平。**

- `services/auth_deps.py`：`get_current_user`（解 JWT，纯按账号，token
  里无 session/租户概念）；`_ensure_student_access`（学生本人或绑定家长
  可读）；`_ensure_student_self`（写只能本人）。`UserRole` 只有
  `student`/`parent` 两个值，没有 teacher/admin/org。
- AA.1 遗留的 401 问题（TASKS.md:2100-2113，`tutor_loop.py` 的 `_mcp()`
  没带 token）**已在 C1 chat-workspace 工作中修复**（commit `1a6f63a`）。
- 全仓 grep `multi_user`/`tenant_id`/`workspace_id`/`organization_id`
  **零命中**。唯一的"分组"概念是 `cohort`（FSRS 权重拟合用的统计人群
  标签，跟权限/组织架构无关）。
- 结论：一个部署 = N 个独立学生账号，每个可选绑定 N 个家长做只读监督；
  没有班级/学校/工作区层级，没有按用户的 LLM/工具授权，没有 admin 角色。

**DeepTutor `multi_user`（13 文件，`deeptutor/multi_user/`）**：单租户、
文件系统隔离、admin/user 两角色（不是真正多租户——一个部署一个 admin）。

关键能力（Mneme 完全没有的）：
- 按用户物理隔离的文件系统工作区（`data/users/<uid>/`）。
- admin 为每个用户精细授权：`models.llm`/`knowledge_bases`/`skills`/
  `partners`/`enabled_tools`/`mcp_tools`——只存逻辑 ID，`validate_grant`
  显式拒绝任何 `api_key`/`token`/`path` 字段进入授权记录。
- 按用户脱敏的 LLM/provider 访问——非 admin 永远看不到真实
  provider/base_url，只看到 admin 批准的 profile+model 名字。
- 按用户工具/MCP 白名单，默认拒绝（`mcp_tools=None` = 零工具，需 admin
  显式授权）。
- 独立审计日志（`log_usage`/`log_admin_action` 分开记 JSONL）。
- admin 管理路由（用户/授权 CRUD）。

**都没有的**："一个老师管一个班"这种层级——DeepTutor 的 admin 更像"工作区
所有者"，不是班级教师；两边都不解决真正的多校/多租户隔离。如果未来要做
班级/学校级隔离，两边代码都要新写；DeepTutor 更适合参考的是"按用户资源/
工具授权"和"数据隔离"，不是组织架构层级。

---

## 4. 🔴 sympify/eval/exec 全仓 grep（上一轮挂起项，本轮做实）

**结论：找到 5 个新的、真实处理外部输入、完全未加固的裸符号解析点，一个
都不在 `sandbox_selfcheck.py` 的白名单里。** 7 个 `solve_*` 内核 + 2 个
可视化内核确认干净（S0/Visualize 已加固）；全仓无裸 Python
`eval(`/`exec(`/`compile(`/`__import__(`（`sympy_runtime.py` 内部的
`eval(`/`compile(` 调用前面都有 `_validate_ast()`，是既定安全模式本身）；
`apps/mneme-studio` 前端源码无 `eval(`/`new Function(`（只在 `.next/`
构建产物里出现，不算第一方代码）。

| 文件:行 | 外部输入来源 | 是否加固 | 已在白名单 |
|---|---|---|---|
| `vendor/oprim/verify_step.py:69` | 学生聊天消息 + OCR 手写步骤（`socratic_service._try_verify_step`、`paper_grading.verify_steps_chain`） | 否——裸 `sp.sympify()`，`timeout` 字段声明了但从未真正用上（纸面保护） | 否 |
| `vendor/oprim/grade_question.py:78-79` | HTTP 请求体 `student_answer`（判分主链路） | 否 | 否 |
| `vendor/oprim/compute_feedback.py:260` | `student_answer`（`cognitive_service.py`） | 否 | 否 |
| `vendor/oprim/compute_feedback.py:277-278` | 同上 | 否 | 否 |
| `services/socratic_service.py:331` | 学生聊天消息，**无字符集过滤** | 否——用的是 `parse_expr()`，跟 `sympify()` 同一类风险但字符串形态不同，**自检的字符串匹配方式本身抓不到它** | 否 |
| `services/socratic_service.py:393-401` | 学生聊天消息，但经正则预过滤成纯数字/运算符 | 部分——入口窄化了攻击面，但底层 `verify_step.py` 本身仍未加固 | 否 |
| `vendor/oskill/paper_grading.py:86-99` | OCR 识别的学生手写步骤，**无字符集过滤** | 否——五个发现里外部输入面最宽的一个（恶意图片即可触达） | 否 |

**两个需要一起看的系统性问题**：
1. 这 5 个点全部处理**未成年学生的真实输入**（聊天/判分/OCR），不是
   内部/测试数据——风险等级不是"理论上"，是"每次学生答题/发消息/交作业
   照片都会触达"。
2. `sandbox_selfcheck.py` 目前的检测方法本身有盲区：只 `glob("solve_
   *.py")` + 硬编码 `VISUALIZATION_KERNELS`，且只字符串匹配
   `"sp.sympify("`/`"sympy.sympify("`——`parse_expr()` 这种同类风险的
   API 完全绕过这个检测方式，就算把文件加进白名单也测不出来。self-check
   需要扩展检测模式，不只是扩展文件清单。

**误报排除**（确认无风险，不需处理）：`okx_rest_call.py` 的
`__import__("json")`（硬编码字面量）；`_validate_html.py` 里的
`"eval("` 只是文档字符串描述检测目标，不是调用；全部 `re.compile(...)`
（跟代码执行无关，纯因为 grep 子串命中）；各类
`subprocess_exec`/`docker_container_exec`（进程执行，属于不同的漏洞
类别，不是本次 sympify/eval 调查范围）。

---

## 5. 国内渠道可达性：微信/企业微信/飞书

| | 微信公众号 | 微信个人号 | 企业微信 | 飞书 |
|---|---|---|---|---|
| 起步门槛 | 免费测试号（扫码即得），无需营业执照 | **无官方 API**，只有逆向协议 | 免费自建测试企业 | 免费测试租户，权限免审 |
| 上真实用户门槛 | 服务号需真实企业认证（营业执照），订阅号个人可注册但 1条/天 | 不可行——违反 ToS，封号风险真实存在 | 真实注册企业 + 管理后台 | 真实注册组织，应用变更需企业管理员审核 |
| 零门槛替代方案 | 无（认证前提无法绕开） | 无 | **群机器人 webhook**：群内右键添加，无需开发者账号/企业认证 | **自定义机器人 webhook**：群设置里加，无需管理员审批 |
| 免费可本地测试 | 是（测试号覆盖大部分推送/回复 API） | 否 | 是（两档：自建应用 dev 或纯 webhook） | 是（两档同上） |
| 主要坑 | 订阅号 1条/天、服务号 4条/月的推送上限是硬顶；认证年费约 300 元 | **不建议用于面向未成年人数据的正式产品**——无官方保障，ToS 违规 | 群 webhook 只能推送、不能收回复，且需要群已存在 | 同上，群 webhook 只能推送；正式 DM/收回复需完整应用+管理员审核 |

**仓库现状**：`.env.example`/`services/`/`tasks/` 全仓 grep 零命中真实
微信/企业微信/飞书凭据或 provider 代码。`vendor/omodul/notification_
dispatch_workflow.py` 有一个 `channel: Literal["email","web","wechat"]`
字段，但 `wechat` 分支是占位（`sent = True # assume delivered`，未真正
实现）——且这是 vendor/ 的 pytest 快照副本，不代表生产。`TASKS.md` 里
"微信日报"是**人工复制转发**的 UX（一键复制按钮），不是 API 集成。
`tasks/partner_tasks.py` 目前唯一真实接的渠道是邮件。

**结论**：三个渠道目前都是从零开始建；如果 Partners 要做"主动推送"场景，
企业微信/飞书的群机器人 webhook 是成本最低的起步路径（几分钟配置、零
资质），但只能单向推送；微信公众号推送额度受限且需要真实企业认证；微信
个人号不建议碰。

---

## 汇总：对 W5 决策的影响

1. **`tasks/partner_tasks.py` 的两个属性错误应该先单独修**（不属于 W5
   本身，是当前就在每天崩的既有 bug，独立于要不要做 Partners 大功能）。
2. **sympify/eval/exec 的 5 个新发现是最高优先级**——都在未成年学生的
   真实输入路径上，且比这次盘点更早的"发现一个补一个"模式还严重（这次
   甚至发现了自检方法本身的检测盲区，不只是文件覆盖不全）。建议在动手做
   任何新 W5 功能前先处理这批。
3. Partners 架构如果要参考 DeepTutor：事件总线是纯 `asyncio.Queue`（无
   外部依赖，移植成本低），但 16 个渠道适配器里只有企业微信/飞书对国内
   场景直接有用，且都建议先做群机器人 webhook（免资质）而非完整应用。
4. 多用户/多租户是 Mneme 和 DeepTutor 都没解决好的领域（DeepTutor 的
   admin/user 也不是真正多租户）——如果 Partners 要支持"一个老师管一个
   班"，这是两边都要新设计的部分，不能照抄。
