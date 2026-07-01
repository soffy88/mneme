"""Minimal env-var config for oprim knowledge sub-packages."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_store: dict[str, Any] = {}


def load_config(path: Path | None = None) -> dict[str, Any]:
    global _store
    data: dict[str, Any] = {}
    if path is not None and Path(path).exists():
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    data.update(os.environ)
    _store = data
    return _store


def get(key: str, default: Any = None) -> Any:
    return _store.get(key, os.environ.get(key, default))


# Module-level singleton usable as `cfg.get(...)` and `cfg.load_config(...)`
cfg = type("_Cfg", (), {"get": staticmethod(get), "load_config": staticmethod(load_config)})()
