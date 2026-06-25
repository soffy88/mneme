# 文言实词 合并 Dry-Run v2

**数据库**: localhost:5433/mneme

**v2 新规则**:
- ① 例句完全相同 → 重复义项
- ② Pattern B 改名（篇目·词 → 词），再重跑册内合并


## 1. 总量

| 指标 | 数量 |
|---|---|
| 合并前总条数 | 1877 |
| 合并后总条数 | 1693 |
| 减少条数 | **184** |
| 合并组数 | 156 |
| 义项去重（含例句相同规则） | 82 |
| Pattern B 改名条目 | 273 |
| 需人工确认 | 45 |
| 跨册同名（保留不动） | 5 |

## 2. Pattern B 改名详情

**自动确认**（confidence=high）: 228 条
  - `劝学·中` → `中` (统编版高中语文必修上册)
  - `劝学·假` → `假` (统编版高中语文必修上册)
  - `劝学·参省` → `参省` (统编版高中语文必修上册)
  - `劝学·就` → `就` (统编版高中语文必修上册)
  - `劝学·挺` → `挺` (统编版高中语文必修上册)
  - `劝学·无以` → `无以` (统编版高中语文必修上册)
  - `劝学·暴` → `暴` (统编版高中语文必修上册)
  - `劝学·有` → `有` (统编版高中语文必修上册)
  - `劝学·水` → `水` (统编版高中语文必修上册)
  - `劝学·焉` → `焉` (统编版高中语文必修上册)
  - `劝学·生` → `生` (统编版高中语文必修上册)
  - `劝学·疾` → `疾` (统编版高中语文必修上册)
  - `劝学·知` → `知` (统编版高中语文必修上册)
  - `劝学·绝` → `绝` (统编版高中语文必修上册)
  - `劝学·致` → `致` (统编版高中语文必修上册)
  - `劝学·跂` → `跂` (统编版高中语文必修上册)
  - `劝学·跬步` → `跬步` (统编版高中语文必修上册)
  - `劝学·輮` → `輮` (统编版高中语文必修上册)
  - `劝学·金` → `金` (统编版高中语文必修上册)
  - `劝学·锲` → `锲` (统编版高中语文必修上册)
  - `劝学·镂` → `镂` (统编版高中语文必修上册)
  - `劝学·青` → `青` (统编版高中语文必修上册)
  - `劝学·驽马` → `驽马` (统编版高中语文必修上册)
  - `劝学·骐骥` → `骐骥` (统编版高中语文必修上册)
  - `劝学·黄泉` → `黄泉` (统编版高中语文必修上册)
  _（共 228 条，仅列前25）_

**待确认**（confidence=low）: 45 条
  - `琵琶行·文言词汇` → **`重点文言词汇释义`** (统编版高中语文必修上册) ← 请确认
  - `兄事之·名词作状语（鸿门宴）` → **`名词作状语`** (统编版高中语文必修下册) ← 请确认
  - `夜缒·用绳子拴着从城上下` → **`用绳子拴着从城上下`** (统编版高中语文必修下册) ← 请确认
  - `巾·信写在上面的白布方巾` → **`信写在上面的白布方巾`** (统编版高中语文必修下册) ← 请确认
  - `意洞·林觉民自称` → **`林觉民自称`** (统编版高中语文必修下册) ← 请确认
  - `旁·通“傍”，依傍` → **`通“傍”，依傍`** (统编版高中语文必修下册) ← 请确认
  - `烛之武退秦师·古今异义` → **`古今异义`** (统编版高中语文必修下册) ← 请确认
  - `烛之武退秦师·文言实词` → **`文言实词`** (统编版高中语文必修下册) ← 请确认
  - `烛之武退秦师·文言虚词` → **`文言虚词`** (统编版高中语文必修下册) ← 请确认
  - `烛之武退秦师·词类活用` → **`词类活用`** (统编版高中语文必修下册) ← 请确认
  - `烛之武退秦师·通假字` → **`通假字`** (统编版高中语文必修下册) ← 请确认
  - `端章甫·穿着礼服戴着礼帽` → **`穿着礼服戴着礼帽`** (统编版高中语文必修下册) ← 请确认
  - `籍吏民·名词作动词（鸿门宴）` → **`名词作动词`** (统编版高中语文必修下册) ← 请确认
  - `翼蔽·名词作状语（鸿门宴）` → **`名词作状语`** (统编版高中语文必修下册) ← 请确认
  - `诸母·各位伯母叔母` → **`各位伯母叔母`** (统编版高中语文必修下册) ← 请确认
  - `鸿门宴·古今异义` → **`古今异义`** (统编版高中语文必修下册) ← 请确认
  - `鸿门宴·文言实词` → **`文言实词`** (统编版高中语文必修下册) ← 请确认
  - `鸿门宴·词类活用` → **`词类活用`** (统编版高中语文必修下册) ← 请确认
  - `鸿门宴·通假字` → **`通假字`** (统编版高中语文必修下册) ← 请确认
  - `齐桓晋文之事·文言实词` → **`文言实词积累`** (统编版高中语文必修下册) ← 请确认

## 3. 合并样例：「以」字

### 统编版高中语文必修下册

合并前 3 条: 以·同“已”，止·例句：毋吾以也 | 以·因为·例句：以吾一日长乎尔 | 以·因为（《论语》）

合并后 name=`以`，义项数=2（去重 1 条）:

  义项1: [动词] 停止 | 例：毋吾以也
  义项2: [介词] 因为 | 例：以吾一日长乎尔

### 统编版高中语文选择性必修下册

合并前 2 条: 以·因、因为义（陈情表） | 以·用来义（陈情表）

合并后 name=`以`，义项数=2（去重 0 条）:

  义项1: [介词] 因、因为 | 例：臣以险衅
  义项2: [连词] 用来 | 例：臣以供养无主

## 4. Pattern B 改名后触发的再合并（重点）

改名后与同册已有词条合并的组：28 组

- **统编版高中语文必修上册** `有`:
  改名来源: 劝学·有 / 有·取得获得（芣苢）
  合并后义项数: 2（去重0个）
- **统编版高中语文必修下册** `与`:
  改名来源: 与·与其义（与妻书） / 与·赞同 / 吾与点也·与（《论语》）
  合并后义项数: 3（去重0个）
- **统编版高中语文必修下册** `古今异义`:
  改名来源: 烛之武退秦师·古今异义 / 鸿门宴·古今异义
  合并后义项数: 2（去重0个）
- **统编版高中语文必修下册** `名词作状语`:
  改名来源: 兄事之·名词作状语（鸿门宴） / 翼蔽·名词作状语（鸿门宴）
  合并后义项数: 2（去重0个）
- **统编版高中语文必修下册** `文言实词`:
  改名来源: 烛之武退秦师·文言实词 / 鸿门宴·文言实词
  合并后义项数: 2（去重0个）
- **统编版高中语文必修下册** `方`:
  改名来源: 方·合乎礼义的行事准则（《论语》） / 方·计量面积 / 方六七十·方（《论语》）
  合并后义项数: 3（去重0个）
- **统编版高中语文必修下册** `施`:
  改名来源: 功施到今·施（谏逐客书） / 施·延续义（谏逐客书）
  合并后义项数: 1（去重1个）
- **统编版高中语文必修下册** `相`:
  改名来源: 小相·相（《论语》） / 相·傧相，主持礼仪的人
  合并后义项数: 2（去重0个）
- **统编版高中语文必修下册** `葫芦提`:
  改名来源: 糊突·葫芦提·也么哥
  原有词条: 葫芦提
  合并后义项数: 2（去重0个）
- **统编版高中语文必修下册** `让`:
  改名来源: 其言不让·让（《论语》） / 让·辞让义（谏逐客书） / 让·辞让（谏逐客书）
  合并后义项数: 2（去重1个）
- **统编版高中语文必修下册** `词类活用`:
  改名来源: 烛之武退秦师·词类活用 / 鸿门宴·词类活用
  合并后义项数: 2（去重0个）
- **统编版高中语文必修下册** `通假字`:
  改名来源: 烛之武退秦师·通假字 / 鸿门宴·通假字
  合并后义项数: 2（去重0个）
- **统编版·语文七年级上册** `之`:
  改名来源: 久之·之 / 之·代词（《诫子书》）
  合并后义项数: 2（去重0个）
- **统编版·语文七年级上册** `亡`:
  改名来源: 《杞人忧天》·文言词语·亡 / 亡·无，没有
  合并后义项数: 1（去重1个）
- **统编版·语文七年级上册** `奈何`:
  改名来源: 《杞人忧天》·文言词语·奈何 / 奈何·为何，为什么
  合并后义项数: 2（去重0个）
- **统编版·语文七年级上册** `弛`:
  改名来源: 弛·卸下 / 弛担持刀·弛
  合并后义项数: 1（去重1个）
- **统编版·语文七年级上册** `晓`:
  改名来源: 《杞人忧天》·文言词语·晓 / 晓·告知，开导
  合并后义项数: 2（去重0个）
- **统编版·语文七年级上册** `止`:
  改名来源: 止·仅，只 / 止增笑耳·止
  合并后义项数: 2（去重0个）
