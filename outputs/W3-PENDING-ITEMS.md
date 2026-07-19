# W3 挂起项（Part A + Part B 均已交付，随时更新）

## 🔴 ship-gate（spec §6 写死，Part B B5 全绿≠ship-ready，不得因为这条移除）

Part B（Book Engine：B1 ideation/spine/page_plan → B2 block 生成器 → B3
book_compile 四支柱 → B4 /studio/book 阅读器）已全部实现，B5 验收
（B-1 到 B-15）已逐条核对，13 条完全通过、1 条（B-8）范围内如实缩小、
细节见下方"B5 验收记录"。**但 Part B 全绿 = 引擎结构完成，不等于 ship-ready**：

活书引用教材靠 KU→chunk 挂接，~87% 命中率（A3 抽验：13 exact+4 relevant，
2 partial+1 miss；见 A3 词汇碰撞条目），即约 13% 的引用存在错配风险，
honesty 三态标注（R3/R4）只是让这个风险对读者可见，不是消除它。ship 给
真实学生前必须先做到：KU→chunk 挂接精度从 ~87% 提到可接受水平（全语料
人工校订，见 scripts/export_ku_chunk_review.py 已生成待审清单 / 或替换
纯 embedding 挂接方法）。此条不因 B5 验收通过而勾掉。

## B5 验收记录（2026-07-19）

| # | 项 | 结论 |
|---|---|---|
| B-1 | 端到端编译 | ✅ 真实编译 3 本书（G8×2/G1×1），真 qwen，0 block 错误 |
| B-2 | 内容溯源 Knowledge Hub，非纯 LLM 编造/非 Stratum | ✅ 所有引用可追溯真实 chunk_id/pdf_id；代码零处引用 rag_client |
| B-3 | 出处可点开 pdf/page/span | ✅ 真实浏览器 e2e 确认 |
| B-4 | R1 分数<0.60 不出现 | ✅ 多层测试 + 真实书最低分 0.6065/0.6924/0.6969 |
| B-5 | R3 默认"推断未核对" | ✅ |
| B-6 | R4 人工校订后显示"已核对" | ✅ 真实浏览器 e2e（手动模拟一条 verified 挂接，验完已还原） |
| B-7 | 三态 UI 阅读器可见 | ✅ |
| B-8 | quiz 块经既有判分护栏，掌握度回流 | ⚠️ **范围内缩小，如实记录**：quiz/flash_cards/guided 块编译期只存 kc_ids scope（B2 架构决定——这三种是 per-student 实时数据，不能编译期固化），阅读器只给"去学习"入口链接，不在 Book Engine 里重新实现选题/判分。既有 `/studio/learn` 判分链路本身零改动、仍受 S1 CI 门约束，但**没有一条 Book-Engine-专属的端到端测试**证明"从书里点进去、答题、掌握度回流"——因为这条路径就是既有 `/studio/learn`，Book Engine 没有新建判分入口，也没有验证过"点击衔接"这一步本身 |
| B-9 | 四支柱齐，cost 非零 | ✅ 真实开销 $0.57～$0.83/本 |
| B-10 | async 并发 cost/trail 正确 | ✅ 专门测试覆盖，且过程中真的抓到两个实现 bug（cost 从未被记账、trail 未按 step_no 排序） |
| B-11 | decision_trail 记录每处引用分数+三态 | ✅ |
| B-12 | FC-5 零 DB | ✅ package.json 无 DB 驱动依赖 + 容器无 DB 环境变量 + pg_stat_activity 确认零连接 |
| B-13 | FC-6 归属书面记录 | ✅ 每个新元素 docstring 里都有 |
| B-14 | 测试计数审计 | ✅ 828（700+14+114），4 个既有失败贯穿全程未变 |
| B-15 | 门控不受 Book/检索影响 | ✅ 每个新模块都有 is_mastered 前后夹检索的直接证明 |

## 🔴 image rebuild 债 —— PDF 解析能力只在运行容器里，镜像没有

**状态**：未修复，标红，下次动 `mneme-api-1`/`mneme-worker-1` 容器时必须一并处理。

`vendor/oprim/embed_chunks.py` 的 `extract_pages_from_pdf()` 依赖 `pymupdf4llm`
（内部用 `fitz`）+ `pypdf`（fallback）。这两个包：

- **已写入** `requirements.txt`（`pymupdf4llm`、`pypdf>=4.0`）。
- **没有**烤进 `mneme-api`/`mneme-worker` 镜像——A2 批量入库时是用
  `docker exec mneme-api-1 pip install pymupdf4llm pypdf` **临时装进正在跑的容器**
  （避免为装两个包就重启一次生产容器）。

**后果**：下次 `mneme-api-1`/`mneme-worker-1` 被 recreate（`docker compose up -d`
决定重建、或镜像重新 build、或机器重启）——**PDF 解析能力会静默消失**，
`extract_pages_from_pdf` 回退到"两个 import 都失败→返回 `[]`"，
`index_textbook_file` 会报"No text could be extracted from file"。不会崩容器，
只会让任何新教材文件的索引任务默默失败——比 crash-loop 更隐蔽。

