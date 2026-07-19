# 事件记录：`async_session_factory` 导入错误（worker 崩溃循环）

**触发时间**：2026-07-18，W3 A1（Ollama qwen3-embedding 配置补齐）需要重启
`mneme-api-1`/`mneme-worker-1` 以生效新 env var + 迁移。
**性质**：**会话前既有债**（pre-session debt），非本轮引入——重启把它从潜伏状态引爆。

## 根因

`tasks/partner_tasks.py`（会话开始时已是未提交的新文件）和
`vendor/oskill/socratic_loop.py`（会话开始时已是未提交的修改文件）都写了：

```python
from obase.db import async_session_factory
async with async_session_factory() as db:
```

但 `vendor/obase/db.py` 实际导出的是 `SessionLocal`（`async_sessionmaker` 实例），
从未有过 `async_session_factory` 这个名字。

## 为什么直到现在才炸

`mneme-worker-1` 在本次重启前已连续运行 12 小时（`Up 12 hours`）——Celery worker
只在**进程启动时**一次性 import 所有 task 模块，之前那次启动大概率发生在
`partner_tasks.py` 被写入之前，或该模块从未被那次启动的 import 顺序触发校验。
本轮 A1 需要的容器重启，让 Celery 重新走 `import_default_modules()`，才第一次真正
执行到这行错误的 import，直接导致 `mneme-worker-1` crash-loop（`restart: always`
无限重试失败）——**全平台 Celery 任务处理中断**（不只是 A2 的索引任务）。

## 处置

最小一行/文件修复，只改导入名 + context manager 目标，不动其余逻辑：

- `tasks/partner_tasks.py`：`async_session_factory` → `SessionLocal`
- `vendor/oskill/socratic_loop.py`：同上

修复后 worker 正常拉起并保持运行（`celery@... ready`，持续存活验证过）。

## 未修复、明确留作后续债（不在本次修复范围内）

这两个文件本身是会话前的未审查 WIP，`ruff`/`mypy` 扫出的其余问题**原样保留**，
未来谁认领这两个文件时一并处理：

**`tasks/partner_tasks.py`**：
- `F401` `AsyncSession` 导入未使用
- `E402` `from tasks.celery_app import celery_app` 不在文件顶部
- `mypy`：`User` 无 `last_login`/`username` 属性（`services/models.py` 的 `User`
  模型可能缺这两个字段，或此文件假设了一个不同版本的 schema）
- `mypy`：`send_notification` 第一个参数期望 `str`，实际传入 `str | None`
  （`student.email` 未做 None 收窄，尽管上面的查询条件已过滤 `email.isnot(None)`）

**`vendor/oskill/socratic_loop.py`**：无额外 ruff/mypy 问题（仅那一处误命名导入）。

## 影响范围确认

- 只影响这两个从未被正确调用过的代码路径（`partner_push` Celery task、
  `socratic_loop` 的教材 RAG 检索分支）——两者在 worker 崩溃前也从未真正跑通过，
  没有"曾经工作、现在退化"的情况。
- 不影响 A1 本身的验收结论（embedding/char_span 验证走的是 `pytest`/`docker exec`，
  与 worker 进程无关）。
