# W3 挂起项（Part A 进行中，随时更新）

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