**这轮已经吃过一次这类坑**：见 [[A1-ASYNC-SESSION-FACTORY-INCIDENT]]
（`async_session_factory` 导入错误潜伏了 12 小时，直到一次不相关的重启才炸出来）。
同一类"重启才发现"的债，这是第二次——都是因为 requirements.txt / 代码改了，
但镜像/运行容器状态没跟着更新。

**处置**：不现在无谓重启。下次因为任何原因需要重建/重启
`mneme-api-1`/`mneme-worker-1` 时，顺带 `docker compose build api worker`
（会读到 requirements.txt 里已经加的两个包），一次性把这债还掉，不要再单独
为这件事再开一次生产重启窗口。

## A2 已知限制：数学教材字体替换（不是本轮新问题，备查）

已有完整记录：[[A2-FONT-SUBSTITUTION-CAVEAT]]。摘要：人教版数学教材 PDF
的排版字体把拉丁数学变量（x/a/m…）映射成形状相似的无关汉字（狓/犪/犿…），
文本抽取层面无法通过换库解决（OCR 或该出版社专属字形映射表才能真正修）。
2026-07-18 用户已拍板接受为已知限制，按计划批量入库，不额外投入修复。
本条目仅作交叉索引，避免这两个"文本层不完美"的坑（字体替换 vs. NUL 字节）
被混为一谈——NUL 字节那个已经在 A2 修了（`_strip_control_chars`），
字体替换这个是接受不修的。

## A3 已知精度边界：词汇碰撞失败模式（多义数学术语 embedding 混淆）

**状态**：不修，记为 Knowledge Hub 结构性精度天花板（不是 bug，是纯 embedding
语义检索这条技术路线本身的局限）。

**现象**（A3 抽验 20 个 KU 命中率时发现，1/20）：KU「小数的扩大与缩小」
（小数点移动）被匹配到一个讲「相似图形放大缩小」（几何缩放）的 chunk。两者
共享"放大/缩小/倍"这类表面词汇，但概念完全不同——embedding 捕捉的是词汇/
语境层面的相似度，不是数学概念的严格语义区分。

**影响面**：任何在中文数学教材里"一词多义/多概念共享词汇"的 KU 都有同样
风险——不止这一个例子，凡是这类命名冲突的 KC 都可能被误挂接。~85% 的整体
命中率（A3 抽验：13 exact + 4 relevant + 2 partial + 1 miss，见对话记录）对
"W3 把管道跑通"这个目标够用，但对**可售教育产品**不够——1/20 会把小数点
概念讲成几何缩放，真学生会被这个误导，不是无伤大雅的噪音。

**处置原则**：现在不修（概率匹配的本质决定了，靠调 embedding 参数/加更多
候选也解决不了"两个概念共享词汇"这个根本问题）。**Book Engine 引用高频/
核心 KU 的教材原文前，需要人工校订这些挂接，或者加一层规则/关键词消歧**
（如"小数点""放大缩小"这类已知易混淆词对建一个显式排除表）——不能让
Book Engine 端到端只靠 embedding 相似度分数就直接采信、呈现给学生。
`SearchTextbookKnowledge` 已经把 `score` 暴露给调用方（W3 A4 设计），但
"分数够高就采信"本身不是解药——0.784 的分数在 A3 抽验里既出现在完全正确的
匹配（不等式性质1），也可能出现在词汇碰撞的误匹配上，分数本身分不出这两种
情况。

**2026-07-19 更新——人工校订机制已建，校订本身待办**：进 Part B 前拍板：
Book Engine 引用只认人工确认过的挂接。已落地：

- `ku_chunk_matches` 加 `verified`/`verified_at`/`verified_note`
  （迁移 `c4d5e6f7a8ba`），默认全 `false`（未审）。
- `scripts/export_ku_chunk_review.py` → `outputs/ku_chunk_review.csv`
  （2026 行，已生成）：`exam_frequency='high'` 优先（语料库里只有 4 个，
  真实使用数据不存在，唯一有意义的先验）+ 其余按 rank1 匹配分数**升序**
  （分数越低越可能错，优先审最可能错的，不是最多的那桶）。
- `scripts/apply_ku_chunk_review.py`：读回填好 `correct_rank`
  （1/2/3=对应候选正确，0=三个都不对，空=未审）的 CSV，写回
  `verified`；幂等，可重复 apply 同一份文件。
- **人工审这一步本身还没做**——`outputs/ku_chunk_review.csv` 已生成待审，
  这是用户自己的工作，不是 CC 的。Book Engine（Part B）设计引用逻辑时
  必须只读 `verified=true` 的挂接，`verified=false`（含"未审"和"审过但
  三个都不对"两种情况）一律不引用。
