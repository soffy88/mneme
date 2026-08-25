"""Run the registry-aligned shadow comparator on prediction JSONL files.

The command is intentionally offline: it consumes predictions made by an
external adapter and emits metrics only.  It does not read the student
database, persist an evaluation run, or activate a model.

Example::

    python scripts/moat_eval/shadow_registry_eval.py \
      --predictions candidate.jsonl --baseline kernel.jsonl \
      --model-id dkt-2026-08 --baseline-model-id kernel-v1 \
      --train-start 2026-01-01T00:00:00Z --train-end 2026-07-01T00:00:00Z \
      --eval-start 2026-07-01T00:00:00Z --eval-end 2026-08-01T00:00:00Z \
      --as-of 2026-08-02T00:00:00Z
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from services.shadow_evaluation import ShadowPrediction, shadow_evaluation_report


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 datetime: {value}") from exc


def _row_to_prediction(row: dict[str, Any], *, path: Path, line_number: int) -> ShadowPrediction:
    actual = row.get("actual")
    if not isinstance(actual, bool):
        raise ValueError(f"{path}:{line_number}: actual must be a JSON boolean")
    student_id = row.get("student_id")
    return ShadowPrediction(
        model_id=str(row["model_id"]),
        occurred_at=_parse_datetime(str(row["occurred_at"])),
        probability=float(row["probability"]),
        actual=actual,
        student_id=UUID(student_id) if student_id is not None else None,
        kc_id=str(row["kc_id"]) if row.get("kc_id") is not None else None,
        received_at=(
            _parse_datetime(str(row["received_at"]))
            if row.get("received_at") is not None
            else None
        ),
        event_id=UUID(row["event_id"]) if row.get("event_id") is not None else None,
    )


def load_predictions(path: str | Path) -> list[ShadowPrediction]:
    """Load one prediction per non-empty JSONL line without exposing row data."""

    source = Path(path)
    predictions: list[ShadowPrediction] = []
    with source.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{source}:{line_number}: invalid JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{source}:{line_number}: row must be an object")
            try:
                predictions.append(
                    _row_to_prediction(row, path=source, line_number=line_number)
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{source}:{line_number}: invalid prediction") from exc
    return predictions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", required=True, help="candidate JSONL")
    parser.add_argument("--baseline", help="optional baseline JSONL")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--baseline-model-id", default="baseline")
    for name in ("train-start", "train-end", "eval-start", "eval-end", "as-of"):
        parser.add_argument(f"--{name}", required=True)
    return parser


def run(argv: Sequence[str] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    candidate = load_predictions(args.predictions)
    baseline = load_predictions(args.baseline) if args.baseline else None
    return shadow_evaluation_report(
        candidate,
        model_id=args.model_id,
        train_start=_parse_datetime(args.train_start),
        train_end=_parse_datetime(args.train_end),
        eval_start=_parse_datetime(args.eval_start),
        eval_end=_parse_datetime(args.eval_end),
        as_of=_parse_datetime(args.as_of),
        baseline=baseline,
        baseline_model_id=args.baseline_model_id if baseline is not None else None,
    )


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
