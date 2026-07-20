# AGENTS.md — 善学记（Mneme）Agent-native 架构说明

面向：需要理解/操作本仓库的 AI agent（W5 Part C）。本文件只做定位，深入规则
见 `CLAUDE.md`（项目工作约定，含红线）与 `MNEME_MASTER_DESIGN.md`（唯一权威
设计）——两者与本文件冲突时以那两份为准。

## 这是什么

Mneme（对外名"善学记"）：面向 K-12 学生的学习成长档案 + 自主学习工具，核心是
KT(BKT)+FSRS 算法内核，先做广东数学。真实前端在独立仓库
`mneme-web`；本仓库是后端 + 已废弃的旧前端。

## 两层入口（Tools vs Capabilities）

- **HTTP/MCP 面**（`services/mcp_router.py`，前缀 `/mcp/*`）——真正的能力
  边界。每个工具是"纯逻辑函数 `tool_X` + 路由 `POST /mcp/X`"两件套，路由层
  做鉴权（`_ensure_student_self`/`_ensure_student_access`，或 admin 判定）。
  这是唯一应该被调用的入口——不管你是人类前端、`packages/mneme-agent` 的
  `AgenticLoop`，还是本仓库 `cli/mneme_cli.py`，都通过这一层。
- **CLI**（`cli/mneme_cli.py`）——`/v1/auth/*` + `/mcp/*` 的瘦客户端，命令
  文档见 `SKILL.md`。不直连数据库，不导入 oprim/oskill/omodul。

## 红线（结构性，不是口头约定）

- **确定性优先**：有 `solve_*` 内核覆盖的题型，数值结论必来自内核，LLM 不得
  改写。
- **答案分级**：学生自带题/作文永不给可抄答案；系统教学同构新知可给完整
  样例——判定逻辑在服务层，agent 不能自行决定绕过。
- **掌握度唯一路径**：P(L) 只能经 `SubmitAnswer`→内核更新产生，任何 agent/
  Partner/CLI 都不能自行判定或编造掌握度（W5 red line，见
  `tests/test_partner_no_self_judged_mastery.py` 的结构性 AST 断言）。
- **多用户授权**（W5 Part B）：`ADMIN_USER_IDS` 环境变量判定 admin 身份，
  非 admin 学生的工具/模型访问 deny-by-default，需 admin 显式
  `SetUserGrant`——不是"登录了就能用一切工具"。
- **数据最小化 + 合规**：涉未成年人数据的新表必须同 PR 入
  `services/purge_service._STUDENT_TABLES`；对外渠道（Partners/WeCom/Feishu）
  只推必要文案，不外发 PII。

## 3O 分层（代码组织约定）

`oprim`（单次原子操作）→ `oskill`（≥2 oprim 组合算法）→ `omodul`（业务事务）
→ 服务层（`services/`，鉴权/路由/编排）。依赖单向：omodul→oskill→oprim；
`obase`（基础设施）与三层平行，不被三层反向依赖。详细约束见 `CLAUDE.md`
「3O 范式约定」一节。

## 关键文件地图

| 关心什么 | 看这里 |
|---------|--------|
| API/MCP 工具全集 | `services/mcp_router.py` |
| 鉴权/IDOR 防护惯例 | `services/auth_deps.py` |
| 沙箱化 sympy 求值 | `vendor/obase/sympy_runtime.py`（S0/S0-W5，见其自身 docstring） |
| Partners（渠道/心跳/隔离） | `services/partner_channels.py`、`tasks/partner_heartbeat.py`、`vendor/oskill/partner_dispatch.py` |
| 多用户（授权/审计） | `vendor/obase/user_grants.py`、`vendor/obase/audit_log.py`、`vendor/obase/admin_identity.py` |
| CLI | `cli/mneme_cli.py`，命令文档见 `SKILL.md` |
| Agent 组装参考（mneme-agent 包） | `packages/mneme-agent/mneme_agent/assembly/tutor_loop.py` |
| 数据合规/硬删除 | `services/purge_service.py` |
| 项目工作约定/红线全集 | `CLAUDE.md` |
| 唯一权威设计 | `MNEME_MASTER_DESIGN.md` |

## 依赖/环境说明

- `oservi`（服务装配引擎）目前只是本机 dev 挂载
  （`docker-compose.override.yml`），非正式生产依赖——W5 心跳/Partner 相关
  代码不依赖它，走 Celery beat + 直接实现（见
  `tasks/partner_heartbeat.py` 顶部说明）。
- 生产容器启动经 `obase.sandbox_selfcheck.check_or_die()` 强制自检（S0-W5：
  全仓 AST 扫描零绕过），自检不过拒绝对外提供服务。
