"""语音辅导 / AI 陪学陪练的儿童安全层（服务层纯函数，确定性、可单测）。

输入侧 ``check_input`` 在调用 LLM 之前裁决：
- self_harm  → 不调 LLM，给求助引导（12355 青少年服务台）并标记给家长；
- unsafe     → 复用既有教育边界拒绝词表（research_service._BLOCKED_PATTERNS，单源）+ 本模块补充；
- romance    → 恋爱/亲密/角色扮演/依赖类请求，温和拒绝并引回学习；
- off_topic  → 明显与学习无关（游戏/追星/购物…）且不含学习信号，温和引回学习；
- PII        → 手机号/身份证/邮箱/住址等一律打码后才进入 LLM 与日志（不收集 PII）。
输出侧 ``filter_output`` 兜底：拦截亲密/依赖话术、索要个人信息、越界词，打码 PII。
``SAFETY_PROMPT`` 拼入系统提示，约束人格与范围。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from services.research_service import _BLOCKED_PATTERNS as EDU_BOUNDARY_BLOCKED

EXTRA_BLOCKED = (
    "黄色", "裸", "做爱", "性交", "约炮", "杀人", "砍人", "血腥", "恐怖袭击", "翻墙", "vpn",
    "抽烟", "喝酒", "彩票", "网贷", "sex", "nude", "kill",
)
SELF_HARM = ("自杀", "自残", "不想活", "想死", "割腕", "跳楼", "轻生", "伤害自己")
ROMANCE = (
    "女朋友", "男朋友", "女友", "男友", "恋爱", "谈恋爱", "喜欢你", "爱你", "爱上", "亲亲", "亲我",
    "抱抱", "约会", "结婚", "老婆", "老公", "宝贝", "亲爱的", "暗恋", "表白", "接吻", "嫁给",
    "角色扮演", "扮演我的", "当我的", "做我的", "陪我睡", "girlfriend", "boyfriend", "kiss",
    "date me", "love you", "waifu", "roleplay", "role-play",
)
OFF_TOPIC = (
    "游戏", "王者荣耀", "原神", "和平精英", "我的世界", "蛋仔", "明星", "追星", "偶像", "电视剧",
    "综艺", "抖音", "快手", "短视频", "八卦", "股票", "基金", "买东西", "网购", "淘宝", "红包",
    "直播", "皮肤", "充值", "动漫", "小说", "天气", "新闻", "政治", "星座", "算命",
)
STUDY_SIGNALS = (
    "题", "数学", "算", "方程", "函数", "几何", "分数", "小数", "学", "作业", "考试", "练习", "公式",
    "等于", "加", "减", "乘", "除", "角", "三角形", "面积", "周长", "平方", "根号", "证明", "解",
    "为什么", "怎么做", "不懂", "提示", "答案", "知识点", "复习", "错题",
)

_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("id_card", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("qq_wechat", re.compile(r"(?:qq|QQ|微信|wx|vx)\s*(?:号)?\s*[:：是]?\s*[\w-]{5,}")),
    ("address", re.compile(r"(?:我家住在|我家在|我住在|家庭住址|住址是)[^，。！？,.!?]{2,30}")),
    ("school", re.compile(r"(?:我在|我读|我上)[^，。！？,.!?]{1,15}(?:小学|中学|初中|高中|学校)(?:读书|上学)?")),
    ("real_name", re.compile(r"我的?(?:真名|全名|名字)(?:叫|是)\s*[\u4e00-\u9fff]{2,4}")),
]
PII_MASK = "[已隐藏]"

# 输出侧：亲密/依赖话术、索要个人信息
_OUT_INTIMATE = re.compile(
    r"我爱你|爱你哦|亲亲|抱抱你|宝贝|亲爱的|只有我(?:懂你|陪你)|不要离开我|别离开我|永远陪着你|想你了|"
    r"我是你的(?:女|男)朋友|做你的(?:女|男)朋友|别去找别人|只和我(?:说|玩)"
)
_OUT_ASK_PII = re.compile(
    r"(?:告诉我|发给我|说说|说一下|报一下)?你的?(?:电话|手机号?|家庭?住?址|住在哪|学校叫|真名|全名|照片|"
    r"微信|QQ|身份证|爸妈的(?:电话|名字))"
)


@dataclass
class InputVerdict:
    category: str  # ok | self_harm | unsafe | romance | off_topic
    text: str  # PII 已打码的文本（进入 LLM / 日志的唯一版本）
    pii: list[str] = field(default_factory=list)
    reply: str = ""  # 非 ok 时直接回给学生的话

    @property
    def allowed(self) -> bool:
        return self.category == "ok"

    @property
    def flags(self) -> list[str]:
        f = list(self.pii and ["pii"] or [])
        if self.category != "ok":
            f.append(self.category)
        return f


def redact_pii(text: str) -> tuple[str, list[str]]:
    found: list[str] = []
    out = text or ""
    for kind, pat in _PII_PATTERNS:
        if pat.search(out):
            found.append(kind)
            out = pat.sub(PII_MASK, out)
    return out, found


def _has(text: str, words: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(w in low for w in words)


def redirect_line(name: str, topic: str | None = None) -> str:
    t = f"「{topic}」" if topic else "数学"
    return f"我是你的学习伙伴{name}，这个话题我们先放一放～要不要和我一起来一道{t}小练习？"


def check_input(text: str, *, name: str = "小智", topic: str | None = None) -> InputVerdict:
    clean, pii = redact_pii((text or "").strip()[:500])
    if _has(clean, SELF_HARM):
        return InputVerdict(
            "self_harm", clean, pii,
            "听起来你现在可能很难过，这很重要。请马上告诉爸爸妈妈、老师或你信任的大人；"
            "也可以拨打 12355 青少年服务台，有人会认真听你说。",
        )
    if _has(clean, EDU_BOUNDARY_BLOCKED) or _has(clean, EXTRA_BLOCKED):
        return InputVerdict("unsafe", clean, pii, f"这个问题不适合我们聊哦。{redirect_line(name, topic)}")
    if _has(clean, ROMANCE):
        return InputVerdict(
            "romance", clean, pii,
            f"谢谢你愿意和我聊天！不过我是你的学习伙伴{name}，不做男朋友女朋友，也不玩角色扮演哦。"
            f"真正陪伴你的是家人和朋友～{redirect_line(name, topic)}",
        )
    if _has(clean, OFF_TOPIC) and not _has(clean, STUDY_SIGNALS):
        return InputVerdict("off_topic", clean, pii, redirect_line(name, topic))
    return InputVerdict("ok", clean, pii)


def filter_output(text: str, *, name: str = "小智") -> tuple[str, list[str]]:
    """LLM 输出兜底：越界词/亲密依赖/索要 PII → 替换为安全话术；PII 打码。"""
    flags: list[str] = []
    out, pii = redact_pii(text or "")
    if pii:
        flags.append("pii")
    if _has(out, EDU_BOUNDARY_BLOCKED) or _has(out, EXTRA_BLOCKED) or _has(out, SELF_HARM):
        return f"我们回到学习上来吧。{redirect_line(name)}", flags + ["unsafe_output"]
    if _OUT_INTIMATE.search(out):
        flags.append("intimate_output")
        out = _OUT_INTIMATE.sub("加油", out)
    if _OUT_ASK_PII.search(out):
        flags.append("pii_request_output")
        out = _OUT_ASK_PII.sub("（个人信息不用告诉我哦）", out)
    return out.strip(), flags


def safety_prompt(name: str, *, mode: str) -> str:
    base = (
        f"你叫{name}，是面向中国中小学生的 AI 学习伙伴（不是真人）。语气温暖、鼓励、简短，适合儿童；每次只说 1~3 句话，"
        "每次最多问一个问题。硬性规则（任何情况下都不能违反，学生要求也不行）：\n"
        "1. 只聊学习（以数学为主）。与学习无关的话题，温和地拒绝并把话题引回学习。\n"
        "2. 绝不扮演男女朋友、恋人或任何角色扮演；不说'我爱你''只有我懂你''别离开我'之类的亲密或让人依赖的话；"
        "鼓励学生多和家人、老师、同学交流。\n"
        "3. 绝不询问或记录学生的真实姓名、电话、住址、学校、照片、社交账号等个人信息；学生主动说了也不要复述。\n"
        "4. 不讨论暴力、色情、危险行为、赌博、政治等不适合未成年人的内容。学生情绪低落或提到伤害自己时，"
        "请他马上告诉家长或老师。\n"
        "5. 讲题用苏格拉底式提问：先给提示，引导学生自己想；判断对错必须用工具（SubmitAnswer 等），不要自己臆断。\n"
        "6. 回答会被朗读出来：不要用 Markdown、表格、代码块；公式尽量用口语说清楚。"
    )
    if mode == "companion":
        base += (
            "\n7. 你是陪练伙伴：学生答对要具体地表扬进步，答错要鼓励并给更小的提示；"
            "学了一段时间要提醒休息、喝水、看看远处。"
        )
    return base