- **统编版·语文七年级上册** `穿`:
  改名来源: 《穿井得一人》·文言词语·穿 / 穿·挖掘
  合并后义项数: 2（去重0个）
- **统编版·语文七年级上册** `闻`:
  改名来源: 《穿井得一人》·文言词语·闻 / 闻·使听到
  合并后义项数: 1（去重1个）
- **统编版·语文八年级上册** `且`:
  改名来源: 《愚公移山》·且·将近 / 且·况且 / 且·将要（周亚夫军细柳）
  合并后义项数: 3（去重1个）
- **统编版·语文八年级上册** `曾`:
  改名来源: 《愚公移山》·曾·加强否定 / 曾·同“增” / 曾·同增
  合并后义项数: 2（去重1个）
- **统编版·语文八年级上册** `许`:
  改名来源: 《愚公移山》·许·赞同 / 许·表示约数（与朱元思书）
  合并后义项数: 2（去重0个）
- **统编版·语文八年级下册** `为`:
  改名来源: 为·对，向 / 为坻为屿·为
  合并后义项数: 2（去重0个）
- **统编版·语文八年级下册** `可`:
  改名来源: 可·大约 / 可·大约（核舟记） / 可百许头·可
  合并后义项数: 2（去重2个）
- **统编版·语文八年级下册** `微`:
  改名来源: 式微·微 / 式微·微（如果）不是
  合并后义项数: 2（去重0个）
- **统编版·语文八年级下册** `比`:
  改名来源: 其两膝相比者·比 / 比·靠近（核舟记）
  合并后义项数: 1（去重1个）
- **统编版·语文八年级下册** `罔不`:
  改名来源: 罔不·无不（核舟记） / 罔不因势象形·罔不
  合并后义项数: 1（去重1个）

## 5. 例句相同去重案例

共 77 组有义项去重，样例:

- **统编版高中语文必修上册** `兜鍪`: 去掉1义项 | 原始: 兜鍪·古代战士的头盔（插秧歌） | 兜鍪·头盔（插秧歌）
- **统编版高中语文必修上册** `匝`: 去掉1义项 | 原始: 匝·周、圈（短歌行） | 匝·周、遍（插秧歌） | 匝·布满遍及（插秧歌）
- **统编版高中语文必修上册** `受`: 去掉1义项 | 原始: 受·传授（师说） | 受·同'授'（师说）
- **统编版高中语文必修上册** `庸`: 去掉1义项 | 原始: 庸·岂（师说） | 庸·表示反问语气（师说）
- **统编版高中语文必修上册** `既白`: 去掉1义项 | 原始: 既白·天亮 | 既白·天明
- **统编版高中语文必修上册** `莳`: 去掉1义项 | 原始: 莳·移栽、种植（插秧歌） | 莳·移栽种植（插秧歌）
- **统编版高中语文必修上册** `采采`: 去掉1义项 | 原始: 采采·茂盛的样子（芣苢） | 采采·茂盛貌（芣苢）
- **统编版高中语文必修下册** `业`: 去掉1义项 | 原始: 业·使……成就功业（谏逐客书） | 业·使动（谏逐客书）
- **统编版高中语文必修下册** `以`: 去掉1义项 | 原始: 以·同“已”，止·例句：毋吾以也 | 以·因为·例句：以吾一日长乎尔 | 以·因为（《论语》）
- **统编版高中语文必修下册** `倍`: 去掉1义项 | 原始: 倍·背弃（同“背”） | 倍·通背
- **统编版高中语文必修下册** `共`: 去掉1义项 | 原始: 共·供给义（烛之武退秦师） | 共·通“供”
- **统编版高中语文必修下册** `军`: 去掉1义项 | 原始: 军·驻扎 | 军·驻扎义（烛之武退秦师）
- **统编版高中语文必修下册** `却`: 去掉1义项 | 原始: 却·拒绝（谏逐客书） | 却·推却义（谏逐客书） | 却·推辞义（谏逐客书）
- **统编版高中语文必修下册** `哂`: 去掉1义项 | 原始: 哂·微笑 | 哂·微笑（《论语》）
- **统编版高中语文必修下册** `喟然`: 去掉1义项 | 原始: 喟然·喟（《论语》） | 喟然·感叹的样子
- **统编版高中语文必修下册** `因`: 去掉2义项 | 原始: 因·依靠 | 因·依靠义（烛之武退秦师） | 因·接续
- **统编版高中语文必修下册** `如`: 去掉1义项 | 原始: 如·或者 | 如·或者（《论语》）
- **统编版高中语文必修下册** `婚姻`: 去掉1义项 | 原始: 婚姻·古今异义 | 婚姻·古今异义（鸿门宴）
- **统编版高中语文必修下册** `度`: 去掉1义项 | 原始: 度·丈量 | 度·丈量（齐桓晋文之事）
- **统编版高中语文必修下册** `当`: 去掉1义项 | 原始: 当·抵挡 | 当·抵挡义（鸿门宴）

## 6. 需人工确认列表（不执行改名）

