# W3 关闭记录（W3-CLOSE-001）

**日期**：2026-07-19
**状态**：W3 **收口**。Part A（Knowledge Hub）7/7 绿，Part B（Book Engine）
B5 验收 15/15 全过（含补测的 B-8）。
**收口性质**：Part A + Part B 均有可运行代码 + 真实数据验证 + 通过测试；
**但 W3 收口 ≠ ship-ready**——本记录的核心目的之一就是把 ship-gate 原文钉在
这里，不让"W3 完成"这四个字盖过它。见下方"⚠️ ship-gate（不因收口而移除）"。

---

## Part A：Knowledge Hub（自建教材索引 + 检索）

| 项 | commit | 一句话结果 |
|---|---|---|
| A1 | `2b40523` | 本地 Ollama qwen3-embedding 配置补齐；embed_chunks.py 补 char_start/char_end 出处字段；修了 embedding_model 记错、NUL 字节炸库两个真 bug |
| A2 | `2b40523`（同一 commit，数据本身不进代码库） | 22 本数学 PDF 全量入库，4897 chunks；修了一个 16% 命中率的 char_span off-by-one；人教版数学字体把拉丁变量映射成无关汉字，已知限制不修（见 A2-FONT-SUBSTITUTION-CAVEAT.md） |
| A3 | `9caf4ba` | KU↔chunk 推断挂接（ku_chunk_matches），2026 个 KU 实跑；20 抽验 13 exact+4 relevant+2 partial+1 miss（词汇碰撞：小数点移动 vs 几何缩放）——~85-87% 命中率 |
| A4 | `5c5e5d6` | `SearchTextbookKnowledge`（Mneme 自建，刻意不与 C4 的 `SearchKnowledgeBase` 同名——同名会被 oservi/FastAPI 静默遮蔽，实测确认非猜测） |
| A5 | 验收记录见 A1-A5 各 commit + `KNOWLEDGE-HUB-INVENTORY-001.md` | 7/7 项通过 |
| 过渡 | `949e82d` | 人工校订门（`ku_chunk_matches.verified`）+ `scripts/export_ku_chunk_review.py`/`apply_ku_chunk_review.py`；2026 条待审 CSV 已生成，**人工审这一步是用户自己的工作，还没做** |

---

## Part B：Book Engine（活书）

| 项 | commit | 一句话结果 |
|---|---|---|
| B1 | `65c0f16` | book_ideation/book_spine/book_page_plan（mneme-core 私有 oskill）；PORT-PLAN-001 实际不存在，改读 DeepTutor 上游真源码取结构参考；章节树扎根真实 knowledge_clusters，非 LLM 凭空发明 |
| B2 | `a465774` | 6 种块生成器注册表；quiz/flash_cards/guided 编译期只存 kc_ids（per-student 实时数据不能固化）；R1/R3/R4 落地进 knowledge_hub_search.py |
| B3 | `c60050f` | omodul.book_compile 四支柱（cost 是新增支柱，DeepTutor 没有）；async C1-C6 六条并发规矩，测试当场抓到两个真 bug（cost 从未被记账、trail 未按 step_no 排序） |
| B4 | `178a5b8` | `/studio/book` 阅读器；三态标注用人话文案，不套用 `@helios/blocks` 通用徽章；真实浏览器 e2e 确认渲染 |
| B5 | `32c745d` | 验收 15 项，13 项直接通过，B-8 当时如实记为范围内缩小 |
| B-8 补测 | `703e1c2` | 真实点击书页"去学习"链接 → 落地 → 真实作答 → `interaction_events` 落库，证明交接本身通；顺手修了一个真 bug（链接原来没带 kc_ids） |

---

## ⚠️ ship-gate（spec §6 原文，不因 W3 收口而移除）

> Part B 全绿 = 引擎结构完成，≠ ship-ready。ship 给真实学生前必须满足
> （W3 之外，独立工作）：
> 1. KU→chunk 挂接精度从 ~87% 提到可接受水平（全语料人工校订 / 或替换纯
>    embedding 挂接方法）
> 2. honesty 三态标注是缓解不是解决
> 3. 此 gate 记入 W3-PENDING-ITEMS，不得因 Part B 验收全绿而移除

**这条已经写进 `outputs/W3-PENDING-ITEMS.md`（标🔴），这里再钉一次**：
B5 的 15/15（含补测的 B-8）证明的是**引擎结构完整、机制真实生效**——
R1-R4 引用约束真的在成书里起作用、cost/decision_trail 真的记账、
Book→learn 交接真的通。这些都不改变一个事实：**活书里每处引用教材的地方，
背后是 ~13% 概率会指错的 KU→chunk 挂接**。honesty 三态标注只是让这个风险
对读者可见（"这段是推断的，没人核对过"），不是把错配率降下去。10 岁孩子
看到"推断未核对"这五个字，不会因此就能自己判断这段内容对不对——他们没有
判断依据，只有一个诚实的免责声明。

