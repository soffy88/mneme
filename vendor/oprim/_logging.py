"""Minimal structured logging for oprim knowledge sub-packages (stdlib only)."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

_logger = logging.getLogger("oprim")


class _Log:
    def info(self, event: str, **kwargs: Any) -> None:
        _logger.info(json.dumps({"event": event, "ts": time.time(), **kwargs}))

    def warning(self, event: str, **kwargs: Any) -> None:
        _logger.warning(json.dumps({"event": event, "ts": time.time(), **kwargs}))

    def error(self, event: str, **kwargs: Any) -> None:
        _logger.error(json.dumps({"event": event, "ts": time.time(), **kwargs}))

    def emit(self, event: str, **kwargs: Any) -> None:
        self.info(event, **kwargs)

    def setup_logging(self, level: str = "INFO") -> None:
        logging.basicConfig(
            level=getattr(logging, level.upper(), logging.INFO),
            format="%(message)s",
        )
        _logger.setLevel(getattr(logging, level.upper(), logging.INFO))


log = _Log()