| ID | 原名 | 册次 | 提议 | 原因 |
|---|---|---|---|---|
| TONGBIAN-G10-CHINESE-BXS-ku-琵琶行-文言词汇 | `琵琶行·文言词汇` | 统编版高中语文必修上 | `重点文言词汇释义` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-兄事之-名词作状语-鸿门宴 | `兄事之·名词作状语（鸿门宴）` | 统编版高中语文必修下 | `名词作状语` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-夜缒-用绳子拴着从城上下 | `夜缒·用绳子拴着从城上下` | 统编版高中语文必修下 | `用绳子拴着从城上下` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-巾-信写在上面的白布方巾 | `巾·信写在上面的白布方巾` | 统编版高中语文必修下 | `信写在上面的白布方巾` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-意洞-林觉民自称 | `意洞·林觉民自称` | 统编版高中语文必修下 | `林觉民自称` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-旁-通-傍--依傍 | `旁·通“傍”，依傍` | 统编版高中语文必修下 | `通“傍”，依傍` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-烛之武退秦师-古今异义 | `烛之武退秦师·古今异义` | 统编版高中语文必修下 | `古今异义` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-烛之武退秦师-文言实词 | `烛之武退秦师·文言实词` | 统编版高中语文必修下 | `文言实词` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-烛之武退秦师-文言虚词 | `烛之武退秦师·文言虚词` | 统编版高中语文必修下 | `文言虚词` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-烛之武退秦师-词类活用 | `烛之武退秦师·词类活用` | 统编版高中语文必修下 | `词类活用` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-烛之武退秦师-通假字 | `烛之武退秦师·通假字` | 统编版高中语文必修下 | `通假字` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-端章甫-穿着礼服戴着礼帽 | `端章甫·穿着礼服戴着礼帽` | 统编版高中语文必修下 | `穿着礼服戴着礼帽` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-籍吏民-名词作动词-鸿门宴 | `籍吏民·名词作动词（鸿门宴）` | 统编版高中语文必修下 | `名词作动词` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-翼蔽-名词作状语-鸿门宴 | `翼蔽·名词作状语（鸿门宴）` | 统编版高中语文必修下 | `名词作状语` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-诸母-各位伯母叔母 | `诸母·各位伯母叔母` | 统编版高中语文必修下 | `各位伯母叔母` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-鸿门宴-古今异义 | `鸿门宴·古今异义` | 统编版高中语文必修下 | `古今异义` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-鸿门宴-文言实词 | `鸿门宴·文言实词` | 统编版高中语文必修下 | `文言实词` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-鸿门宴-词类活用 | `鸿门宴·词类活用` | 统编版高中语文必修下 | `词类活用` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-鸿门宴-通假字 | `鸿门宴·通假字` | 统编版高中语文必修下 | `通假字` | 提取词可能不准确，请确认 |
| TONGBIAN-G10-CHINESE-BXX-ku-齐桓晋文之事-文言实词 | `齐桓晋文之事·文言实词` | 统编版高中语文必修下 | `文言实词积累` | 提取词可能不准确，请确认 |
| TONGBIAN-G11-CHINESE-SBXM-ku-重-zhòng-负国-更加对不起国家 | `重（zhòng）负国·更加对不起国家` | 统编版高中语文选择性 | `更加对不起国家` | 提取词可能不准确，请确认 |
| TONGBIAN-G11-CHINESE-SBXS-ku-不失其所者久-死而不亡者寿义-老子 | `不失其所者久·死而不亡者寿义（老子）` | 统编版高中语文选择性 | `死而不亡者寿义` | 提取词可能不准确，请确认 |
| TONGBIAN-G11-CHINESE-SBXS-ku-为之于未有-治之于未乱义-老子 | `为之于未有·治之于未乱义（老子）` | 统编版高中语文选择性 | `治之于未乱义` | 提取词可能不准确，请确认 |
| TONGBIAN-G11-CHINESE-SBXS-ku-企者不立-跨者不行义-老子 | `企者不立·跨者不行义（老子）` | 统编版高中语文选择性 | `跨者不行义` | 提取词可能不准确，请确认 |
| TONGBIAN-G11-CHINESE-SBXS-ku-呺-xiāo-然-瓠落无所容义-庄子 | `呺（xiāo）然·瓠落无所容义（庄子）` | 统编版高中语文选择性 | `瓠落无所容义` | 提取词可能不准确，请确认 |
| TONGBIAN-G11-CHINESE-SBXS-ku-知人者智-自知者明义-老子 | `知人者智·自知者明义（老子）` | 统编版高中语文选择性 | `自知者明义` | 提取词可能不准确，请确认 |
| TONGBIAN-G11-CHINESE-SBXS-ku-知足者富-强行者有志义-老子 | `知足者富·强行者有志义（老子）` | 统编版高中语文选择性 | `强行者有志义` | 提取词可能不准确，请确认 |
| TONGBIAN-G11-CHINESE-SBXS-ku-胜人者有力-自胜者强义-老子 | `胜人者有力·自胜者强义（老子）` | 统编版高中语文选择性 | `自胜者强义` | 提取词可能不准确，请确认 |
| TONGBIAN-G12-CHINESE-SBXX-ku-中流-江河水流中央 | `中流·江河水流中央` | 统编版高中语文选择性 | `江河水流中央` | 提取词可能不准确，请确认 |
| TONGBIAN-G12-CHINESE-SBXX-ku-噌吰-形容钟鼓声 | `噌吰·形容钟鼓声` | 统编版高中语文选择性 | `形容钟鼓声` | 提取词可能不准确，请确认 |
| TONGBIAN-G12-CHINESE-SBXX-ku-氓-文言词汇-说-通假 | `氓·文言词汇（说·通假）` | 统编版高中语文选择性 | `文言词汇（说` | 提取词可能不准确，请确认 |
| TONGBIAN-G12-CHINESE-SBXX-ku-空中-中间是空的 | `空中·中间是空的` | 统编版高中语文选择性 | `中间是空的` | 提取词可能不准确，请确认 |
| TONGBIAN-G12-CHINESE-SBXX-ku-箱帘-同-奁--镜匣 | `箱帘·同“奁”，镜匣` | 统编版高中语文选择性 | `同“奁”，镜匣` | 提取词可能不准确，请确认 |
| TONGBIAN-G12-CHINESE-SBXX-ku-迷途-迷路-出来做官 | `迷途·迷路/出来做官` | 统编版高中语文选择性 | `迷路/出来做官` | 提取词可能不准确，请确认 |
| TONGBIAN-G7-CHINESE-S-ku-无以-没有什么可以拿来 | `无以·没有什么可以拿来` | 统编版·语文七年级上 | `没有什么可以拿来` | 提取词可能不准确，请确认 |
| TONGBIAN-G7-CHINESE-S-ku-明-明确-坚定 | `明·明确、坚定` | 统编版·语文七年级上 | `明确、坚定` | 提取词可能不准确，请确认 |
| TONGBIAN-G7-CHINESE-X-ku-动态助词-着-了-过 | `动态助词·着/了/过` | 统编版·语文七年级下 | `着/了/过` | 提取词可能不准确，请确认 |
| TONGBIAN-G7-CHINESE-X-ku-尔-同-耳--罢了 | `尔·同“耳”，罢了` | 统编版·语文七年级下 | `同“耳”，罢了` | 提取词可能不准确，请确认 |
| TONGBIAN-G7-CHINESE-X-ku-忿然-气愤的样子 | `忿然·气愤的样子` | 统编版·语文七年级下 | `气愤的样子` | 提取词可能不准确，请确认 |
| TONGBIAN-G7-CHINESE-X-ku-语气助词-了-嘛-啦-吗-呢-吧-啊 | `语气助词·了/嘛/啦/吗/呢/吧/啊` | 统编版·语文七年级下 | `了/嘛/啦/吗/呢/吧/啊` | 提取词可能不准确，请确认 |
| TONGBIAN-G8-CHINESE-X-ku-其真无马邪-加强诘问语气-马说 | `其真无马邪·加强诘问语气（马说）` | 统编版·语文八年级下 | `加强诘问语气` | 提取词可能不准确，请确认 |
| TONGBIAN-G8-CHINESE-X-ku-货恶其弃于地也-不必藏于己-礼记二则 | `货恶其弃于地也·不必藏于己（礼记二则）` | 统编版·语文八年级下 | `不必藏于己` | 提取词可能不准确，请确认 |
| TONGBIAN-G9-CHINESE-S-ku-拥毳衣炉火-裹着裘皮衣服-围着火炉-湖心亭看雪 | `拥毳衣炉火·裹着裘皮衣服，围着火炉（湖心亭看雪）` | 统编版·语文九年级上 | `裹着裘皮衣服，围着火炉` | 提取词可能不准确，请确认 |
| TONGBIAN-G9-CHINESE-X-ku-战胜于朝廷-在朝廷上取胜 | `战胜于朝廷·在朝廷上取胜` | 统编版·语文九年级下 | `在朝廷上取胜` | 提取词可能不准确，请确认 |
| TONGBIAN-G9-CHINESE-X-ku-谤讥于市朝-在公共场所指责 | `谤讥于市朝·在公共场所指责` | 统编版·语文九年级下 | `在公共场所指责` | 提取词可能不准确，请确认 |

## 7. 合并计划概览（按条数排序，前 60）

| 册次 | 词根 | 合并前 | 义项数 | 含改名? |
|---|---|---|---|---|
| 统编版高中语文必修下册 | 因 | 5条 | 3 |  |
| 统编版高中语文必修下册 | 道 | 5条 | 5 |  |
| 统编版·语文八年级上册 | 且 | 4条 | 3 | ✓改 |
| 统编版·语文八年级下册 | 可 | 4条 | 2 | ✓改 |
| 统编版高中语文必修上册 | 匝 | 3条 | 2 |  |
| 统编版高中语文必修上册 | 师 | 3条 | 3 |  |
| 统编版高中语文必修上册 | 掇 | 3条 | 3 |  |
| 统编版高中语文必修下册 | 与 | 3条 | 3 | ✓改 |
| 统编版高中语文必修下册 | 以 | 3条 | 2 |  |
| 统编版高中语文必修下册 | 内 | 3条 | 3 |  |
| 统编版高中语文必修下册 | 却 | 3条 | 2 |  |
| 统编版高中语文必修下册 | 固 | 3条 | 3 |  |
| 统编版高中语文必修下册 | 意 | 3条 | 2 |  |
| 统编版高中语文必修下册 | 方 | 3条 | 3 | ✓改 |
| 统编版高中语文必修下册 | 活 | 3条 | 2 |  |
| 统编版高中语文必修下册 | 目 | 3条 | 2 |  |
| 统编版高中语文必修下册 | 竟 | 3条 | 3 |  |
| 统编版高中语文必修下册 | 蚤 | 3条 | 1 |  |
| 统编版高中语文必修下册 | 要 | 3条 | 1 |  |
| 统编版高中语文必修下册 | 让 | 3条 | 2 | ✓改 |
| 统编版高中语文必修下册 | 非常 | 3条 | 1 |  |
| 统编版·语文八年级上册 | 曾 | 3条 | 2 | ✓改 |
| 统编版高中语文必修上册 | 偻 | 2条 | 2 |  |
| 统编版高中语文必修上册 | 兜鍪 | 2条 | 1 |  |
| 统编版高中语文必修上册 | 其 | 2条 | 2 |  |
| 统编版高中语文必修上册 | 受 | 2条 | 1 |  |
| 统编版高中语文必修上册 | 圜 | 2条 | 2 |  |
| 统编版高中语文必修上册 | 庸 | 2条 | 1 |  |
| 统编版高中语文必修上册 | 惑 | 2条 | 2 |  |
| 统编版高中语文必修上册 | 捋 | 2条 | 2 |  |
| 统编版高中语文必修上册 | 敛裾 | 2条 | 2 |  |
| 统编版高中语文必修上册 | 既白 | 2条 | 1 |  |
| 统编版高中语文必修上册 | 有 | 2条 | 2 | ✓改 |
| 统编版高中语文必修上册 | 脉脉 | 2条 | 2 |  |
| 统编版高中语文必修上册 | 莳 | 2条 | 1 |  |
| 统编版高中语文必修上册 | 薄言 | 2条 | 2 |  |
| 统编版高中语文必修上册 | 袅娜 | 2条 | 2 |  |
| 统编版高中语文必修上册 | 襭 | 2条 | 2 |  |
| 统编版高中语文必修上册 | 采采 | 2条 | 1 |  |
| 统编版高中语文必修上册 | 风致 | 2条 | 2 |  |
| 统编版高中语文必修下册 | 业 | 2条 | 1 |  |
| 统编版高中语文必修下册 | 举 | 2条 | 2 |  |
| 统编版高中语文必修下册 | 倍 | 2条 | 1 |  |
| 统编版高中语文必修下册 | 共 | 2条 | 1 |  |
| 统编版高中语文必修下册 | 军 | 2条 | 1 |  |
| 统编版高中语文必修下册 | 古今异义 | 2条 | 2 | ✓改 |
| 统编版高中语文必修下册 | 名词作状语 | 2条 | 2 | ✓改 |
| 统编版高中语文必修下册 | 哂 | 2条 | 1 |  |
| 统编版高中语文必修下册 | 喟然 | 2条 | 1 |  |
| 统编版高中语文必修下册 | 如 | 2条 | 1 |  |
| 统编版高中语文必修下册 | 婚姻 | 2条 | 1 |  |
| 统编版高中语文必修下册 | 居 | 2条 | 2 |  |
| 统编版高中语文必修下册 | 幸 | 2条 | 2 |  |
| 统编版高中语文必修下册 | 度 | 2条 | 1 |  |
| 统编版高中语文必修下册 | 当 | 2条 | 1 |  |
| 统编版高中语文必修下册 | 微 | 2条 | 1 |  |
| 统编版高中语文必修下册 | 所以 | 2条 | 2 |  |
| 统编版高中语文必修下册 | 抑 | 2条 | 2 |  |
| 统编版高中语文必修下册 | 择 | 2条 | 1 |  |
| 统编版高中语文必修下册 | 摄 | 2条 | 1 |  |

