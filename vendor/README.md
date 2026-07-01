# vendor/ — mneme 自带的 3O 内核副本

## 为什么有这个目录

`oprim / oskill / omodul / obase` 这些"内核"包物理上住在共享目录 `platform/3O/`，
被多个项目（mneme、tide…）共用。同一 git 仓同一时刻只能 checkout 一个分支，
别的项目切分支时，mneme 依赖的 edu-audit 内核改动就从工作树消失，导致
FSRS 个性化 / 试卷确定性批改 / 集中练习去抖 / 苏格拉底续接 等功能静默失效。

为让 **mneme 自包含、不受共享目录切分支影响**，把内核按 mneme 需要的版本
vendored 进来：
- `oprim / oskill / omodul` ← 各自 `feat/edu-audit-fixes` 分支（含 edu-audit 改动）
- `obase` ← `main`（mneme 未改动 obase）

## 怎么生效（vendor 优先）

- 测试：`pyproject.toml` 的 `[tool.pytest.ini_options] pythonpath = ["vendor", "."]`
  把 `vendor/` 放在最前。
- 运行时：`services/__init__.py`、`tasks/__init__.py` 顶部在任何内核 import 之前
  把 `vendor/` 插到 `sys.path` 最前（uvicorn→services、celery→tasks 都覆盖到）。

验证：`import oprim; oprim.__file__` 指向 `mneme/vendor/oprim/...`，
`services.kernel_selfcheck.check_kernel_contract()` 返回空。

## 如何刷新（内核有新改动时）

在对应内核仓提交到 `feat/edu-audit-fixes` 后，用 `git archive` 重新导出（不切工作树）：

```bash
cd ~/projects/mneme
for r in oprim oskill omodul; do
  rm -rf vendor/$r
  git -C ~/projects/platform/3O/$r archive feat/edu-audit-fixes $r | tar -x -C vendor/
done
rm -rf vendor/obase && git -C ~/projects/platform/3O/obase archive main obase | tar -x -C vendor/
find vendor -name __pycache__ -type d -exec rm -rf {} +
```

> 注：这是内核的**副本**。内核算法的权威源仍是 platform/3O 各仓；此处只为把
> mneme 需要的版本钉死、避免共享目录被切分支时 mneme 被动。
