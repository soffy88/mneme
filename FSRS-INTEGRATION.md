# FSRS 复习调度集成文档（Word Atlas 优点吸收 · A 线）

借鉴口径与定义署名：Word Atlas contributors — CC BY 4.0

> 算法本身是公开的 FSRS 算法，署名针对借鉴的口径与定义（四档评分、
> 目标记忆率默认 90%、「稳定度 ≥ 21 天即掌握」、只有第一次作答更新记忆、
> 答错换题型重试不计分、先复习到期项再按 5 个一组学新项）。
> 本模块是照公开公式自己实现的干净实现，未复制 ts-fsrs 源码，
> 也不依赖 pip 的 `fsrs` 包。

## 1. 交付物

| 文件 | 说明 |
|---|---|
| `services/wordatlas_fsrs.py` | FSRS-6 调度模块（纯函数，标准库 only，无 DB 依赖） |
| `tests/test_wordatlas_fsrs.py` | 纯内存测试（不连任何数据库） |
| 本文件 | 算法口径、参数表、BKT 分工与接线说明 |

分支：`feat/word-atlas-graft`（从 main `ddbbe23` 新建的 worktree，
只提交上面三个点名路径；未动生产库、不部署、不 push）。

## 2. 卡片状态

一张卡 = `FSRSState`：

- `stability`（稳定度 S，单位天；新卡为 None）：记忆能维持多久。
- `difficulty`（难度 D，1~10；新卡为 None）：材料本身有多难。
- `due`（到期时间）：下次应复习的时间点；队列只按它排序。
- `last_review`（上次作答时间）+ `review_count`（已计分次数）。
- `retrievability`（可提取率 R）不是存量字段：由 S 与距上次作答的
  流逝天数实时算出（`current_retrievability`）。刚复习完时 R = 1，
  随时间按遗忘曲线衰减；下次间隔就是把它衰减到目标记忆率的时间。

## 3. FSRS-6 公式（本模块实现的全部公式）

参数来源：FSRS-6 官方默认参数（open-spaced-repetition FSRS-6
默认权重；py-fsrs 6.x / fsrs-rs 的 DEFAULT_PARAMETERS 与之一致，
衰减率 w[20] = 0.1542 是 FSRS-6 区别于 FSRS-5（0.5）的标志）。
下表即模块内 `DEFAULT_PARAMETERS` 的逐项含义。

| 索引 | 默认值 | 用途 |
|---|---|---|
| w[0] | 0.212 | Again 首评初始稳定度（天） |
| w[1] | 1.2931 | Hard 首评初始稳定度 |
| w[2] | 2.3065 | Good 首评初始稳定度 |
| w[3] | 8.2956 | Easy 首评初始稳定度 |
| w[4] | 6.4133 | 初始难度基线 |
| w[5] | 0.8334 | 初始难度评分因子 |
| w[6] | 3.0194 | 难度变化率 |
| w[7] | 0.001 | 难度均值回归强度 |
| w[8] | 1.8722 | 成功后稳定度增长（取 exp） |
| w[9] | 0.1666 | 成功后稳定度衰减指数 |
| w[10] | 0.796 | 成功后可提取率影响 |
| w[11] | 1.4835 | 遗忘后稳定度基数 |
| w[12] | 0.0614 | 遗忘后难度惩罚指数 |
| w[13] | 0.2629 | 遗忘后稳定度保留指数 |
| w[14] | 1.6483 | 遗忘后可提取率影响 |
| w[15] | 0.6014 | Hard 惩罚乘子（< 1） |
| w[16] | 1.8729 | Easy 奖励乘子（> 1） |
| w[17] | 0.5425 | 短期稳定度评分因子 |
| w[18] | 0.0912 | 短期稳定度评分偏移 |
| w[19] | 0.0658 | 短期稳定度指数 |
| w[20] | 0.1542 | 遗忘曲线衰减率 |

公式（G 为档位数值 Again=1 / Hard=2 / Good=3 / Easy=4）：

- 遗忘曲线：`R(t, S) = (1 + F * t / S) ** (-w[20])`，
  其中 `F = 0.9 ** (1 / -w[20]) - 1`。
- 间隔（反解遗忘曲线到目标记忆率 `R_d`，默认 0.90，可调）：
  `I = S / F * (R_d ** (-1 / w[20]) - 1)`；目标 90% 时 `I ≈ S`。
  上限 36500 天（FSRS 默认最大间隔），下限 1 分钟。
