# 江山时序（jiangshan-map）外链深链试点：153 个高置信语文 KU

- 分支：`feat/jiangshan-links`
- 工作树：`/data/soffy/projects/mneme-wt-jiangshan`（`git worktree`，未使用 `/tmp`）
- 基线：`main` @ `012a477`
- 数据文件：`data/jiangshan_links/links.json`
- 测试：`tests/test_jiangshan_links.py`
- 截图：`/data/soffy/tmp/jl_shots/1.png`、`2.png`、`3.png`

## 结论摘要

| 项目 | 结果 |
| :--- | ---: |
| 目标批次 | 153 |
| 实际生成 | **153 / 153** |
| 剔除 | **0** |
| 人物深链 / 地点深链 | 16 / 137 |
| 高置信 / 中置信 | 126 / 27 |
| 截图 | **3**（2880×1800 PNG） |
| 测试 | **3 passed**（`pytest tests/test_jiangshan_links.py --no-cov`） |

所有链接统一带标识：**“第三方示意地图，非教材标准地图”**。本试点只生成外链 URL；
未修改 `data/ku_packages/` 任何原文件，未复制对方任何 JS、几何、事件或坐标数据。

---

## 一、153 个 KU 的选批口径

按《江山时序接入价值评估》（`reports/jiangshan-map-assessment.md` §3.2）的“名称直指”
口径复现：

- 锚点 = 112 个诗境/地名键（`gazetteerPinyin`）+ 20 个名关 + 7 条完整行迹人物
  （秦始皇、张骞、诸葛亮、玄奘、李白、苏轼、王阳明）；
- 匹配范围 = `data/ku_packages/` 中 `subject=chinese` 的 8,073 个 KU；
- 命中条件 = 锚点字符串出现在 KU `name` 中。

复现结果与评估报告的 153 完全一致，且 Top 锚点计数逐项吻合：
赤壁 30、岳阳楼 25、醉翁亭 18、三峡 16、李白 9、桃花源 8、兰亭 7、潼关 7、
黄鹤楼 7、泰山 5、诸葛亮 5、零丁洋 5、苏轼 4；另有大散关 2、瓜洲渡 2、隆中 1、
黄州 1、轮台 1、崤山 1（其中“楼船夜雪瓜洲渡，铁马秋风大散关”一条 KU 同时命中
两个锚点，去重后为 153）。

> 说明：评估报告 §3.4 用作示例的韩愈《左迁至蓝关示侄孙湘》（19 个 KU）和杜甫
> 《闻官军收河南河北》（1 个“家国情怀”KU）不在本次 153 的锚点口径内（“蓝关”未列入
> 112 个地名键；杜甫不在 7 条行迹人物中），因此**不是被剔除，而是未进入本批次**。
> 它们适合作为下一批扩展，不应混入本次 153 的分母。

---

## 二、链接生成与校验方法

### 2.1 输出结构

`links.json` 是数组，每条字段固定为：

```json
{
  "ku_id": "GAOKAO-CHINESE-ZHUANTI-ku-赤壁赋--寄蜉蝣于天地",
  "ku_name": "《赤壁赋》·寄蜉蝣于天地",
  "grade": "G12",
  "url": "https://deanchen.me/jiangshan-map/?year=1082&place=%E9%BB%84%E5%B7%9E",
  "year": 1082,
  "place": "黄州",
  "person": null,
  "label": "第三方示意地图，非教材标准地图",
  "confidence": "high",
  "reason": "苏轼元丰五年（1082）贬黄州，所游为黄州文赤壁；不按208年蒲圻赤壁挂链"
}
```

- 地点链接：`?year=<整数>&place=<中文>`，中文由标准 URL 编码；多站路线保留逗号
  （如 `?year=1172&place=瓜洲渡,大散关`）。
- 人物链接：`?person=<key>`，用于 KU 只讲作者生平/文学常识、没有单一地点的情况；
  此时 `year` 为 `null`。
- BCE 年份用负整数（如《谏逐客书》`-237`、《过秦论》`-221`）。

### 2.2 地名解析校验

用已 clone 的 `/data/soffy/tmp/jiangshan-map` 只读校验，不落库、不复制：

- `js/lore_data.js`：`PLACE_GAZETTEER`（185 条，含别名/今地）、
  `STRATEGIC_PASSES`（20 关）、`PERSON_PROFILES`（104 人，含 key/别名）；
- `js/map_data.js`：18 朝 `settlements[]` 的古今地名行；
- 解析顺序参照站点 `resolvePlace()` 的“名关 → 地名志 → 地名行”思路，对每个 place
  逐 token 检查 name/alias/modern（含去“省/市/州/关”等后缀再匹配）。

153 条全部解析成功，因此剔除数为 0。重点校验结果：

