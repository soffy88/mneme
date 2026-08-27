"""Hard boundary between real, demo, test, and synthetic records."""

from __future__ import annotations

from enum import Enum
from collections.abc import Mapping
from typing import Any


class UserDataClass(str, Enum):
    REAL = "REAL"
    DEMO = "DEMO"
    TEST = "TEST"
    SYNTHETIC = "SYNTHETIC"


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def classify_user_data(item: Any) -> UserDataClass:
    metadata = _value(item, "metadata", {}) or {}
    if not isinstance(metadata, Mapping):
        metadata = {}
    provenance = _value(item, "provenance", None)
    provenance_metadata = _value(provenance, "metadata", {}) or {}
    if isinstance(provenance_metadata, Mapping):
        metadata = {**provenance_metadata, **metadata}
    if _value(item, "synthetic", False) or metadata.get("synthetic") is True:
        return UserDataClass.SYNTHETIC
    if metadata.get("demo") is True or _value(item, "demo", False):
        return UserDataClass.DEMO
    if metadata.get("test") is True or _value(item, "test", False):
        return UserDataClass.TEST
    return UserDataClass.REAL


def production_analytics_allowed(item: Any) -> bool:
    return classify_user_data(item) == UserDataClass.REAL


__all__ = ["UserDataClass", "classify_user_data", "production_analytics_allowed"]