- 首评：`S0(G) = w[G-1]`（下限 0.1 天）；
  `D0(G) = clamp(w[4] - exp(w[5] * (G-1)) + 1, 1, 10)`。
  注意 FSRS-6 默认参数下 Easy 首评难度公式值为负，clamp 后为 1.0，
  这是公式与参数的直接结果，不是本模块的近似。
- 难度更新：`D' = D + (-w[6] * (G-3)) * (10 - D) / 9`（线性阻尼，
  难度越高变化越小）；`D'' = w[7] * D0(4) + (1 - w[7]) * D'`（向
  Easy 首评难度均值回归）；再 clamp 到 [1, 10]。
  效果：Again/Hard 升难度，Good 几乎不动，Easy 降难度。
- 成功回忆（Hard/Good/Easy，距上次 ≥ 1 天）：
  `S' = S * (1 + m * exp(w[8]) * (11 - D) * S ** (-w[9]) * (exp((1 - R) * w[10]) - 1))`，
  `m` 为 w[15]（Hard）/ w[16]（Easy）/ 1（Good）。R < 1 时增长为正，
  故成功回忆必不降低稳定度，且 Easy > Good > Hard。
- 遗忘（Again）：`S' = w[11] * D ** (-w[12]) * ((S + 1) ** w[13] - 1)
  * exp((1 - R) * w[14])`，再取 `min(S', S / exp(w[17] * w[18]))`。
  这个 FSRS-6 上限是关键：它保证 Again 必降低稳定度（至少约 4.8%），
  即使卡片已严重逾期（R 很低、原始公式可能反升）也不会反升。
- 同日复评（距上次 < 1 天，成功档）：短期分支
  `S' = S * exp(w[17] * (G - 3 + w[18])) * S ** (-w[19])`，
  且 Good/Easy 保底 `S' >= S`；Again 不走本分支，走遗忘分支。
- 本模块不实现 Anki 式学习步进（1 分钟 / 10 分钟）与间隔抖动
  （fuzzing）：due 直接是 `now + 间隔` 的时间戳；首评 Again 的
  间隔约 0.212 天（约 5 小时），这是 FSRS-6 在 90% 目标下的间隔，
  不是学习步进。如未来要学习步进，应另起一层，不改本模块公式。

## 4. 四档调度函数

`review(card, rating, now, *, parameters=..., desired_retention=0.90)`
返回新卡与说明（含分支 initial / recall / forget / short_term、
复习前可提取率、间隔天数、下次到期）。它是纯函数：不改入参，
不读库，不写库。`desired_retention` 可调（越高间隔越短、复习越密）。

## 5. 「稳定度 ≥ 21 天即掌握」

`is_mastered(card)`：`stability is not None and stability >= 21.0`。
这是 Word Atlas 口径的复测侧掌握定义，只用于 FSRS 侧判断
（例如到期队列里标注已掌握、或毕业展示），不替代仓内 BKT 的
掌握裁决（见第 8 节）：BKT 的 `MASTERED = 0.7` 与
`mastery_confirmed` 仍是 Mneme 掌握的唯一裁决源。

## 6. gap drill 作答 → 四档映射

### 6.1 字段 provenance（先查实，再映射，绝不编造）

实查结果：

- `gap_drill_service.answer_drill` 的会话 `results` 条目只有
  `question_id / ku_id / result` 三个键（`result` ∈ correct/wrong/skip），
  **没有耗时、没有提示字段**。所以耗时与提示不能从会话结果里取。
- 仓内实有的耗时/提示字段（调用方传入本映射时用这些，不新造名）：
  - `QuestionRecord.duration_ms`（作答耗时毫秒）与
    `QuestionRecord.hints_used`（> 0 即用过提示）；
  - `learning_engine.submit_answer` 的参数 `used_hint` 与 `latency_ms`；
  - MCP SubmitAnswer 的 `response_time_ms`；
  - 词汇线既有映射 `learning_scoring.derive_fsrs_rating`：
    INCORRECT/SKIPPED → AGAIN，PARTIAL/used_hint → HARD，
    `latency_ms <= fast_threshold_ms`（默认 3000）→ EASY，其余 GOOD。
- 本映射新增的策略参数（明确标注为新增，不是仓内既有常量）：
  `SLOW_THRESHOLD_MS = 30000`（30 秒）。仓内此前只有快线、没有慢线；
  gap drill 是单点微题，单题 ≥ 30 秒视为吃力，答对也只给 Hard。