## 8. 完整合并计划 JSON

```json
[
  {
    "book": "统编版高中语文必修上册",
    "root": "偻",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "偻·弯腰",
      "偻·鞠躬义（登泰山记）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-偻-弯腰",
      "TONGBIAN-G10-CHINESE-BXS-ku-偻-鞠躬义-登泰山记"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "兜鍪",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "兜鍪·古代战士的头盔（插秧歌）",
      "兜鍪·头盔（插秧歌）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-兜鍪-古代战士的头盔-插秧歌",
      "TONGBIAN-G10-CHINESE-BXS-ku-兜鍪-头盔-插秧歌"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "其",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "其·代词（师说）",
      "其·它们（师说）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-其-代词-师说",
      "TONGBIAN-G10-CHINESE-BXS-ku-其-它们-师说"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "匝",
    "before": 3,
    "after_yixiang": 2,
    "removed_dup": 1,
    "names_before": [
      "匝·周、圈（短歌行）",
      "匝·周、遍（插秧歌）",
      "匝·布满遍及（插秧歌）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-匝-周-圈-短歌行",
      "TONGBIAN-G10-CHINESE-BXS-ku-匝-周-遍-插秧歌",
      "TONGBIAN-G10-CHINESE-BXS-ku-匝-布满遍及-插秧歌"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "受",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "受·传授（师说）",
      "受·同'授'（师说）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-受-传授-师说",
      "TONGBIAN-G10-CHINESE-BXS-ku-受-同-授--师说"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "圜",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "圜·同圆",
      "圜·同圆（登泰山记）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-圜-同圆",
      "TONGBIAN-G10-CHINESE-BXS-ku-圜-同圆-登泰山记"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "师",
    "before": 3,
    "after_yixiang": 3,
    "removed_dup": 0,
    "names_before": [
      "师·从师（师说）",
      "师·学习（师说）",
      "师·老师（师说）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-师-从师-师说",
      "TONGBIAN-G10-CHINESE-BXS-ku-师-学习-师说",
      "TONGBIAN-G10-CHINESE-BXS-ku-师-老师-师说"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "庸",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "庸·岂（师说）",
      "庸·表示反问语气（师说）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-庸-岂-师说",
      "TONGBIAN-G10-CHINESE-BXS-ku-庸-表示反问语气-师说"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "惑",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "惑·疑惑（师说）",
      "惑·糊涂（师说）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-惑-疑惑-师说",
      "TONGBIAN-G10-CHINESE-BXS-ku-惑-糊涂-师说"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "捋",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "捋·从茎上成把取下（芣苢）",
      "捋·成把地摘取（芣苢）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-捋-从茎上成把取下-芣苢",
      "TONGBIAN-G10-CHINESE-BXS-ku-捋-成把地摘取-芣苢"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "掇",
    "before": 3,
    "after_yixiang": 3,
    "removed_dup": 0,
    "names_before": [
      "掇·拾取摘取（芣苢）",
      "掇·拾取（短歌行）",
      "掇·拾取（芣苢）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-掇-拾取摘取-芣苢",
      "TONGBIAN-G10-CHINESE-BXS-ku-掇-拾取-短歌行",
      "TONGBIAN-G10-CHINESE-BXS-ku-掇-拾取-芣苢"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "敛裾",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "敛裾",
      "敛裾·古今异义（荷塘月色）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-敛裾",
      "TONGBIAN-G10-CHINESE-BXS-ku-敛裾-古今异义-荷塘月色"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "既白",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "既白·天亮",
      "既白·天明"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-既白-天亮",
      "TONGBIAN-G10-CHINESE-BXS-ku-既白-天明"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "有",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "劝学·有",
      "有·取得获得（芣苢）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-劝学-有",
      "TONGBIAN-G10-CHINESE-BXS-ku-有-取得获得-芣苢"
    ],
    "has_rename": true
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "脉脉",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "脉脉",
      "脉脉·古今异义（荷塘月色）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-脉脉",
      "TONGBIAN-G10-CHINESE-BXS-ku-脉脉-古今异义-荷塘月色"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "莳",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "莳·移栽、种植（插秧歌）",
      "莳·移栽种植（插秧歌）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-莳-移栽-种植-插秧歌",
      "TONGBIAN-G10-CHINESE-BXS-ku-莳-移栽种植-插秧歌"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "薄言",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "薄言·动词词头（芣苢）",
      "薄言·助词无实义（芣苢）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-薄言-动词词头-芣苢",
      "TONGBIAN-G10-CHINESE-BXS-ku-薄言-助词无实义-芣苢"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "袅娜",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "袅娜",
      "袅娜·古今异义（荷塘月色）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-袅娜",
      "TONGBIAN-G10-CHINESE-BXS-ku-袅娜-古今异义-荷塘月色"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "襭",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "襭·把衣襟掖在腰带兜东西（芣苢）",
      "襭·把衣襟掖在腰带间兜东西（芣苢）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-襭-把衣襟掖在腰带兜东西-芣苢",
      "TONGBIAN-G10-CHINESE-BXS-ku-襭-把衣襟掖在腰带间兜东西-芣苢"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "采采",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "采采·茂盛的样子（芣苢）",
      "采采·茂盛貌（芣苢）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-采采-茂盛的样子-芣苢",
      "TONGBIAN-G10-CHINESE-BXS-ku-采采-茂盛貌-芣苢"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修上册",
    "root": "风致",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "风致",
      "风致·古今异义（荷塘月色）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXS-ku-风致",
      "TONGBIAN-G10-CHINESE-BXS-ku-风致-古今异义-荷塘月色"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "与",
    "before": 3,
    "after_yixiang": 3,
    "removed_dup": 0,
    "names_before": [
      "与·与其义（与妻书）",
      "与·赞同",
      "吾与点也·与（《论语》）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-与-与其义-与妻书",
      "TONGBIAN-G10-CHINESE-BXX-ku-与-赞同",
      "TONGBIAN-G10-CHINESE-BXX-ku-吾与点也-与--论语"
    ],
    "has_rename": true
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "业",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "业·使……成就功业（谏逐客书）",
      "业·使动（谏逐客书）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-业-使--成就功业-谏逐客书",
      "TONGBIAN-G10-CHINESE-BXX-ku-业-使动-谏逐客书"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "举",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "举·攻克义（谏逐客书）",
      "举·攻占义（谏逐客书）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-举-攻克义-谏逐客书",
      "TONGBIAN-G10-CHINESE-BXX-ku-举-攻占义-谏逐客书"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "以",
    "before": 3,
    "after_yixiang": 2,
    "removed_dup": 1,
    "names_before": [
      "以·同“已”，止·例句：毋吾以也",
      "以·因为·例句：以吾一日长乎尔",
      "以·因为（《论语》）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-以-同-已--止-例句-毋吾以也",
      "TONGBIAN-G10-CHINESE-BXX-ku-以-因为-例句-以吾一日长乎尔",
      "TONGBIAN-G10-CHINESE-BXX-ku-以-因为--论语"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "倍",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "倍·背弃（同“背”）",
      "倍·通背"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-倍-背弃-同-背",
      "TONGBIAN-G10-CHINESE-BXX-ku-倍-通背"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "共",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "共·供给义（烛之武退秦师）",
      "共·通“供”"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-共-供给义-烛之武退秦师",
      "TONGBIAN-G10-CHINESE-BXX-ku-共-通-供"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "内",
    "before": 3,
    "after_yixiang": 3,
    "removed_dup": 0,
    "names_before": [
      "内·接纳（同“纳”）",
      "内·纳（谏逐客书）",
      "内·通假字（鸿门宴）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-内-接纳-同-纳",
      "TONGBIAN-G10-CHINESE-BXX-ku-内-纳-谏逐客书",
      "TONGBIAN-G10-CHINESE-BXX-ku-内-通假字-鸿门宴"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "军",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "军·驻扎",
      "军·驻扎义（烛之武退秦师）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-军-驻扎",
      "TONGBIAN-G10-CHINESE-BXX-ku-军-驻扎义-烛之武退秦师"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "却",
    "before": 3,
    "after_yixiang": 2,
    "removed_dup": 1,
    "names_before": [
      "却·拒绝（谏逐客书）",
      "却·推却义（谏逐客书）",
      "却·推辞义（谏逐客书）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-却-拒绝-谏逐客书",
      "TONGBIAN-G10-CHINESE-BXX-ku-却-推却义-谏逐客书",
      "TONGBIAN-G10-CHINESE-BXX-ku-却-推辞义-谏逐客书"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "古今异义",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "烛之武退秦师·古今异义",
      "鸿门宴·古今异义"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-烛之武退秦师-古今异义",
      "TONGBIAN-G10-CHINESE-BXX-ku-鸿门宴-古今异义"
    ],
    "has_rename": true
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "名词作状语",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "兄事之·名词作状语（鸿门宴）",
      "翼蔽·名词作状语（鸿门宴）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-兄事之-名词作状语-鸿门宴",
      "TONGBIAN-G10-CHINESE-BXX-ku-翼蔽-名词作状语-鸿门宴"
    ],
    "has_rename": true
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "哂",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "哂·微笑",
      "哂·微笑（《论语》）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-哂-微笑",
      "TONGBIAN-G10-CHINESE-BXX-ku-哂-微笑--论语"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "喟然",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "喟然·喟（《论语》）",
      "喟然·感叹的样子"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-喟然-喟--论语",
      "TONGBIAN-G10-CHINESE-BXX-ku-喟然-感叹的样子"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "因",
    "before": 5,
    "after_yixiang": 3,
    "removed_dup": 2,
    "names_before": [
      "因·依靠",
      "因·依靠义（烛之武退秦师）",
      "因·接续",
      "因·接续（《论语》）",
      "因·趁机义（鸿门宴）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-因-依靠",
      "TONGBIAN-G10-CHINESE-BXX-ku-因-依靠义-烛之武退秦师",
      "TONGBIAN-G10-CHINESE-BXX-ku-因-接续",
      "TONGBIAN-G10-CHINESE-BXX-ku-因-接续--论语",
      "TONGBIAN-G10-CHINESE-BXX-ku-因-趁机义-鸿门宴"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "固",
    "before": 3,
    "after_yixiang": 3,
    "removed_dup": 0,
    "names_before": [
      "固·使动（谏太宗十思疏）",
      "固·坚持（促织）",
      "固·本来（与妻书）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-固-使动-谏太宗十思疏",
      "TONGBIAN-G10-CHINESE-BXX-ku-固-坚持-促织",
      "TONGBIAN-G10-CHINESE-BXX-ku-固-本来-与妻书"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "如",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "如·或者",
      "如·或者（《论语》）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-如-或者",
      "TONGBIAN-G10-CHINESE-BXX-ku-如-或者--论语"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "婚姻",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "婚姻·古今异义",
      "婚姻·古今异义（鸿门宴）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-婚姻-古今异义",
      "TONGBIAN-G10-CHINESE-BXX-ku-婚姻-古今异义-鸿门宴"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "居",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "居·平日·例句：居则曰",
      "居·平日（《论语》）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-居-平日-例句-居则曰",
      "TONGBIAN-G10-CHINESE-BXX-ku-居-平日--论语"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "幸",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "幸·临幸义（阿房宫赋）",
      "幸·幸亏义（鸿门宴）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-幸-临幸义-阿房宫赋",
      "TONGBIAN-G10-CHINESE-BXX-ku-幸-幸亏义-鸿门宴"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "度",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "度·丈量",
      "度·丈量（齐桓晋文之事）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-度-丈量",
      "TONGBIAN-G10-CHINESE-BXX-ku-度-丈量-齐桓晋文之事"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "当",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "当·抵挡",
      "当·抵挡义（鸿门宴）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-当-抵挡",
      "TONGBIAN-G10-CHINESE-BXX-ku-当-抵挡义-鸿门宴"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "微",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "微·如果没有、不是",
      "微·如果没有（烛之武退秦师）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-微-如果没有-不是",
      "TONGBIAN-G10-CHINESE-BXX-ku-微-如果没有-烛之武退秦师"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "意",
    "before": 3,
    "after_yixiang": 2,
    "removed_dup": 1,
    "names_before": [
      "意·心意义（与妻书）",
      "意·料想",
      "意·料想义（鸿门宴）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-意-心意义-与妻书",
      "TONGBIAN-G10-CHINESE-BXX-ku-意-料想",
      "TONGBIAN-G10-CHINESE-BXX-ku-意-料想义-鸿门宴"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "所以",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "所以·表凭借（答司马谏议书）",
      "所以·表原因（答司马谏议书）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-所以-表凭借-答司马谏议书",
      "TONGBIAN-G10-CHINESE-BXX-ku-所以-表原因-答司马谏议书"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "抑",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "抑·表选择（与妻书）",
      "抑·难道（齐桓晋文之事）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-抑-表选择-与妻书",
      "TONGBIAN-G10-CHINESE-BXX-ku-抑-难道-齐桓晋文之事"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "择",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "择·区别义（谏逐客书）",
      "择·舍弃（谏逐客书）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-择-区别义-谏逐客书",
      "TONGBIAN-G10-CHINESE-BXX-ku-择-舍弃-谏逐客书"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "摄",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "摄·夹处",
      "摄·夹处（《论语》）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-摄-夹处",
      "TONGBIAN-G10-CHINESE-BXX-ku-摄-夹处--论语"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "故",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "故·交情",
      "故·旧交义（鸿门宴）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-故-交情",
      "TONGBIAN-G10-CHINESE-BXX-ku-故-旧交义-鸿门宴"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "数",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "数·多次义（鸿门宴）",
      "数·多次（读shuò）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-数-多次义-鸿门宴",
      "TONGBIAN-G10-CHINESE-BXX-ku-数-多次-读shuò"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "文言实词",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "烛之武退秦师·文言实词",
      "鸿门宴·文言实词"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-烛之武退秦师-文言实词",
      "TONGBIAN-G10-CHINESE-BXX-ku-鸿门宴-文言实词"
    ],
    "has_rename": true
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "方",
    "before": 3,
    "after_yixiang": 3,
    "removed_dup": 0,
    "names_before": [
      "方·合乎礼义的行事准则（《论语》）",
      "方·计量面积",
      "方六七十·方（《论语》）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-方-合乎礼义的行事准则--论语",
      "TONGBIAN-G10-CHINESE-BXX-ku-方-计量面积",
      "TONGBIAN-G10-CHINESE-BXX-ku-方六七十-方--论语"
    ],
    "has_rename": true
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "施",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "功施到今·施（谏逐客书）",
      "施·延续义（谏逐客书）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-功施到今-施-谏逐客书",
      "TONGBIAN-G10-CHINESE-BXX-ku-施-延续义-谏逐客书"
    ],
    "has_rename": true
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "明",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "明·圣明义（谏逐客书）",
      "明·彰明（谏逐客书）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-明-圣明义-谏逐客书",
      "TONGBIAN-G10-CHINESE-BXX-ku-明-彰明-谏逐客书"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "朝",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "朝·使……朝见",
      "朝·使……朝见（齐桓晋文之事）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-朝-使--朝见",
      "TONGBIAN-G10-CHINESE-BXX-ku-朝-使--朝见-齐桓晋文之事"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "木叶",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "木叶·树叶·落叶",
      "木叶·树叶辨析（说“木叶”）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-木叶-树叶-落叶",
      "TONGBIAN-G10-CHINESE-BXX-ku-木叶-树叶辨析-说-木叶"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "权",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "权·称量",
      "权·称量（齐桓晋文之事）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-权-称量",
      "TONGBIAN-G10-CHINESE-BXX-ku-权-称量-齐桓晋文之事"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "活",
    "before": 3,
    "after_yixiang": 2,
    "removed_dup": 1,
    "names_before": [
      "活·使……活命（使动用法）",
      "活·使动用法",
      "活·使动用法（鸿门宴）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-活-使--活命-使动用法",
      "TONGBIAN-G10-CHINESE-BXX-ku-活-使动用法",
      "TONGBIAN-G10-CHINESE-BXX-ku-活-使动用法-鸿门宴"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "率尔",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "率尔·尔（《论语》）",
      "率尔·轻率匆忙的样子"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-率尔-尔--论语",
      "TONGBIAN-G10-CHINESE-BXX-ku-率尔-轻率匆忙的样子"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "生",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "生·则·兀的",
      "生·甚、深"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-生-则-兀的",
      "TONGBIAN-G10-CHINESE-BXX-ku-生-甚-深"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "盖",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "盖·何不（齐桓晋文之事）",
      "盖·同'盍'，何不"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-盖-何不-齐桓晋文之事",
      "TONGBIAN-G10-CHINESE-BXX-ku-盖-同-盍--何不"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "目",
    "before": 3,
    "after_yixiang": 2,
    "removed_dup": 1,
    "names_before": [
      "目·名词作动词（鸿门宴）",
      "目·名词用作动词",
      "目·递眼色（名词用作动词）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-目-名词作动词-鸿门宴",
      "TONGBIAN-G10-CHINESE-BXX-ku-目-名词用作动词",
      "TONGBIAN-G10-CHINESE-BXX-ku-目-递眼色-名词用作动词"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "相",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "小相·相（《论语》）",
      "相·傧相，主持礼仪的人"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-小相-相--论语",
      "TONGBIAN-G10-CHINESE-BXX-ku-相-傧相-主持礼仪的人"
    ],
    "has_rename": true
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "着",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "着·命令义",
      "着·行·咱"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-着-命令义",
      "TONGBIAN-G10-CHINESE-BXX-ku-着-行-咱"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "窃",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "窃·私下（谏逐客书）",
      "窃·谦辞义（谏逐客书）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-窃-私下-谏逐客书",
      "TONGBIAN-G10-CHINESE-BXX-ku-窃-谦辞义-谏逐客书"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "竟",
    "before": 3,
    "after_yixiang": 3,
    "removed_dup": 0,
    "names_before": [
      "竟·完成（与妻书）",
      "竟·完毕义（与妻书）",
      "竟·终究（与妻书）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-竟-完成-与妻书",
      "TONGBIAN-G10-CHINESE-BXX-ku-竟-完毕义-与妻书",
      "TONGBIAN-G10-CHINESE-BXX-ku-竟-终究-与妻书"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "罔",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "罔·同“网”（齐桓晋文之事）",
      "罔·陷害（齐桓晋文之事）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-罔-同-网--齐桓晋文之事",
      "TONGBIAN-G10-CHINESE-BXX-ku-罔-陷害-齐桓晋文之事"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "葫芦提",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "糊突·葫芦提·也么哥",
      "葫芦提"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-糊突-葫芦提-也么哥",
      "TONGBIAN-G10-CHINESE-BXX-ku-葫芦提"
    ],
    "has_rename": true
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "蚤",
    "before": 3,
    "after_yixiang": 1,
    "removed_dup": 2,
    "names_before": [
      "蚤·早（同“早”）",
      "蚤·通假字（鸿门宴）",
      "蚤·通早"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-蚤-早-同-早",
      "TONGBIAN-G10-CHINESE-BXX-ku-蚤-通假字-鸿门宴",
      "TONGBIAN-G10-CHINESE-BXX-ku-蚤-通早"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "行李",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "行李·使者义（烛之武退秦师）",
      "行李·使者（古今异义）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-行李-使者义-烛之武退秦师",
      "TONGBIAN-G10-CHINESE-BXX-ku-行李-使者-古今异义"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "要",
    "before": 3,
    "after_yixiang": 1,
    "removed_dup": 2,
    "names_before": [
      "要·通假字（鸿门宴）",
      "要·通邀",
      "要·邀请（同“邀”）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-要-通假字-鸿门宴",
      "TONGBIAN-G10-CHINESE-BXX-ku-要-通邀",
      "TONGBIAN-G10-CHINESE-BXX-ku-要-邀请-同-邀"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "见",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "见·第一人称代词（答司马谏议书）",
      "见·表被动（答司马谏议书）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-见-第一人称代词-答司马谏议书",
      "TONGBIAN-G10-CHINESE-BXX-ku-见-表被动-答司马谏议书"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "让",
    "before": 3,
    "after_yixiang": 2,
    "removed_dup": 1,
    "names_before": [
      "其言不让·让（《论语》）",
      "让·辞让义（谏逐客书）",
      "让·辞让（谏逐客书）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-其言不让-让--论语",
      "TONGBIAN-G10-CHINESE-BXX-ku-让-辞让义-谏逐客书",
      "TONGBIAN-G10-CHINESE-BXX-ku-让-辞让-谏逐客书"
    ],
    "has_rename": true
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "词类活用",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "烛之武退秦师·词类活用",
      "鸿门宴·词类活用"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-烛之武退秦师-词类活用",
      "TONGBIAN-G10-CHINESE-BXX-ku-鸿门宴-词类活用"
    ],
    "has_rename": true
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "说",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "说·通'悦'（烛之武退秦师）",
      "说·通“悦”"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-说-通-悦--烛之武退秦师",
      "TONGBIAN-G10-CHINESE-BXX-ku-说-通-悦"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "谢",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "谢·道歉",
      "谢·道歉义（鸿门宴）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-谢-道歉",
      "TONGBIAN-G10-CHINESE-BXX-ku-谢-道歉义-鸿门宴"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "贰",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "贰·从属二主",
      "贰·从属二主义（烛之武退秦师）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-贰-从属二主",
      "TONGBIAN-G10-CHINESE-BXX-ku-贰-从属二主义-烛之武退秦师"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "资",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "资·资助义（谏逐客书）",
      "资·资助（谏逐客书）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-资-资助义-谏逐客书",
      "TONGBIAN-G10-CHINESE-BXX-ku-资-资助-谏逐客书"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "赍",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "赍·赠送义（谏逐客书）",
      "赍·送给义（谏逐客书）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-赍-赠送义-谏逐客书",
      "TONGBIAN-G10-CHINESE-BXX-ku-赍-送给义-谏逐客书"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "辟",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "辟·开辟",
      "辟·开辟（齐桓晋文之事）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-辟-开辟",
      "TONGBIAN-G10-CHINESE-BXX-ku-辟-开辟-齐桓晋文之事"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "通假字",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "烛之武退秦师·通假字",
      "鸿门宴·通假字"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-烛之武退秦师-通假字",
      "TONGBIAN-G10-CHINESE-BXX-ku-鸿门宴-通假字"
    ],
    "has_rename": true
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "道",
    "before": 5,
    "after_yixiang": 5,
    "removed_dup": 0,
    "names_before": [
      "道·取道（鸿门宴）",
      "道·规律（庖丁解牛）",
      "道·说（齐桓晋文之事）",
      "道·道理（庖丁解牛）",
      "道·道路（烛之武退秦师）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-道-取道-鸿门宴",
      "TONGBIAN-G10-CHINESE-BXX-ku-道-规律-庖丁解牛",
      "TONGBIAN-G10-CHINESE-BXX-ku-道-说-齐桓晋文之事",
      "TONGBIAN-G10-CHINESE-BXX-ku-道-道理-庖丁解牛",
      "TONGBIAN-G10-CHINESE-BXX-ku-道-道路-烛之武退秦师"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "郤",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "郤·通假字（鸿门宴）",
      "郤·隔阂（同“隙”）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-郤-通假字-鸿门宴",
      "TONGBIAN-G10-CHINESE-BXX-ku-郤-隔阂-同-隙"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "鄙",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "鄙·边邑",
      "鄙·边邑（名词用作动词）（烛之武退秦师）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-鄙-边邑",
      "TONGBIAN-G10-CHINESE-BXX-ku-鄙-边邑-名词用作动词--烛之武退秦师"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "阙",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "阙·使……削减",
      "阙·侵损义（烛之武退秦师）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-阙-使--削减",
      "TONGBIAN-G10-CHINESE-BXX-ku-阙-侵损义-烛之武退秦师"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "陪",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "陪·增加",
      "陪·增加义（烛之武退秦师）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-陪-增加",
      "TONGBIAN-G10-CHINESE-BXX-ku-陪-增加义-烛之武退秦师"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "非常",
    "before": 3,
    "after_yixiang": 1,
    "removed_dup": 2,
    "names_before": [
      "非常·古今异义",
      "非常·古今异义（鸿门宴）",
      "非常·意外的变故（古今异义）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-非常-古今异义",
      "TONGBIAN-G10-CHINESE-BXX-ku-非常-古今异义-鸿门宴",
      "TONGBIAN-G10-CHINESE-BXX-ku-非常-意外的变故-古今异义"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文必修下册",
    "root": "黔首",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "黔首·民众（谏逐客书）",
      "黔首·百姓义（谏逐客书）"
    ],
    "ids": [
      "TONGBIAN-G10-CHINESE-BXX-ku-黔首-民众-谏逐客书",
      "TONGBIAN-G10-CHINESE-BXX-ku-黔首-百姓义-谏逐客书"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文选择性必修中册",
    "root": "亡",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "亡",
      "亡·同无理之无（苏武传）"
    ],
    "ids": [
      "TONGBIAN-G11-CHINESE-SBXM-ku-亡",
      "TONGBIAN-G11-CHINESE-SBXM-ku-亡-同无理之无-苏武传"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文选择性必修中册",
    "root": "见",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "见·同现（苏武传）",
      "见·被动标记（屈原列传）"
    ],
    "ids": [
      "TONGBIAN-G11-CHINESE-SBXM-ku-见-同现-苏武传",
      "TONGBIAN-G11-CHINESE-SBXM-ku-见-被动标记-屈原列传"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文选择性必修上册",
    "root": "恶",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "恶·何怎么义（兼爱）",
      "恶·动词·厌恶（恶其声）"
    ],
    "ids": [
      "TONGBIAN-G11-CHINESE-SBXS-ku-恶-何怎么义-兼爱",
      "TONGBIAN-G11-CHINESE-SBXS-ku-恶-动词-厌恶-恶其声"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文选择性必修上册",
    "root": "然",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "然·代词·这样（而然）",
      "然·通假字·同“燃”（始然）"
    ],
    "ids": [
      "TONGBIAN-G11-CHINESE-SBXS-ku-然-代词-这样-而然",
      "TONGBIAN-G11-CHINESE-SBXS-ku-然-通假字-同-燃--始然"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文选择性必修下册",
    "root": "以",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "以·因、因为义（陈情表）",
      "以·用来义（陈情表）"
    ],
    "ids": [
      "TONGBIAN-G12-CHINESE-SBXX-ku-以-因-因为义-陈情表",
      "TONGBIAN-G12-CHINESE-SBXX-ku-以-用来义-陈情表"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文选择性必修下册",
    "root": "矜",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "矜·怜悯义（陈情表）",
      "矜·顾惜义（陈情表）"
    ],
    "ids": [
      "TONGBIAN-G12-CHINESE-SBXX-ku-矜-怜悯义-陈情表",
      "TONGBIAN-G12-CHINESE-SBXX-ku-矜-顾惜义-陈情表"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文选择性必修下册",
    "root": "适",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "适·出嫁",
      "适·刚才"
    ],
    "ids": [
      "TONGBIAN-G12-CHINESE-SBXX-ku-适-出嫁",
      "TONGBIAN-G12-CHINESE-SBXX-ku-适-刚才"
    ],
    "has_rename": false
  },
  {
    "book": "统编版高中语文选择性必修下册",
    "root": "除",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "除·授予官职义（陈情表）",
      "除·授官义（陈情表）"
    ],
    "ids": [
      "TONGBIAN-G12-CHINESE-SBXX-ku-除-授予官职义-陈情表",
      "TONGBIAN-G12-CHINESE-SBXX-ku-除-授官义-陈情表"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文七年级上册",
    "root": "之",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "久之·之",
      "之·代词（《诫子书》）"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-S-ku-久之-之",
      "TONGBIAN-G7-CHINESE-S-ku-之-代词--诫子书"
    ],
    "has_rename": true
  },
  {
    "book": "统编版·语文七年级上册",
    "root": "乐",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "乐·以……为乐",
      "乐·以……为快乐"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-S-ku-乐-以--为乐",
      "TONGBIAN-G7-CHINESE-S-ku-乐-以--为快乐"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文七年级上册",
    "root": "亡",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "《杞人忧天》·文言词语·亡",
      "亡·无，没有"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-S-ku-杞人忧天--文言词语-亡",
      "TONGBIAN-G7-CHINESE-S-ku-亡-无-没有"
    ],
    "has_rename": true
  },
  {
    "book": "统编版·语文七年级上册",
    "root": "俄而",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "俄而·é'ér",
      "俄而·不久"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-S-ku-俄而-é-ér",
      "TONGBIAN-G7-CHINESE-S-ku-俄而-不久"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文七年级上册",
    "root": "因",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "因·yīn",
      "因·趁、乘"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-S-ku-因-yīn",
      "TONGBIAN-G7-CHINESE-S-ku-因-趁-乘"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文七年级上册",
    "root": "奈何",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "《杞人忧天》·文言词语·奈何",
      "奈何·为何，为什么"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-S-ku-杞人忧天--文言词语-奈何",
      "TONGBIAN-G7-CHINESE-S-ku-奈何-为何-为什么"
    ],
    "has_rename": true
  },
  {
    "book": "统编版·语文七年级上册",
    "root": "差可拟",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "差可拟·chākěnǐ",
      "差可拟·大体可以相比"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-S-ku-差可拟-chākěnǐ",
      "TONGBIAN-G7-CHINESE-S-ku-差可拟-大体可以相比"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文七年级上册",
    "root": "弛",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "弛·卸下",
      "弛担持刀·弛"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-S-ku-弛-卸下",
      "TONGBIAN-G7-CHINESE-S-ku-弛担持刀-弛"
    ],
    "has_rename": true
  },
  {
    "book": "统编版·语文七年级上册",
    "root": "晓",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "《杞人忧天》·文言词语·晓",
      "晓·告知，开导"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-S-ku-杞人忧天--文言词语-晓",
      "TONGBIAN-G7-CHINESE-S-ku-晓-告知-开导"
    ],
    "has_rename": true
  },
  {
    "book": "统编版·语文七年级上册",
    "root": "未若",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "未若·wèiruò",
      "未若·不如"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-S-ku-未若-wèiruò",
      "TONGBIAN-G7-CHINESE-S-ku-未若-不如"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文七年级上册",
    "root": "止",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "止·仅，只",
      "止增笑耳·止"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-S-ku-止-仅-只",
      "TONGBIAN-G7-CHINESE-S-ku-止增笑耳-止"
    ],
    "has_rename": true
  },
  {
    "book": "统编版·语文七年级上册",
    "root": "穿",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "《穿井得一人》·文言词语·穿",
      "穿·挖掘"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-S-ku-穿井得一人--文言词语-穿",
      "TONGBIAN-G7-CHINESE-S-ku-穿-挖掘"
    ],
    "has_rename": true
  },
  {
    "book": "统编版·语文七年级上册",
    "root": "说",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "说·同“悦”",
      "说·通假字"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-S-ku-说-同-悦",
      "TONGBIAN-G7-CHINESE-S-ku-说-通假字"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文七年级上册",
    "root": "闻",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "《穿井得一人》·文言词语·闻",
      "闻·使听到"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-S-ku-穿井得一人--文言词语-闻",
      "TONGBIAN-G7-CHINESE-S-ku-闻-使听到"
    ],
    "has_rename": true
  },
  {
    "book": "统编版·语文七年级上册",
    "root": "顾",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "顾·回头看",
      "顾·看，视"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-S-ku-顾-回头看",
      "TONGBIAN-G7-CHINESE-S-ku-顾-看-视"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文七年级上册",
    "root": "骤",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "骤·zhòu",
      "骤·急"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-S-ku-骤-zhòu",
      "TONGBIAN-G7-CHINESE-S-ku-骤-急"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文七年级下册",
    "root": "为",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "为·wèi",
      "为·wéi"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-X-ku-为-wèi",
      "TONGBIAN-G7-CHINESE-X-ku-为-wéi"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文七年级下册",
    "root": "乃",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "乃·nǎi",
      "乃·是（最苦与最乐）"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-X-ku-乃-nǎi",
      "TONGBIAN-G7-CHINESE-X-ku-乃-是-最苦与最乐"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文七年级下册",
    "root": "但",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "但·dàn",
      "但·文言词语"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-X-ku-但-dàn",
      "TONGBIAN-G7-CHINESE-X-ku-但-文言词语"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文七年级下册",
    "root": "安",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "安·使……安适（庄子）",
      "安·怎么"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-X-ku-安-使--安适-庄子",
      "TONGBIAN-G7-CHINESE-X-ku-安-怎么"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文七年级下册",
    "root": "就",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "就·jiù",
      "就·靠近"
    ],
    "ids": [
      "TONGBIAN-G7-CHINESE-X-ku-就-jiù",
      "TONGBIAN-G7-CHINESE-X-ku-就-靠近"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文八年级上册",
    "root": "上",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "上·向上（与朱元思书）",
      "上·在上面（与朱元思书）"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-S-ku-上-向上-与朱元思书",
      "TONGBIAN-G8-CHINESE-S-ku-上-在上面-与朱元思书"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文八年级上册",
    "root": "且",
    "before": 4,
    "after_yixiang": 3,
    "removed_dup": 1,
    "names_before": [
      "《愚公移山》·且·将近",
      "且·况且",
      "且·将要（周亚夫军细柳）",
      "且·将近"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-S-ku-愚公移山--且-将近",
      "TONGBIAN-G8-CHINESE-S-ku-且-况且",
      "TONGBIAN-G8-CHINESE-S-ku-且-将要-周亚夫军细柳",
      "TONGBIAN-G8-CHINESE-S-ku-且-将近"
    ],
    "has_rename": true
  },
  {
    "book": "统编版·语文八年级上册",
    "root": "举",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "举·选拔，任用",
      "举·高飞（渔家傲）"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-S-ku-举-选拔-任用",
      "TONGBIAN-G8-CHINESE-S-ku-举-高飞-渔家傲"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文八年级上册",
    "root": "反",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "反·同'返'",
      "反·同“返”，返回（与朱元思书）"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-S-ku-反-同-返",
      "TONGBIAN-G8-CHINESE-S-ku-反-同-返--返回-与朱元思书"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文八年级上册",
    "root": "奔",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "奔·飞奔的马（三峡）",
      "奔·飞奔的马（与朱元思书）"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-S-ku-奔-飞奔的马-三峡",
      "TONGBIAN-G8-CHINESE-S-ku-奔-飞奔的马-与朱元思书"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文八年级上册",
    "root": "曾",
    "before": 3,
    "after_yixiang": 2,
    "removed_dup": 1,
    "names_before": [
      "《愚公移山》·曾·加强否定",
      "曾·同“增”",
      "曾·同增"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-S-ku-愚公移山--曾-加强否定",
      "TONGBIAN-G8-CHINESE-S-ku-曾-同-增",
      "TONGBIAN-G8-CHINESE-S-ku-曾-同增"
    ],
    "has_rename": true
  },
  {
    "book": "统编版·语文八年级上册",
    "root": "苦",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "苦·使动用法",
      "苦·愁苦，这里指担心"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-S-ku-苦-使动用法",
      "TONGBIAN-G8-CHINESE-S-ku-苦-愁苦-这里指担心"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文八年级上册",
    "root": "许",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "《愚公移山》·许·赞同",
      "许·表示约数（与朱元思书）"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-S-ku-愚公移山--许-赞同",
      "TONGBIAN-G8-CHINESE-S-ku-许-表示约数-与朱元思书"
    ],
    "has_rename": true
  },
  {
    "book": "统编版·语文八年级下册",
    "root": "为",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "为·对，向",
      "为坻为屿·为"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-X-ku-为-对-向",
      "TONGBIAN-G8-CHINESE-X-ku-为坻为屿-为"
    ],
    "has_rename": true
  },
  {
    "book": "统编版·语文八年级下册",
    "root": "亲",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "亲·亲（意动用法）",
      "亲·以……为亲（礼记二则）"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-X-ku-亲-亲-意动用法",
      "TONGBIAN-G8-CHINESE-X-ku-亲-以--为亲-礼记二则"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文八年级下册",
    "root": "分",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "分·分",
      "分·职分（礼记二则）"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-X-ku-分-分",
      "TONGBIAN-G8-CHINESE-X-ku-分-职分-礼记二则"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文八年级下册",
    "root": "可",
    "before": 4,
    "after_yixiang": 2,
    "removed_dup": 2,
    "names_before": [
      "可·大约",
      "可·大约（核舟记）",
      "可百许头·可",
      "高可二黍许·可"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-X-ku-可-大约",
      "TONGBIAN-G8-CHINESE-X-ku-可-大约-核舟记",
      "TONGBIAN-G8-CHINESE-X-ku-可百许头-可",
      "TONGBIAN-G8-CHINESE-X-ku-高可二黍许-可"
    ],
    "has_rename": true
  },
  {
    "book": "统编版·语文八年级下册",
    "root": "妻子",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "妻子·妻子儿女",
      "妻子·妻子和儿女"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-X-ku-妻子-妻子儿女",
      "TONGBIAN-G8-CHINESE-X-ku-妻子-妻子和儿女"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文八年级下册",
    "root": "归",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "归·女子出嫁（礼记二则）",
      "归·归"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-X-ku-归-女子出嫁-礼记二则",
      "TONGBIAN-G8-CHINESE-X-ku-归-归"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文八年级下册",
    "root": "微",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "式微·微",
      "式微·微（如果）不是"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-X-ku-式微-微",
      "TONGBIAN-G8-CHINESE-X-ku-式微-微-如果-不是"
    ],
    "has_rename": true
  },
  {
    "book": "统编版·语文八年级下册",
    "root": "志",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "志·做记号",
      "志·志"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-X-ku-志-做记号",
      "TONGBIAN-G8-CHINESE-X-ku-志-志"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文八年级下册",
    "root": "比",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "其两膝相比者·比",
      "比·靠近（核舟记）"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-X-ku-其两膝相比者-比",
      "TONGBIAN-G8-CHINESE-X-ku-比-靠近-核舟记"
    ],
    "has_rename": true
  },
  {
    "book": "统编版·语文八年级下册",
    "root": "绝境",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "绝境·与世隔绝的地方",
      "绝境·与人世隔绝的地方"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-X-ku-绝境-与世隔绝的地方",
      "TONGBIAN-G8-CHINESE-X-ku-绝境-与人世隔绝的地方"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文八年级下册",
    "root": "罔不",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "罔不·无不（核舟记）",
      "罔不因势象形·罔不"
    ],
    "ids": [
      "TONGBIAN-G8-CHINESE-X-ku-罔不-无不-核舟记",
      "TONGBIAN-G8-CHINESE-X-ku-罔不因势象形-罔不"
    ],
    "has_rename": true
  },
  {
    "book": "统编版·语文九年级上册",
    "root": "兀的",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "兀的·怎么",
      "兀的·怎能"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-S-ku-兀的-怎么",
      "TONGBIAN-G9-CHINESE-S-ku-兀的-怎能"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级上册",
    "root": "封",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "封·奏章",
      "封·谏书（左迁至蓝关示侄孙湘）"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-S-ku-封-奏章",
      "TONGBIAN-G9-CHINESE-S-ku-封-谏书-左迁至蓝关示侄孙湘"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级上册",
    "root": "屏人促席",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "屏人促席·使回避，将座席靠近",
      "屏人促席·屏退他人靠近坐席"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-S-ku-屏人促席-使回避-将座席靠近",
      "TONGBIAN-G9-CHINESE-S-ku-屏人促席-屏退他人靠近坐席"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级上册",
    "root": "开",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "开·启发",
      "开·天气放晴"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-S-ku-开-启发",
      "TONGBIAN-G9-CHINESE-S-ku-开-天气放晴"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级上册",
    "root": "弊事",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "弊事·有害的事",
      "弊事·有害的事（左迁至蓝关示侄孙湘）"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-S-ku-弊事-有害的事",
      "TONGBIAN-G9-CHINESE-S-ku-弊事-有害的事-左迁至蓝关示侄孙湘"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级上册",
    "root": "桑梓",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "桑梓·家乡",
      "桑梓·桑梓"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-S-ku-桑梓-家乡",
      "TONGBIAN-G9-CHINESE-S-ku-桑梓-桑梓"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级上册",
    "root": "肯",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "肯·岂肯",
      "肯·岂肯（左迁至蓝关示侄孙湘）"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-S-ku-肯-岂肯",
      "TONGBIAN-G9-CHINESE-S-ku-肯-岂肯-左迁至蓝关示侄孙湘"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级上册",
    "root": "雾凇沆砀",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "雾凇沆砀·冰花弥漫（湖心亭看雪）",
      "雾凇沆砀·白汽弥漫（湖心亭看雪）"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-S-ku-雾凇沆砀-冰花弥漫-湖心亭看雪",
      "TONGBIAN-G9-CHINESE-S-ku-雾凇沆砀-白汽弥漫-湖心亭看雪"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级上册",
    "root": "顾",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "顾·义项",
      "顾·拜访"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-S-ku-顾-义项",
      "TONGBIAN-G9-CHINESE-S-ku-顾-拜访"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级下册",
    "root": "书",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "书·书写（陈涉世家）",
      "书·字条（陈涉世家）"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-X-ku-书-书写-陈涉世家",
      "TONGBIAN-G9-CHINESE-X-ku-书-字条-陈涉世家"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级下册",
    "root": "休祲",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "休祲·吉凶征兆（唐雎不辱使命）",
      "休祲·吉凶的征兆"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-X-ku-休祲-吉凶征兆-唐雎不辱使命",
      "TONGBIAN-G9-CHINESE-X-ku-休祲-吉凶的征兆"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级下册",
    "root": "再",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "再·两次（送东阳马生序）",
      "再·第二次"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-X-ku-再-两次-送东阳马生序",
      "TONGBIAN-G9-CHINESE-X-ku-再-第二次"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级下册",
    "root": "数",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "数·几（陈涉世家）",
      "数·屡次（陈涉世家）"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-X-ku-数-几-陈涉世家",
      "TONGBIAN-G9-CHINESE-X-ku-数-屡次-陈涉世家"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级下册",
    "root": "次",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "次·编次（陈涉世家）",
      "次·驻扎（陈涉世家）"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-X-ku-次-编次-陈涉世家",
      "TONGBIAN-G9-CHINESE-X-ku-次-驻扎-陈涉世家"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级下册",
    "root": "汤",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "汤·热水",
      "汤·热水（送东阳马生序）"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-X-ku-汤-热水",
      "TONGBIAN-G9-CHINESE-X-ku-汤-热水-送东阳马生序"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级下册",
    "root": "等",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "等·同样（陈涉世家）",
      "等·表示复数（陈涉世家）"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-X-ku-等-同样-陈涉世家",
      "TONGBIAN-G9-CHINESE-X-ku-等-表示复数-陈涉世家"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级下册",
    "root": "腰",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "腰·在腰间佩戴",
      "腰·腰间佩戴（送东阳马生序）"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-X-ku-腰-在腰间佩戴",
      "TONGBIAN-G9-CHINESE-X-ku-腰-腰间佩戴-送东阳马生序"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级下册",
    "root": "被",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "被·同“披”（送东阳马生序）",
      "被·同“披”（陈涉世家）"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-X-ku-被-同-披--送东阳马生序",
      "TONGBIAN-G9-CHINESE-X-ku-被-同-披--陈涉世家"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级下册",
    "root": "走",
    "before": 2,
    "after_yixiang": 1,
    "removed_dup": 1,
    "names_before": [
      "走·跑",
      "走·跑（送东阳马生序）"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-X-ku-走-跑",
      "TONGBIAN-G9-CHINESE-X-ku-走-跑-送东阳马生序"
    ],
    "has_rename": false
  },
  {
    "book": "统编版·语文九年级下册",
    "root": "间",
    "before": 2,
    "after_yixiang": 2,
    "removed_dup": 0,
    "names_before": [
      "间·参与",
      "间·暗中（陈涉世家）"
    ],
    "ids": [
      "TONGBIAN-G9-CHINESE-X-ku-间-参与",
      "TONGBIAN-G9-CHINESE-X-ku-间-暗中-陈涉世家"
    ],
    "has_rename": false
  }
]
```