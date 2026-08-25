"""Tests for Aria Brain (Phase 3 autonomous behavior)."""

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from services.aria_brain import AriaBrain, BrainConfig, BrainState


@pytest.fixture
def sent_commands() -> list[dict]:
    return []


@pytest.fixture
def brain(sent_commands: list[dict]) -> AriaBrain:
    async def send_fn(cmd: dict) -> None:
        sent_commands.append(cmd)

    return AriaBrain(
        student_id="test-student",
        send_fn=send_fn,
        config=BrainConfig(idle_tick_s=0.1, silence_timeout_s=0.2),
    )


def _mock_director_output(**overrides):
    """Create a mock AriaDirectorOutput with tiny hold for fast tests."""
    out = MagicMock()
    out.action = overrides.get("action", "play_piano")
    out.utterance = overrides.get("utterance", "")
    out.emotion = overrides.get("emotion", "focused")
    out.hold_ms = overrides.get("hold_ms", 50)  # tiny for fast test loops
    out.source = overrides.get("source", "llm")
    return out


class TestBrainStateMachine:
    def test_initial_state_idle(self, brain: AriaBrain):
        assert brain.state == BrainState.IDLE

    @pytest.mark.asyncio
    async def test_user_entered_greeting(self, brain: AriaBrain, sent_commands: list[dict]):
        """User entering triggers a greeting."""
        with patch("services.aria_director.direct", new_callable=AsyncMock,
                   return_value=_mock_director_output()):
            await brain.start()
            await brain.push_event("user_entered")
            await asyncio.sleep(0.4)
            await brain.stop()

        greetings = [c for c in sent_commands if c.get("source") == "brain_greeting"]
        assert len(greetings) >= 1
        assert greetings[0]["action"] == "look_at_user"
        assert "hello" in greetings[0]["utterance"].lower()

    @pytest.mark.asyncio
    async def test_heuristic_fallback_play(self, brain: AriaBrain, sent_commands: list[dict]):
        """When Director LLM fails, heuristic fallback plays piano."""
        with patch("services.aria_director.direct", new_callable=AsyncMock,
                   side_effect=Exception("LLM down")):
            await brain.start()
            await asyncio.sleep(0.5)
            await brain.stop()

        heuristic = [c for c in sent_commands if c.get("source") == "brain_heuristic"]
        assert len(heuristic) >= 1

    @pytest.mark.asyncio
    async def test_user_spoke_triggers_response(self, brain: AriaBrain, sent_commands: list[dict]):
        """User speaking triggers a Director response."""
        mock_out = _mock_director_output(
            action="speak", utterance="Hello there!", emotion="happy", hold_ms=50
        )
        with patch("services.aria_director.direct", new_callable=AsyncMock,
                   return_value=mock_out):
            await brain.start()
            await brain.push_event("user_spoke", "Hi Aria!")
            await asyncio.sleep(0.5)
            await brain.stop()

        responses = [c for c in sent_commands if c.get("utterance") == "Hello there!"]
        assert len(responses) >= 1

    @pytest.mark.asyncio
    async def test_stop_cancels_loop(self, brain: AriaBrain):
        """Stopping the brain cancels the loop cleanly."""
        with patch("services.aria_director.direct", new_callable=AsyncMock,
                   return_value=_mock_director_output()):
            await brain.start()
            assert brain._task is not None
            await brain.stop()
            assert brain._task.cancelled() or brain._task.done()

    @pytest.mark.asyncio
    async def test_history_accumulates(self, brain: AriaBrain):
        """User messages accumulate in history via _decide."""
        mock_out = _mock_director_output(action="speak", utterance="Response", hold_ms=50)
        with patch("services.aria_director.direct", new_callable=AsyncMock,
                   return_value=mock_out):
            # Call _decide directly (deterministic, no loop timing)
            from services.aria_brain import BrainEvent

            await brain._decide(BrainEvent(kind="user_spoke", text="First message"))
            await brain._decide(BrainEvent(kind="user_spoke", text="Second message"))

        user_msgs = [h for h in brain._history if h["role"] == "user"]
        assert len(user_msgs) == 2
        assert user_msgs[0]["content"] == "First message"
        assert user_msgs[1]["content"] == "Second message"