### 6.2 映射表（`map_gap_drill_to_rating`）

| 作答 | 档位 | 依据 |
|---|---|---|
| wrong | Again | 任务口径；与词汇线 INCORRECT → AGAIN 一致 |
| correct + 用提示（used_hint 或 hints_used > 0） | Hard | 与词汇线 PARTIAL/used_hint → HARD 一致 |
| correct + latency ≥ 30000 ms | Hard | 本模块新增慢线（6.1） |
| correct + latency ≤ 3000 ms | Easy | 沿用词汇线 fast_threshold_ms 默认值 |
| correct + 其余（含耗时/提示均缺省） | Good | 中性默认：不凭空给 Easy，也不凭空降 Hard |
| skip / 自评（self_assessed=True） | 不计分（返回 None） | 见 6.3 |

耗时取首个非空值，优先级：`latency_ms` → `duration_ms` →
`response_time_ms`。`result` 缺失时可用 `is_correct` 兜底；
`verdict` 可作 `result` 的别名（反馈体里用 verdict 键）。

### 6.3 为什么 skip / 自评不计分（与词汇线 SKIPPED → AGAIN 的区别）

`gap_drill_service` 的红线是：自评/skip 不回写掌握度，由装配层按
`answered.self_assessed` 决定。FSRS 排期同理：一次未验证的回忆
（自评）或一次主动放弃（skip）不应被记成一次遗忘，否则会把
「没答」惩罚成「答错」，并在学生随后真实作答时重复计分。
词汇线的 SKIPPED → AGAIN 是另一条线（词汇会话内放弃即按遗忘计）
的既有约定，本映射不照搬；如未来某调用方确实要把 skip 当 Again，
应在调用前自行把 skip 翻译成 wrong，而不是改本映射。

## 7. 同一轮重答不重复计分（调用层）

Word Atlas 口径：只有第一次作答更新记忆；答错换题型重试不计分。

落地点是 `apply_review` / `apply_gap_drill_answer` 的 `review_id`
幂等：同一 `review_id` 第二次传入时返回原卡不动、
`applied=False`。gap drill 调用时 `review_id` 默认按
`gap:{session_id}:{卡 key 或答案 ku_id}` 生成——同一节 drill 里
同一 KU 只计第一次作答的分；答错后换题型重试即使这次答对了，
映射仍判 Easy，但不计分、不改卡；该卡按第一次的 Again 排期，
下一轮（新 review_id）再计分。

不计分（skip/自评）时不占 `review_id`：同一节里该 KU 随后
的真实作答仍可计分。`review_id` 为 None 时不做幂等（调用方自担）。

已计分 id 集合的持久化不在本模块：调用方应把它随
`fsrs_card_json` 一起存取（该字段已存在，无需迁移），
`apply_*` 返回更新后的集合就是为此准备的。

## 8. 复习队列

`build_review_queue(cards, now, *, group_size=5)`（Word Atlas
每日旅程口径：先复习、再 5 个一组学新词）：

1. 已到期项在前：`due <= now`，最久逾期的在最前（按 due 升序）。
2. 新学项在后：按传入顺序取 `group_size` 个一组（默认 5 个），
   剩余的进 `new_remaining`，供下一组取用（调用方传剩余列表
   再调一次即得下一组）。
3. 未到期项不进队列，单列 `upcoming`（按 due 升序）供展示。
4. 新学项判定：`review_count == 0` 或 `due` 为 None（且未到期）。

返回：`queue`（= due + new_batch）、`due`、`new_batch`、
`new_remaining`、`upcoming`、`due_count`、`new_batch_count`。

## 9. 与现有 BKT 的分工（不打架的接线）

| 维度 | BKT（既有，诊断用） | FSRS（本模块，排期用） |
|---|---|---|
| 回答的问题 | 这个 KU 掌握了吗？（掌握度推断） | 这个 KU 何时复测？（复测排期） |
| 唯一真相源 | `services/learner_model.py`：`p_mastery`、GATE=0.6、MASTERED=0.7；`mastery_confirmed` 只由 `mastery_gate_service` 的隔离裁决题写入 | 本模块的 S/D/due；`is_mastered`（S ≥ 21 天）只是 FSRS 侧标注 |
| 写什么 | BKT 写 `p_mastery` 等掌握字段 | FSRS 写 S/D/due（未来接线时写 `fsrs_card_json`） |
| 不写什么 | BKT 不写 due/稳定度 | FSRS 绝不写 `p_mastery` / `mastery_confirmed` |
| 触发 | 诊断、单点练后的门禁核对（`gap_drill_service.evaluate_return` 只读核对） | 到期复测、每日旅程组队 |

