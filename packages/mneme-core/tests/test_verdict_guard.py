"""Tests for verdict_guard — the most critical guardrail."""
import pytest
from mneme_core.service.verdict_guard import enforce, GuardRejection

def test_valid_deterministic():
    enforce("deterministic", None, origin="core")  # should not raise

def test_valid_llm_verified():
    enforce("llm_verified", "ref-123", origin="agent")  # should not raise

def test_invalid_verdict_source():
    with pytest.raises(GuardRejection):
        enforce("magic", None)

def test_llm_verified_needs_evidence():
    """llm_verified without evidence_ref MUST be rejected."""
    with pytest.raises(GuardRejection):
        enforce("llm_verified", None)

def test_llm_verified_empty_evidence():
    with pytest.raises(GuardRejection):
        enforce("llm_verified", "")

def test_agent_cannot_forge_deterministic():
    """origin=agent + deterministic MUST be rejected."""
    with pytest.raises(GuardRejection):
        enforce("deterministic", None, origin="agent")