**"W3 完成"这个事实，和"KU→chunk 精度够格 ship 给真实学生"这件事，是两回事，
不要把前者当成后者的证明。**

---

## KU→chunk ~13% 错配天花板（结构性，非本次 bug）

- A3 首轮 20 抽验：13 exact + 4 relevant + 2 partial + 1 miss（决策术语
  "放大/缩小"词汇碰撞：小数点移动 vs 几何图形缩放）。
- 二次验证追加 25 抽验（Part B 上游对话记录）：确认坏匹配率约 13%，且
  misses 散布在 0.592–0.732 分数区间——**阈值不是正确性过滤器**，0.732
  这种"看起来分数不低"的匹配也可能是错的。
- 术语表方案（351 个高风险 KU）对真实失败模式 recall 只有 1/6（6:1）——
  大部分错配不是"含糊词汇"导致的，是"结构相似但具体内容不对"这种更难
  用规则捕捉的失败模式。
- **处置**：R1（阈值 0.60 自动排除）+ R3/R4（三态标注）已经是这条技术路线
  能做到的全部缓解——两者都不能把 13% 降到接近 0。真正的解法只有两条：
  全语料人工校订（`outputs/ku_chunk_review.csv` 已生成，2026 条待审，
  0 条审过）、或换一个比纯 embedding cosine 更准的挂接方法。

---

## 全部挂起项（汇总索引，各自详情见 outputs/W3-PENDING-ITEMS.md）

- 🔴 **ship-gate**：KU→chunk ~13% 错配，ship 前必须先校订/换方法（见上）。
- 🔴 **image rebuild 债**：`pymupdf4llm`/`pypdf` 只 `pip install` 进了运行中的
  `mneme-api-1`/`mneme-worker-1` 容器（ephemeral），`requirements.txt` 里
  有了但镜像从未 rebuild——images 创建于 2026-07-05，`requirements.txt`
  最后改动在 2026-07-19，镜像早于改动。下次任何原因需要 `docker compose
  build`/容器 recreate（不是单纯 restart）时，PDF 解析能力会静默消失。
  下次动这两个容器时必须顺带 `docker compose build api worker` 一次性还债。
- **A2 已知限制**：人教版数学教材字体把拉丁变量映射成形状相似的无关汉字
  （x→狓/a→犪/m→犿），文本层面无法通过换库解决，接受不修（见
  `A2-FONT-SUBSTITUTION-CAVEAT.md`）。
- **A3 词汇碰撞失败模式**：多义数学术语导致 embedding 检索误召回，Knowledge
  Hub 已知精度边界的一部分，与上面 ship-gate 是同一件事的不同角度。
- **新发现，不修**：`_llm_generate_question`（既有 W2C 兜底出题逻辑，非
  Book Engine 引入）不传年级上下文——G1 KC 生成了研究生集合论级别的题目。
  B-8 补测过程中撞见，超出本次范围，留后续（`services/mcp_router.py`）。
- **人工校订本身未开始**：`outputs/ku_chunk_review.csv`（2026 条）已生成，
  排序（`exam_frequency=high` 优先 + 匹配分数升序）已就绪，`scripts/
  apply_ku_chunk_review.py` 已测试可用——但审查这个动作本身是用户的工作，
  CC 没有做、也不该代做。
- **交接自本次会话更早阶段、W3 之外**：3× daily_plan 失败｜oservi assemble
  双注册 bug｜blocks OMarkdownRenderer bug（AA.3 已绕过用 katex 直渲染，
  上游包本身的 bug 未修）｜S3-C 真人 pilot（W8–W12 红，唯一真瓶颈）｜
  Stratum 内容库为空（C4 通路验证过、语料库本身没填，若要用需独立填库）。

---

## 回归状态（收口时，2026-07-19）

根仓 `pytest`：700 过 / 4 败（既有失败，`test_daily_plan.py` ×3 +
`test_dod_e2e.py` ×1，与本次改动无关，已多次交叉验证与改动前一致）/ 3 跳。
`packages/mneme-agent`：14 过 / 0 败。`packages/mneme-core`：114 过 / 0 败。
共计 828 个测试，本次 W3 全程新增约 125 个，同一基线的 4 个既有失败贯穿
始终未变。ruff/mypy 在所有本次触及的第一方文件上干净（`vendor/` 按既有
约定不纳入检查范围）。

前端（`apps/mneme-studio`）：TypeScript 严格模式编译通过，`next build`
成功，3 组 Playwright e2e（书单/阅读器渲染/Book→learn 交接）全部真实浏览器
验证通过（含一次专门验证 B-6 verified 态渲染、验完已还原测试数据）。生产
`mneme-studio` 容器已 rebuild + 重启两次（部署 B4 页面本身 + 部署 B-8 的
kc_ids 链接修复），均经用户确认。