接线原则（本次只交付模块与映射，不改任何既有写路径）：

1. **读同一张卡，分开的字段**：`KCMastery.fsrs_card_json` 已是仓内
   既有字段（`practice_queue_service` 已按它的 `due` 读到期队列），
   未来接线时 FSRS 侧只读写该 JSON 内的 S/D/due/last_review/
   review_count 与已计分 id 集，不碰同一行的掌握字段。
2. **写路径仍走既有唯一入口**：gap drill 的判分与 BKT 回写仍走
   `SubmitAnswer` 唯一写路径（`gap_drill_service` 头注的红线），
   本模块不自判掌握度、不写 `kc_mastery`，只给调用方算好
   「这次作答后卡应是什么状态」，由调用方在既有写路径内落盘。
3. **口径不混用**：对外展示「已掌握」时以 BKT 裁决为准；
   FSRS 的 S ≥ 21 天只在复习调度语境里用（例如到期队列里
   标注该卡已进入长间隔），不得反向推高 `p_mastery`。
4. **权重优化不动**：`fsrs_optimize_service.py` 仍是权重选择路径
   （用真实复习日志在候选权重里择优）；本模块默认用 FSRS-6
   默认参数，优化出权重后调用方只需传 `parameters=...` 即可，
   不改公式。`InteractionEvent.fsrs_rating`（1~4）与本模块
   `Rating` 数值一致，优化日志可直接复用。
5. **本次未做的事（明确留给接线方）**：无路由、无 DB 写、
   无迁移、无前端改动；`practice_queue_service` 的到期读法不变，
   新队列函数是纯函数版，供未来调用方组装每日旅程时复用。

## 10. 测试（纯内存，零数据库）

`tests/test_wordatlas_fsrs.py`（25 个测试函数）覆盖：

- 参数表：21 维、FSRS-6 首评值与衰减率、目标记忆率 0.90。
- 单调性与边界：Again 降稳定度（含严重逾期仍降）、
  Easy > Good > Hard 的稳定度增长、新卡四档间隔递增、
  间隔随稳定度递增、随目标记忆率提高而缩短、
  可提取率随时间衰减且在间隔处回到约 0.90、
  难度随档位升降且 clamp 在 [1, 10]、同日复评 Good/Easy 不降稳定度。
- 掌握规则：S = 21 天为掌握、20.999 天不掌握、新卡不掌握。
- 映射：wrong → Again、plain correct → Good、提示 → Hard、
  快（≤ 3 秒，三个耗时别名）→ Easy、慢（≥ 30 秒）→ Hard、
  skip/自评 → 不计分、未知结果 → ValueError。
- 幂等：同一 review_id 只计一次（卡与 due 完全不动）、
  不同 review_id 可再计、gap drill 同一节同一 KU 第一次
  Again 后换题型重试答对也不计分、skip 不占轮次。
- 队列：到期在前且最久逾期在前、新学一批恰好 5 个、
  剩余 2 个进 new_remaining、未到期只进 upcoming、空队列与
  group_size 非法校验。
- 序列化：to_dict/from_dict 往返一致。

运行（测试文件自身零 DB import；worktree 内无 `.env` 时仓内
conftest 会因解析不到测试库 URL 而拒载，与本测试无关——
本测试是纯内存，故用 `--noconftest` 跑；单文件跑全仓覆盖率门
（60%）必然触发，故加 `--no-cov`；实测 25 passed）：

```
python3 -m pytest tests/test_wordatlas_fsrs.py -q --noconftest -p no:cacheprovider --no-cov
```

## 11. 局限与后续

- 无学习步进、无间隔抖动（见第 3 节末尾）；如产品要 Anki 式
  分钟级步进，需在调用层另加，不改公式。
- 无权重拟合：默认参数是群体默认；个体/群体优化走既有
  `fsrs_optimize_service`，拟合出权重后传参即可。
- 未接路由与落盘：接线方按第 9 节原则，在既有 SubmitAnswer
  写路径内调用 `apply_gap_drill_answer` 并把返回的卡与 id 集
  写回 `fsrs_card_json`，再用 `build_review_queue` 组装每日旅程。
