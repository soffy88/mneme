"""离线数据文件定位与只读 SQLite 连接（ECDICT / chinese-poetry / chinese-xinhua 成语）。

数据不进 git：由 scripts/ask_data/fetch_and_build.py 下载（固定 commit + sha256）并构建到
``MNEME_ASK_DATA_DIR``（默认 <repo>/data/external/ask_providers）。文件缺失时各 provider 静默降级
（返回 None），绝不抛到求解主流程。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
_lock = threading.Lock()
_conns: dict[str, Optional[sqlite3.Connection]] = {}


def data_dir() -> Path:
    return Path(os.environ.get("MNEME_ASK_DATA_DIR") or (_ROOT / "data" / "external" / "ask_providers"))


def connect(name: str) -> Optional[sqlite3.Connection]:
    """只读打开 <data_dir>/<name>.sqlite；不存在返回 None（结果缓存，进程内复用）。"""
    with _lock:
        if name in _conns and _conns[name] is not None:
            return _conns[name]
        path = data_dir() / f"{name}.sqlite"
        if not path.exists():
            return None
        conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _conns[name] = conn
        return conn


def reset_cache() -> None:
    """测试用：切换 MNEME_ASK_DATA_DIR 后清掉缓存的连接。"""
    with _lock:
        for c in _conns.values():
            if c is not None:
                c.close()
        _conns.clear()
