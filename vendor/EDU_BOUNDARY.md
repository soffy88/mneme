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
5. **第二轮裁剪（2026-08-16）**：删除 115 个未被引用文件——量化/支付/宏观
   工作流（alipay/stripe/okx/stat_arb/macro_*/risk_*/llm_agent(bear/bull)/
   ohlcv_store/price_store/crypto 交易族/backtest 族）及
   autoheal_cycle/backup_app_data/generative_video_pipeline。
   `scripts/vendor_edu_closure.py --check` 升级为**存在性守卫**：vendor/ 下
   文件本身命中金融键即 fail（防整仓 dump 回流），白名单仅含合法密码学/
   DB 事务设施（obase.crypto、oprim.crypto.hashing、
   omodul.refactor_transaction）。oprim/crypto/__init__.py 已收窄为
   hashing re-export；oprim/__init__.py 已移除 _quant_analysis 导入。
   刷新 vendor 后若 check 报金融文件，需按清单删除后再提交。

## 自检

```bash
pytest tests/test_vendor_edu_boundary.py tests/test_mastery_write_path_guards.py -q
python scripts/vendor_edu_closure.py --check
```
