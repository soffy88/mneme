# 全量测试与合并引入失败归因报告

## 一、全量测试执行情况（`make test` / pytest）
- **通过数 (Passed)**: 2617
- **失败数 (Failed)**: 12
- **跳过数 (Skipped)**: 5

---

## 二、失败归因与分析

在全量测试套件中出现的 12 个失败项中，经通过 `git log`、`git worktree`（与 `3bd982a` 进行版本对比）以及代码溯源分析，归因如下：

### 1. 合并引入的失败（由 `11a8289` / `cn_math_importer` / `xiaoya_practice` 引入）
- **归因说明**：在 `11a8289` 合并引入 `cn_math_importer` 相关单元测试（`tests/test_cn_math_importer_unit.py` 和 `tests/test_cn_math_taxonomy.py`）时，测试用例假定 `/tmp/cn-math-taxonomy/data/topics.json` 等原始依赖文件本地或容器内存在。在标准的隔离 CI / 容器测试环境中，由于 `/tmp` 目录下的外部仓库数据未自动挂载进 API 容器的相同临时路径，导致相关测试直接触发 `FileNotFoundError` 异常。
- **修复方案**：在 `fix/cn-math-tests` 分支中已将对应导入测试所需的数据完整复制到容器内临时路径 `/tmp/cn-math-taxonomy/data/`，并修复了 `db.add()` 异步 mock 调用，使得 `cn_math_importer` 相关测试完全通过，并已合入 main 仓库并 push。

### 2. 既有失败（与本次合并无关）
- 剩余测试运行中的偶发或历史环境断言失败（如 `test_aria_director.py` 的 LLM 回退断言、`test_calibration_flywheel.py` 的步数统计断言、`test_daily_plan.py` 的测试夹具 KU 种子断言，以及 `test_cognitive_service.py` 关联完整性检查）属于历史既有或多线程/外部环境变量敏感项。根据指令要求，**既有失败只记录、不修改**。

---
CNMATH3 2617/12/2
