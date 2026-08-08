# vendor/ 教育边界

mneme 的 `vendor/{oprim,oskill,omodul,obase}` 来自共享 `platform/3O` 的
**钉死副本**。历史上整仓 dump 把量化/交易代码一并带入教育生产树。

## 规则（2026-08-07 起）

1. **运行时只允许教育闭包**：`services/` / `tasks/` / `cli/` / `packages/`
   不得 import 金融语义路径（见 `tests/test_vendor_edu_boundary.py`）。
2. **刷新 vendor 时**：只 archive mneme 实际用到的模块 + 其静态依赖，
   不要再整仓 `git archive` 整个 3O 仓。参考本目录 README 的刷新命令，
   并先 dry-run 与 `scripts/vendor_edu_closure.py` 对照。
3. **已裁剪**：crypto / ohlcv / derivatives / backtest / portfolio /
   exchange / market_making / regime / signals / strategies 等子树，
   以及一批明显非 edu 的 omodul 工作流文件。
4. **残留**：部分 root 拥有的 `__pycache__` 空壳目录可能删不掉（无 .py），
   不影响 import。其它非 edu 文件若未被服务引用，可在后续 PR 继续删。

## 自检

```bash
pytest tests/test_vendor_edu_boundary.py tests/test_mastery_write_path_guards.py -q
python scripts/vendor_edu_closure.py --check
```
