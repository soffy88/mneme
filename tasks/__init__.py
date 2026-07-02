"""Celery task package."""

# vendor 优先（见 services/__init__）：内核 import 之前把 vendor/ 插到 sys.path 最前。
import os as _os
import sys as _sys

_vendor = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "vendor"
)
if _os.path.isdir(_vendor) and _vendor not in _sys.path:
    _sys.path.insert(0, _vendor)

from .celery_app import celery_app  # noqa: E402  # 必须在 vendor sys.path 注入之后

__all__ = ["celery_app"]
