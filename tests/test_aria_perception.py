"""Aria P1 Perception — VLM 场景感知 + Director 集成 单元测试。"""

from __future__ import annotations

import pytest

from oprim.vlm_scene import (
    AriaScenePerception,
    parse_text_scene,
    _parse_vlm_response,
)
from services.aria_perception import (
    AriaPerceptionManager,
    get_perception_manager,
    reset_perception_manager,
)
from services.aria_director import (
    AriaDirectorInput,
    AriaDirectorState,
    AriaPerception,
    _heuristic,
    _perception_nudge,
)


# ── oprim/vlm_scene.py ────────────────────────────────────────────────────────


class TestParseTextScene:
    def test_piano_room_objects(self):
        p = parse_text_scene("阳光照在三角钢琴上，旁边有书架和节拍器")
        assert "grand_piano" in p.objects
        assert "bookshelf" in p.objects
        assert "metronome" in p.objects
        assert p.lighting == "warm_afternoon"

    def test_evening_relax(self):
        p = parse_text_scene("晚上在沙发上放松聊天")
        assert "sofa" in p.objects
        assert p.time_of_day == "evening"
        assert p.mood == "relaxed_conversation"

    def test_empty_description(self):
        p = parse_text_scene("")
        assert p.objects == []
        assert p.lighting == "neutral"
        assert p.mood == "neutral"

    def test_bilingual_keywords(self):
        p = parse_text_scene("A grand piano with sheet music under bright daylight")
        assert "grand_piano" in p.objects
        assert "sheet_music" in p.objects
        assert p.lighting == "bright_daylight"

    def test_user_visible_default(self):
        p = parse_text_scene("钢琴")
        assert p.user_visible is True

    def test_user_visible_override(self):
        p = parse_text_scene("钢琴", user_visible=False)
        assert p.user_visible is False


class TestAriaScenePerception:
    def test_to_dict(self):
        p = AriaScenePerception(
            objects=["grand_piano", "bookshelf"],
            lighting="warm_afternoon",
            mood="focused_practice",
        )
        d = p.to_dict()
        assert d["objects"] == ["grand_piano", "bookshelf"]
        assert d["lighting"] == "warm_afternoon"
        assert "raw_description" in d

    def test_to_director_brief_full(self):
        p = AriaScenePerception(
            objects=["grand_piano"],
            lighting="warm_afternoon",
            mood="focused_practice",
            time_of_day="afternoon",
        )
        brief = p.to_director_brief()
        assert "grand_piano" in brief
        assert "warm_afternoon" in brief
        assert "focused_practice" in brief

    def test_to_director_brief_neutral(self):
        p = AriaScenePerception()
        brief = p.to_director_brief()
        assert brief == "普通房间场景"


class TestParseVLMResponse:
    def test_valid_json(self):
        raw = '{"objects": ["piano", "chair"], "lighting": "soft", "mood": "calm"}'
        p = _parse_vlm_response(raw)
        assert p.objects == ["piano", "chair"]
        assert p.lighting == "soft"

    def test_markdown_code_block(self):
        raw = '```json\n{"objects": ["desk"], "mood": "focused"}\n```'
        p = _parse_vlm_response(raw)
        assert p.objects == ["desk"]
        assert p.mood == "focused"

    def test_invalid_json_graceful(self):
        raw = "Sorry, I cannot analyze this image."
        p = _parse_vlm_response(raw)
        assert p.objects == []
        assert p.lighting == "neutral"
        assert p.raw_description == raw

    def test_missing_fields_default(self):
        raw = '{"objects": ["lamp"]}'
        p = _parse_vlm_response(raw)
        assert p.objects == ["lamp"]
        assert p.lighting == "neutral"
        assert p.time_of_day == "daytime"


# ── services/aria_perception.py ───────────────────────────────────────────────


