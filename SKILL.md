# 用 mneme CLI 操作善学记（Mneme）

面向：驱动善学记后端完成学习流程的 AI agent（W5 Part C，Agent-native 面）。

## 红线（不可绕过）

- 本 CLI（`cli/mneme_cli.py`）是 `/v1/auth/*` + `/mcp/*` 的瘦客户端——每条命令
  都走真实 HTTP + JWT 鉴权 + 服务层既有 guard（`_ensure_student_self`/
  `_ensure_student_access`、`SubmitAnswer` 的 verdict_guard 等）。不直连数据库、
  不导入 oprim/oskill/omodul，结构上不可能绕过这些红线——跟人类用户用同一套
  护栏。
- **绝不代替学生编造答案、绝不把 `expected`/正确答案泄露给学生**——出题
  （`request-question`）只出不给答案；提交答案（`submit-answer`）判分结果里
  `is_correct`/`hint` 是允许的反馈，完整解答步骤按 Master 附录 L2 的分级红线
  处理，不由本 CLI 自行决定要不要给。
- 掌握度（P(L)）只能通过 `submit-answer`→服务层内核更新产生，任何 agent
  都不能自行判定/编造掌握度结果。

## 前置：登录

```bash
python -m cli.mneme_cli login --email you@example.com
# 提示输入验证码（开发环境 EMAIL_PROVIDER=mock 时验证码会打印在服务端日志）
```

token 落 `~/.config/mneme/token`，后续命令自动带上，不用每次都传。

## 命令一览

| 命令 | 作用 | 对应端点 |
|------|------|----------|
| `login --email <e>` | 邮箱验证码登录，保存 token | `POST /v1/auth/send-email-code` + `/v1/auth/login-email` |
| `whoami` | 查看当前登录身份 | `GET /v1/auth/me` |
| `review-queue --student-id <id> --kc <kc>...` | 查待复习队列 | `POST /mcp/GetReviewQueue` |
| `request-question --student-id <id> --kc <kc>` | 为某知识点出下一题（只出不答） | `POST /mcp/RequestQuestion` |
| `submit-answer --student-id <id> --question-id <q> --answer <a>` | 提交一次作答 | `POST /mcp/SubmitAnswer` |
| `bind-partner --student-id <id> --channel wecom\|feishu --target <webhook-url>` | 绑定 Partner 推送渠道（需先被 admin 授权，见下） | `POST /mcp/BindPartnerChannel` |
| `grant --student-id <id> --tools <t1,t2> --models <m1,m2>` | （仅 admin）设置某学生的工具/模型授权 | `POST /mcp/SetUserGrant` |
| `audit-log --student-id <id>` | 查看某学生的操作审计 | `POST /mcp/GetAuditLog` |

所有命令都支持 `--api-base <url>` 覆盖默认地址（默认读 `MNEME_API_BASE` 环境
变量，再默认 `http://localhost:8000`）。

## 典型工作流：帮学生完成一次复习

```bash
python -m cli.mneme_cli review-queue --student-id $SID --kc GDMATH-CONIC-01
python -m cli.mneme_cli request-question --student-id $SID --kc GDMATH-CONIC-01
# 拿到 question_id 后，把题目呈现给学生，收到学生的真实作答后再提交：
python -m cli.mneme_cli submit-answer --student-id $SID --question-id $QID --answer "$STUDENT_ANSWER"
```

## Partners（渠道推送）需要 admin 先授权

W5 v1 起，Partner 相关工具（如 `BindPartnerChannel`）默认对所有学生
deny-by-default——不是「登录了就能用」。管理员需要先跑一次：

```bash
python -m cli.mneme_cli grant --student-id $SID --tools BindPartnerChannel
```

学生才能绑定推送渠道；`admin` 身份由服务端 `ADMIN_USER_IDS` 环境变量白名单
判定，不是账号里的字段。

## 更深的架构

见仓库根 `AGENTS.md`（Agent-native 架构说明）与 `CLAUDE.md`（项目工作约定）。
