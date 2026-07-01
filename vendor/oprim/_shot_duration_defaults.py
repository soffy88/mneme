"""Pure constants for shot duration defaults and transition rules."""
from __future__ import annotations

SHOT_DURATION_DEFAULTS: dict = {
    "closeup": 5.0,
    "action_medium": (5.0, 10.0),
    "info": (10.0, 15.0),
}

TRANSITION_RULES: dict[str, str] = {
    "same_scene_near": "hard",      # 同场景近景别硬切
    "cross_scene": "dissolve",      # 跨场景叠化 ≤0.5s
    "emotion_shift": "flash",       # 情绪转折闪白闪黑
}