class TestPerceptionManager:
    def setup_method(self):
        reset_perception_manager()

    @pytest.mark.asyncio
    async def test_update_from_text_and_get(self):
        mgr = AriaPerceptionManager()
        result = await mgr.update_from_text(
            room_key="music_room",
            text_description="三角钢琴旁边有书架",
        )
        assert "grand_piano" in result["objects"]
        assert "bookshelf" in result["objects"]

        cached = mgr.get(room_key="music_room")
        assert cached is not None
        assert cached["objects"] == result["objects"]

    @pytest.mark.asyncio
    async def test_cache_miss(self):
        mgr = AriaPerceptionManager()
        assert mgr.get(room_key="nonexistent") is None

    @pytest.mark.asyncio
    async def test_cache_invalidate(self):
        mgr = AriaPerceptionManager()
        await mgr.update_from_text(room_key="r1", text_description="钢琴")
        assert mgr.get(room_key="r1") is not None
        assert mgr.invalidate(room_key="r1") is True
        assert mgr.get(room_key="r1") is None

    @pytest.mark.asyncio
    async def test_cache_clear(self):
        mgr = AriaPerceptionManager()
        await mgr.update_from_text(room_key="r1", text_description="钢琴")
        await mgr.update_from_text(room_key="r2", text_description="书架")
        assert mgr.cache_size == 2
        assert mgr.clear() == 2
        assert mgr.cache_size == 0

    @pytest.mark.asyncio
    async def test_get_brief(self):
        mgr = AriaPerceptionManager()
        await mgr.update_from_text(room_key="r1", text_description="晚上三角钢琴")
        brief = mgr.get_brief(room_key="r1")
        assert "grand_piano" in brief
        assert "evening" in brief

    @pytest.mark.asyncio
    async def test_get_brief_empty(self):
        mgr = AriaPerceptionManager()
        assert mgr.get_brief(room_key="missing") == ""

    @pytest.mark.asyncio
    async def test_update_from_image_no_vlm_fallback(self):
        mgr = AriaPerceptionManager()
        result = await mgr.update_from_image(
            room_key="r1",
            image_b64="fake_base64",
            fallback_text="钢琴和书架",
        )
        # Falls back to text parsing since no VLM caller
        assert "grand_piano" in result["objects"] or "bookshelf" in result["objects"]

    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        mgr = AriaPerceptionManager()
        # Fill beyond cache size (16)
        for i in range(20):
            await mgr.update_from_text(room_key=f"r{i}", text_description=f"房间{i}")
        # Oldest entries should be evicted
        assert mgr.get(room_key="r0") is None
        assert mgr.get(room_key="r19") is not None

    def test_singleton(self):
        reset_perception_manager()
        m1 = get_perception_manager()
        m2 = get_perception_manager()
        assert m1 is m2
        reset_perception_manager()


# ── Director integration ──────────────────────────────────────────────────────


class TestDirectorPerception:
    def test_perception_nudge_piano(self):
        inp = AriaDirectorInput(
            event="tick",
            state=AriaDirectorState(
                perception=AriaPerception(
                    objects=["grand_piano", "bookshelf"],
                ),
            ),
        )
        assert _perception_nudge(inp) == "play_piano"

    def test_perception_nudge_sheet_music(self):
        inp = AriaDirectorInput(
            event="tick",
            state=AriaDirectorState(
                perception=AriaPerception(objects=["sheet_music"]),
            ),
        )
        assert _perception_nudge(inp) == "play_piano"

    def test_perception_nudge_relaxed_mood(self):
        inp = AriaDirectorInput(
            event="tick",
            state=AriaDirectorState(
                perception=AriaPerception(mood="relaxed_conversation"),
            ),
        )
        assert _perception_nudge(inp) == "speak"

    def test_perception_nudge_none(self):
        inp = AriaDirectorInput(event="tick")
        assert _perception_nudge(inp) is None

    def test_heuristic_autonomous_with_piano_perception(self):
        from unittest.mock import patch

        inp = AriaDirectorInput(
            event="tick",
            state=AriaDirectorState(
                mode="playing",
                perception=AriaPerception(objects=["grand_piano"]),
            ),
        )
        # 固定随机数避免 40% 概率的 autonomous_speak 干扰
        with patch("services.aria_director.random.random", return_value=0.9):
            out = _heuristic(inp)
        assert out.action == "play_piano"
        assert out.perception_brief != ""
        assert "grand_piano" in out.perception_brief

    def test_heuristic_wake_evening_perception(self):
        inp = AriaDirectorInput(
            event="wake",
            state=AriaDirectorState(
                perception=AriaPerception(time_of_day="evening"),
            ),
        )
        out = _heuristic(inp)
        assert "evening" in (out.utterance or "").lower()

    def test_heuristic_wake_piano_perception(self):
        inp = AriaDirectorInput(
            event="wake",
            state=AriaDirectorState(
                perception=AriaPerception(objects=["grand_piano"]),
            ),
        )
        out = _heuristic(inp)
        assert "piano" in (out.utterance or "").lower()

    def test_perception_brief_in_output(self):
        inp = AriaDirectorInput(
            event="tick",
            state=AriaDirectorState(
                perception=AriaPerception(
                    objects=["grand_piano"],
                    lighting="warm_afternoon",
                ),
            ),
        )
        out = _heuristic(inp)
        assert "grand_piano" in out.perception_brief
        assert "warm_afternoon" in out.perception_brief

    def test_no_perception_still_works(self):
        """无 perception 时 Director 仍正常工作（向后兼容）。"""
        from unittest.mock import patch

        inp = AriaDirectorInput(event="tick")
        with patch("services.aria_director.random.random", return_value=0.9):
            out = _heuristic(inp)
        assert out.action == "play_piano"
        assert out.perception_brief == ""


# ── AriaPerception model ──────────────────────────────────────────────────────


class TestAriaPerceptionModel:
    def test_brief_empty(self):
        p = AriaPerception()
        assert p.brief() == ""

    def test_brief_with_objects(self):
        p = AriaPerception(
            objects=["grand_piano", "bookshelf"],
            lighting="warm_afternoon",
            mood="focused_practice",
        )
        b = p.brief()
        assert "grand_piano" in b
        assert "bookshelf" in b
        assert "warm_afternoon" in b

    def test_roundtrip_dict(self):
        p = AriaPerception(
            objects=["desk", "lamp"],
            time_of_day="evening",
        )
        d = p.model_dump()
        p2 = AriaPerception(**d)
        assert p2.objects == p.objects
        assert p2.time_of_day == p.time_of_day
