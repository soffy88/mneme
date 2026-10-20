# NOTICE — cn-math-taxonomy

本目录中的 `topics.json`、`dependencies.json`、`questions.json`、`cn-curriculum-standards.json`、
`id-aliases.json` 与 `LICENSE` **原样**拷贝自上游仓库，未作任何修改（sha256 见 `UPSTREAM.json`）：

- 上游：中小学数学知识图谱（一—九年级） https://github.com/xiaoyang111222/cn-math-taxonomy
- 作者 / 权利人：xiaoyang111222（商用授权联系：X @hassanyehiaa 或上游 Issue）
- 版本：commit `3251221aa85c76f6837a3e37addea6e9ed85df98`（2026-10-19）
- 许可：知识共享 署名-非商业性使用 4.0 国际（CC BY-NC 4.0），全文见 `LICENSE`，
  https://creativecommons.org/licenses/by-nc/4.0/deed.zh-hans

Mneme 中的使用：`services/cn_math_importer.py` 导入为 knowledge_units（`cnmath:<topicId>`）；
`mneme_core.domain.oprim.prereq_graph` / `oprim.prereq_judge` / `oskill.prereq_diagnosis`
是上游 `diagnose/engine.js` 的 Python 移植（同一许可）。

**限制**：CC BY-NC 4.0 不允许商业使用（含付费课程、付费 App、机构收费服务）。善学记若有收费功能使用本数据/算法，
须先取得上游单独商用授权。

上一版快照（commit 0b22ee8，333 个知识点，含 18 个 cnm_ext_* 外部节点）已被本版替换。