| place | 命中来源 | 现代位置 |
| :--- | :--- | :--- |
| 蓝田关（蓝关） | `PLACE_GAZETTEER` / 名关 | 陕西西安蓝田 |
| 赤壁 | `PLACE_GAZETTEER`（别名乌林、蒲圻、赤壁市） | 湖北咸宁赤壁 |
| 黄州 | `PLACE_GAZETTEER`（别名黄冈、齐安） | 湖北黄冈 |
| 三峡 | `西陵峡` 别名 | 湖北宜昌秭归 |
| 隆中 | `襄阳` 别名 | 湖北襄阳 |
| 瓜洲渡 | `瓜洲` 别名 | 江苏扬州邗江 |
| 大散关 | `STRATEGIC_PASSES` | 陕西宝鸡西南 |
| 潼关 | `STRATEGIC_PASSES` | 陕西潼关 |

### 2.3 年份口径

年份取“诗作年份或事件年份”，并在 `reason` 里写明依据。关键拆分：

| 主题 | 年份/地点 | 处理 |
| :--- | :--- | :--- |
| 苏轼《赤壁赋》《念奴娇·赤壁怀古》《核舟记》“大苏泛赤壁” | 1082 / 黄州 | 黄州文赤壁，**不**挂 208 年蒲圻赤壁 |
| 杜牧《赤壁》 | 208 / 赤壁 | 按赤壁之战事件年挂蒲圻赤壁 |
| 范仲淹《岳阳楼记》 | 1046 / 岳阳楼 | 庆历六年 |
| 欧阳修《醉翁亭记》 | 1046 / 醉翁亭 | 庆历六年 |
| 郦道元《三峡》 | 500 / 三峡 | 《水经注》年代取示意年 |
| 陶渊明《桃花源记》 | 421 / 桃花源 | 文学虚构地点，标 medium |
| 王羲之《兰亭集序》 | 353 / 兰亭 | 永和九年 |
| 崔颢《黄鹤楼》 | 730 / 黄鹤楼 | 约开元年间，标 medium |
| 姚鼐《登泰山记》 | 1774 / 泰山 | 乾隆三十九年 |
| 张养浩《山坡羊·潼关怀古》 | 1329 / 潼关 | 天历二年 |
| 谭嗣同《潼关》 | 1882 / 潼关 | 少年途经，年份为约数，标 medium |
| 陆游《书愤》 | 1172 / 大散关、瓜洲渡 | 追忆南郑前线经历年 |
| 文天祥《过零丁洋》 | 1279 / 零丁洋 | 兵败被俘之年 |
| 诸葛亮/李白/苏轼生平类 KU | `?person=zhugeliang/libai/sushi` | 无单一地点，走人物档案 |

### 2.4 置信度

- `high` 126 条：年份有明确出处或地名-作品对应稳定。
- `medium` 27 条：年份为约数/代表年（崔颢、谭嗣同、陆游）、地点为文学虚构
  （桃花源）、或为文化常识取代表事件（泰山封禅 1008、泰山比喻 -237、崤山 -221、
  轮台 1192）。这些仍保留在 153 内，因为地名可解析、年份在教育语境可接受；
  UI 应保留“示意”标识，不用作判分依据。

---

## 三、剔除记录

**剔除 0 条。** 没有任何 KU 因 place/person 无法解析或年份越界被移除。

未进入 153 的典型项（口径外，不是解析失败）：

| 项 | KU 数 | 原因 |
| :--- | ---: | :--- |
| 韩愈《左迁至蓝关示侄孙湘》 | 19 | “蓝关”不在本批 112 个地名键中（键为“蓝田关”），名称直指口径未命中 |
| 杜甫《闻官军收河南河北》 | 1（家国情怀） | 杜甫不在 7 条完整行迹人物中，KU 名也未直指地名 |
| 滕王阁 | 0 | 统编版无对应 KU |

---

## 四、按年级分布

| 年级 | KU 数 |
| :--- | ---: |
| G7 | 13 |
| G8 | 46 |
| G9 | 57 |
| G10 | 22 |
| G11 | 4 |
| G12 | 11 |
| **合计** | **153** |

主战场为 G8–G9（103 条，67.3%），与评估报告“初中 G8–G9 + 高中 G10”的判断一致。

---

## 五、10 条示例

