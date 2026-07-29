"""
Aria Perception Service — 场景感知缓存服务
==========================================
services/aria_perception.py

管理 Aria 的场景感知状态：
  - 缓存同一 room_key 的场景描述（避免重复 VLM 调用）
  - 支持文本描述和 VLM 图片分析两种入口
  - 提供 Director 可消费的 perception 字典

缓存策略：
  - 内存 LRU 缓存（默认 16 条）
  - TTL 10 分钟（同一场景不会频繁变化）
  - VLM 调用失败时降级到文本解析
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Any, Dict, Optional, TYPE_CHECKING

from vendor.oprim.vlm_scene import (
    AriaScenePerception,
    parse_text_scene,
    vlm_scene_describe,
)

if TYPE_CHECKING:
    from obase.provider_registry import VLMCaller

logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────────────────────────

_CACHE_MAX_SIZE = 16
_CACHE_TTL_SECONDS = 600  # 10 minutes


# ── Cache Entry ───────────────────────────────────────────────────────────────

class _CacheEntry:
    __slots__ = ("perception", "created_at", "source")

    def __init__(self, perception: AriaScenePerception, source: str):
        self.perception = perception
        self.created_at = time.monotonic()
        self.source = source

    def is_fresh(self) -> bool:
        return (time.monotonic() - self.created_at) < _CACHE_TTL_SECONDS


# ── Perception Manager ────────────────────────────────────────────────────────

class AriaPerceptionManager:
    """
    管理 Aria 的场景感知状态。

    用法::

        mgr = AriaPerceptionManager()

        # 文本描述入口（无 VLM 调用）
        perception = await mgr.update_from_text(
            room_key="music_room_01",
            text_description="阳光透过窗帘照在三角钢琴上，旁边有书架和节拍器"
        )

        # VLM 图片入口
        perception = await mgr.update_from_image(
            room_key="music_room_01",
            image_b64="...",
            hint="练琴房"
        )

        # 获取缓存（Director 调用）
        cached = mgr.get(room_key="music_room_01")
    """

    def __init__(self, *, vlm_caller: Optional["VLMCaller"] = None):
        self._cache: "OrderedDict[str, _CacheEntry]" = OrderedDict()
        self._vlm_caller = vlm_caller
        self._lock = asyncio.Lock()

    def set_vlm_caller(self, vlm_caller: "VLMCaller") -> None:
        self._vlm_caller = vlm_caller

    def get(self, *, room_key: str) -> Optional[Dict[str, Any]]:
        """获取缓存的场景感知（Director 用）。返回 None 表示无缓存。"""
        entry = self._cache.get(room_key)
        if entry is None or not entry.is_fresh():
            if entry is not None:
                # Expired — remove
                del self._cache[room_key]
            return None
        # Move to end (LRU)
        self._cache.move_to_end(room_key)
        return entry.perception.to_dict()

    def get_brief(self, *, room_key: str) -> str:
        """获取简短描述（用于 Director prompt 嵌入）。"""
        entry = self._cache.get(room_key)
        if entry is None or not entry.is_fresh():
            return ""
        self._cache.move_to_end(room_key)
        return entry.perception.to_director_brief()

    async def update_from_text(
        self,
        *,
        room_key: str,
        text_description: str,
        user_visible: bool = True,
    ) -> Dict[str, Any]:
        """
        从文本描述更新场景感知（无 VLM 调用，纯规则解析）。

        Parameters
        ----------
        room_key : str
            房间标识（同一房间共享缓存）
        text_description : str
            场景描述文本
        user_visible : bool
            用户是否可见

        Returns
        -------
        dict — AriaScenePerception 的字典形式
        """
        async with self._lock:
            perception = parse_text_scene(text_description, user_visible=user_visible)
            self._put(room_key, _CacheEntry(perception, source="text"))
            logger.info(
                "aria_perception: updated from text room=%s objects=%s",
                room_key, perception.objects,
            )
            return perception.to_dict()

    async def update_from_image(
        self,
        *,
        room_key: str,
        image_b64: str,
        hint: str = "",
        fallback_text: str = "",
    ) -> Dict[str, Any]:
        """
        从图片更新场景感知（VLM 调用，失败降级到文本）。

        Parameters
        ----------
        room_key : str
            房间标识
        image_b64 : str
            图片 base64 编码
        hint : str
            场景提示
        fallback_text : str
            VLM 失败时的降级文本描述

        Returns
        -------
        dict — AriaScenePerception 的字典形式
        """
        if self._vlm_caller is None:
            logger.warning("aria_perception: no VLM caller, falling back to text")
            return await self.update_from_text(
                room_key=room_key,
                text_description=fallback_text or hint,
            )

        try:
            async with self._lock:
                perception = await vlm_scene_describe(
                    image_b64=image_b64,
                    vlm_caller=self._vlm_caller,
                    hint=hint,
                )
                self._put(room_key, _CacheEntry(perception, source="vlm"))
                logger.info(
                    "aria_perception: updated from VLM room=%s objects=%s",
                    room_key, perception.objects,
                )
                return perception.to_dict()
        except Exception as e:
            logger.warning("aria_perception: VLM failed, falling back: %s", e)
            if fallback_text:
                return await self.update_from_text(
                    room_key=room_key,
                    text_description=fallback_text,
                )
            # No fallback — return empty perception
            empty = AriaScenePerception(raw_description=f"VLM failed: {e}")
            return empty.to_dict()

    def invalidate(self, *, room_key: str) -> bool:
        """手动清除指定房间缓存。返回是否命中。"""
        if room_key in self._cache:
            del self._cache[room_key]
            return True
        return False

    def clear(self) -> int:
        """清除所有缓存，返回清除数量。"""
        n = len(self._cache)
        self._cache.clear()
        return n

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    # ── Internal ──

    def _put(self, room_key: str, entry: _CacheEntry) -> None:
        """写入缓存，必要时驱逐最旧条目。"""
        if room_key in self._cache:
            del self._cache[room_key]
        elif len(self._cache) >= _CACHE_MAX_SIZE:
            self._cache.popitem(last=False)  # Evict oldest
        self._cache[room_key] = entry


# ── Module-level singleton ─────────────────────────────────────────────────────

_manager: Optional[AriaPerceptionManager] = None


def get_perception_manager() -> AriaPerceptionManager:
    """获取全局 PerceptionManager 单例。"""
    global _manager
    if _manager is None:
        _manager = AriaPerceptionManager()
    return _manager


def reset_perception_manager() -> None:
    """重置全局单例（测试用）。"""
    global _manager
    _manager = None
