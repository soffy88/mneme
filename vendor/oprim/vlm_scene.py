"""
VLM Scene Description — 视觉语言模型场景感知原子操作
===================================================
vendor/oprim/vlm_scene.py

单次原子操作：输入图片(base64)或文本描述 → 输出结构化场景描述。
支持两种模式：
  1. VLM 模式：提供 image_b64，调用 VLMCaller 分析图片
  2. 文本模式：提供 text_description，直接解析为结构化输出

输出结构（AriaScenePerception）：
  - objects: 场景中的物体列表
  - lighting: 光线描述
  - mood: 氛围判断
  - time_of_day: 时间段
  - activity_context: 活动上下文
  - user_visible: 用户是否可见
  - raw_description: 原始描述文本

不依赖其他 oprim。纯函数倾向。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from obase.provider_registry import VLMCaller

logger = logging.getLogger(__name__)


# ── Output Model ──────────────────────────────────────────────────────────────

@dataclass
class AriaScenePerception:
    """Director 可消费的结构化场景描述。"""

    objects: List[str] = field(default_factory=list)
    lighting: str = "neutral"
    mood: str = "neutral"
    time_of_day: str = "daytime"
    activity_context: str = "general"
    user_visible: bool = True
    raw_description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_director_brief(self) -> str:
        """生成 Director prompt 可嵌入的简短描述。"""
        parts: List[str] = []
        if self.objects:
            parts.append(f"场景中有：{', '.join(self.objects[:6])}")
        if self.lighting and self.lighting != "neutral":
            parts.append(f"光线：{self.lighting}")
        if self.mood and self.mood != "neutral":
            parts.append(f"氛围：{self.mood}")
        if self.time_of_day and self.time_of_day != "daytime":
            parts.append(f"时间：{self.time_of_day}")
        if self.activity_context and self.activity_context != "general":
            parts.append(f"活动：{self.activity_context}")
        return "；".join(parts) if parts else "普通房间场景"


# ── VLM Prompt ────────────────────────────────────────────────────────────────

_VLM_SYSTEM = (
    "你是一个场景分析助手。分析图片中的人物所处环境，输出 JSON 格式：\n"
    '{"objects": ["物体1", "物体2", ...], '
    '"lighting": "光线描述(英文短语)", '
    '"mood": "氛围(英文短语)", '
    '"time_of_day": "morning|afternoon|evening|night", '
    '"activity_context": "活动上下文(英文短语)", '
    '"user_visible": true/false}\n'
    "只输出 JSON，不要其他内容。"
)


# ── Text Parsing ──────────────────────────────────────────────────────────────

_ROOM_KEYWORDS: Dict[str, List[str]] = {
    "grand_piano": ["钢琴", "三角钢琴", "piano", "grand piano", "琴"],
    "upright_piano": ["立式钢琴", "upright piano"],
    "bookshelf": ["书架", "书柜", "bookshelf", "books"],
    "window": ["窗", "窗户", "window", "窗帘"],
    "desk": ["书桌", "桌子", "desk", "table"],
    "chair": ["椅子", "凳子", "琴凳", "chair", "bench", "stool"],
    "lamp": ["灯", "台灯", "lamp", "light"],
    "plant": ["植物", "花", "盆栽", "plant", "flower"],
    "painting": ["画", "挂画", "painting", "art"],
    "mirror": ["镜子", "mirror"],
    "clock": ["钟", "时钟", "clock"],
    "metronome": ["节拍器", "metronome"],
    "music_stand": ["谱架", "乐谱架", "music stand"],
    "sheet_music": ["乐谱", "琴谱", "sheet music", "score"],
    "curtain": ["窗帘", "curtain", "drapes"],
    "rug": ["地毯", "rug", "carpet"],
    "sofa": ["沙发", "sofa", "couch"],
}

_LIGHTING_KEYWORDS: Dict[str, List[str]] = {
    "warm_afternoon": ["下午", "午后", "阳光", "afternoon", "sunlight", "warm"],
    "soft_morning": ["早上", "早晨", "morning", "晨光"],
    "evening_warm": ["傍晚", "晚上", "evening", "dusk", "暖光"],
    "night_dim": ["夜晚", "深夜", "night", "dark"],
    "bright_daylight": ["明亮", "bright", "daylight", "日光"],
}

_MOOD_KEYWORDS: Dict[str, List[str]] = {
    "focused_practice": ["练习", "专注", "practice", "focus", "concentrate"],
    "relaxed_conversation": ["聊天", "放松", "对话", "chat", "relax", "conversation"],
    "formal_performance": ["演奏", "表演", "performance", "concert", "formal"],
    "cozy_intimate": ["温馨", "亲密", "cozy", "intimate", "warm"],
    "creative_exploration": ["探索", "创作", "create", "explore", "improvise"],
}

_TIME_KEYWORDS: Dict[str, List[str]] = {
    "morning": ["早上", "早晨", "morning", "AM", "a.m."],
    "afternoon": ["下午", "午后", "afternoon", "noon"],
    "evening": ["傍晚", "晚上", "evening", "dusk", "PM", "p.m."],
    "night": ["夜晚", "深夜", "night", "midnight", "late"],
}


def _match_keywords(text: str, keyword_map: Dict[str, List[str]]) -> List[str]:
    """在 text 中搜索 keyword_map 的匹配项，返回匹配到的 key 列表。"""
    text_lower = text.lower()
    matched: List[str] = []
    for key, keywords in keyword_map.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                matched.append(key)
                break
    return matched


def parse_text_scene(text_description: str, *, user_visible: bool = True) -> AriaScenePerception:
    """
    从文本描述解析场景信息（无 VLM 调用，纯规则）。

    Parameters
    ----------
    text_description : str
        用户/前端提供的场景描述文本（中/英文均可）
    user_visible : bool
        用户是否在场景中可见

    Returns
    -------
    AriaScenePerception
    """
    objects = _match_keywords(text_description, _ROOM_KEYWORDS)
    lightings = _match_keywords(text_description, _LIGHTING_KEYWORDS)
    moods = _match_keywords(text_description, _MOOD_KEYWORDS)
    times = _match_keywords(text_description, _TIME_KEYWORDS)

    return AriaScenePerception(
        objects=objects if objects else [],
        lighting=lightings[0] if lightings else "neutral",
        mood=moods[0] if moods else "neutral",
        time_of_day=times[0] if times else "daytime",
        activity_context=moods[0].replace("_", " ") if moods else "general",
        user_visible=user_visible,
        raw_description=text_description,
    )


# ── VLM Call ──────────────────────────────────────────────────────────────────

async def vlm_scene_describe(
    *,
    image_b64: str,
    vlm_caller: "VLMCaller",
    hint: str = "",
) -> AriaScenePerception:
    """
    调用 VLM 分析场景图片，返回结构化描述。

    Parameters
    ----------
    image_b64 : str
        图片的 base64 编码（JPEG/PNG）
    vlm_caller : VLMCaller
        已注册的 VLM 调用器（符合 obase VLMCaller 协议）
    hint : str
        可选的场景提示（如 "这是一个练琴房"），辅助 VLM 理解

    Returns
    -------
    AriaScenePerception

    Raises
    ------
    RuntimeError
        VLM 调用失败时
    """
    prompt = _VLM_SYSTEM
    if hint:
        prompt += f"\n提示：{hint}"

    try:
        result = await vlm_caller(
            prompt=prompt,
            image_b64=image_b64,
            response_format="json",
        )
    except Exception as e:
        logger.warning("VLM scene describe failed: %s", e)
        raise RuntimeError(f"VLM scene describe failed: {e}") from e

    # Parse JSON from result
    raw_text = result.get("text", "") or result.get("content", "") or ""
    return _parse_vlm_response(raw_text)


def _parse_vlm_response(raw_text: str) -> AriaScenePerception:
    """解析 VLM 返回的 JSON 文本。"""
    # Try to extract JSON from markdown code block or raw text
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw_text)
    json_str = json_match.group(1).strip() if json_match else raw_text.strip()

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        logger.warning("VLM response not valid JSON: %s", raw_text[:200])
        return AriaScenePerception(raw_description=raw_text)

    return AriaScenePerception(
        objects=data.get("objects", []),
        lighting=data.get("lighting", "neutral"),
        mood=data.get("mood", "neutral"),
        time_of_day=data.get("time_of_day", "daytime"),
        activity_context=data.get("activity_context", "general"),
        user_visible=data.get("user_visible", True),
        raw_description=raw_text,
    )
