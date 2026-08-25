"""The offline JSONL adapter preserves the shadow comparator contract."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

MOAT_DIR = str(Path(__file__).resolve().parents[1] / "scripts" / "moat_eval")
if MOAT_DIR not in sys.path:
    sys.path.insert(0, MOAT_DIR)

from shadow_registry_eval import load_predictions, run  # noqa: E402

BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _row(model_id: str, day: int, probability: float, actual: bool) -> dict:
    return {
        "model_id": model_id,
        "occurred_at": (BASE + timedelta(days=day)).isoformat(),
        "probability": probability,
        "actual": actual,
        "kc_id": "ku-1",
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )


def test_jsonl_adapter_runs_registry_aligned_report(tmp_path: Path) -> None:
    candidate_path = tmp_path / "candidate.jsonl"
    baseline_path = tmp_path / "baseline.jsonl"
    _write_jsonl(
        candidate_path,
        [_row("challenger-1", 6, 0.9, True), _row("challenger-1", 7, 0.1, False)],
    )
    _write_jsonl(
        baseline_path,
        [_row("kernel-1", 6, 0.6, True), _row("kernel-1", 7, 0.4, False)],
    )

    result = run(
        [
            "--predictions",
            str(candidate_path),
            "--baseline",
            str(baseline_path),
            "--model-id",
            "challenger-1",
            "--baseline-model-id",
            "kernel-1",
            "--train-start",
            "2026-01-01T00:00:00Z",
            "--train-end",
            "2026-01-06T00:00:00Z",
            "--eval-start",
            "2026-01-06T00:00:00Z",
            "--eval-end",
            "2026-01-15T00:00:00Z",
            "--as-of",
            "2026-01-20T00:00:00Z",
        ]
    )

    assert result["mode"] == "shadow_only"
    assert result["candidate"]["n"] == 2
    assert result["baseline"]["model_id"] == "kernel-1"


def test_jsonl_adapter_rejects_non_boolean_actual(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    row = _row("challenger-1", 6, 0.5, True)
    row["actual"] = 1
    _write_jsonl(path, [row])

    with pytest.raises(ValueError, match="invalid prediction"):
        load_predictions(path)