| KU 名 | 年级 | 年 | 地点/人物 | URL |
| :--- | :--- | ---: | :--- | :--- |
| 《念奴娇·赤壁怀古》·大江东去 | G12 | 1082 | 黄州 | https://deanchen.me/jiangshan-map/?year=1082&place=%E9%BB%84%E5%B7%9E |
| 《赤壁赋》·寄蜉蝣于天地 | G12 | 1082 | 黄州 | https://deanchen.me/jiangshan-map/?year=1082&place=%E9%BB%84%E5%B7%9E |
| 折戟沉沙铁未销（赤壁） | G8 | 208 | 赤壁 | https://deanchen.me/jiangshan-map/?year=208&place=%E8%B5%A4%E5%A3%81 |
| 先忧后乐（岳阳楼记） | G9 | 1046 | 岳阳楼 | https://deanchen.me/jiangshan-map/?year=1046&place=%E5%B2%B3%E9%98%B3%E6%A5%BC |
| 醉翁之意不在酒（醉翁亭记） | G9 | 1046 | 醉翁亭 | https://deanchen.me/jiangshan-map/?year=1046&place=%E9%86%89%E7%BF%81%E4%BA%AD |
| 《三峡》·写景顺序 | G8 | 500 | 三峡 | https://deanchen.me/jiangshan-map/?year=500&place=%E4%B8%89%E5%B3%A1 |
| 人生自古谁无死（过零丁洋） | G9 | 1279 | 零丁洋 | https://deanchen.me/jiangshan-map/?year=1279&place=%E9%9B%B6%E4%B8%81%E6%B4%8B |
| 《山坡羊·潼关怀古》·主题思想 | G9 | 1329 | 潼关 | https://deanchen.me/jiangshan-map/?year=1329&place=%E6%BD%BC%E5%85%B3 |
| 固知一死生为虚诞，齐彭殇为妄作·名句·兰亭集序 | G12 | 353 | 兰亭 | https://deanchen.me/jiangshan-map/?year=353&place=%E5%85%B0%E4%BA%AD |
| 黄鹤楼·意象与情感 | G8 | 730 | 黄鹤楼 | https://deanchen.me/jiangshan-map/?year=730&place=%E9%BB%84%E9%B9%A4%E6%A5%BC |

---

## 六、效果样张

用站点自带 `skills/jiangshan-atlas/scripts/jiangshan.py`，在本地 clone 上离线渲染
（Chromium headless，2880×1800）：

| # | 样例 | URL | 输出 |
| ---: | :--- | :--- | :--- |
| 1 | 苏轼《念奴娇·赤壁怀古》 | `?year=1082&place=黄州` | `/data/soffy/tmp/jl_shots/1.png` |
| 2 | 杜牧《赤壁》 | `?year=208&place=赤壁` | `/data/soffy/tmp/jl_shots/2.png` |
| 3 | 文天祥《过零丁洋》 | `?year=1279&place=零丁洋` | `/data/soffy/tmp/jl_shots/3.png` |

三张均通过 `jiangshan.py` 的 PNG 头、尺寸（≥800×500）与像素方差检查；
`--inspect` 也确认三处 place 均可解析（黄州→湖北黄冈、赤壁→湖北咸宁赤壁、
零丁洋→广东珠江口伶仃洋）。

> 注：用户举例中的韩愈、杜甫两例不在本批 153 内（见 §三），因此样张改用同批次内
> 可形成对照的三例：苏轼黄州**文赤壁**、杜牧蒲圻**武赤壁**、文天祥零丁洋。
> 韩愈蓝关、杜甫归乡路线可在下一批扩展时补测。

---

## 七、测试

`tests/test_jiangshan_links.py` 覆盖：

1. JSON 是 153 条数组，字段集合/顺序固定，`ku_id` 全部存在于 `data/ku_packages/`，
   `ku_name`/`grade` 与原 KU 包一致；
2. URL 以 `https://deanchen.me/jiangshan-map/?` 开头，参数只允许
   `year/place/person`；地点链必须带 year 且与 `year` 字段一致，人物链必须用
   `person` 且 `year=null`；中文 place 必须在 URL 中百分号编码；
3. 年级分布与试点报告一致（G7 13、G8 46、G9 57、G10 22、G11 4、G12 11）。

运行：

```bash
cd /data/soffy/projects/mneme-wt-jiangshan
POSTGRES_PASSWORD=... python3 -m pytest tests/test_jiangshan_links.py -q --no-cov
# 3 passed in 0.14s
```

> 仓库 `pyproject` 对整仓有 60% 覆盖率门禁；单跑本文件需加 `--no-cov`，否则会因
> 只覆盖 3 个纯数据测试而触发全局覆盖率失败，与本测试正确性无关。

---

## 八、边界与下一步

1. **只做外链**：未复制对方 JS/几何/事件/坐标，未改 `ku_packages`；GPL 传染风险按
   评估报告保持最低。
2. **必须显示标识**：所有入口展示“第三方示意地图，非教材标准地图”，不用于判分、
   不做边界题材料。
3. **同名异地已拆分**：赤壁（208 蒲圻 vs 1082 黄州）、潼关（1329 张养浩 vs 1882
   谭嗣同）按 KU 分别配置；后续新增时继续遵守。
4. **下一批建议**：补“蓝关”等未入 112 键的地名锚点，可把韩愈 19 个 KU 纳入；
   杜甫归乡路线建议用多站 `?year=763&place=剑外,巴峡,巫峡,襄阳,洛阳`。
5. **合规前置**：面向学生全量上线前，仍需法务确认许可证与地图展示责任；本试点
   不构成合规签字。
