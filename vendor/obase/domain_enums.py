"""领域枚举（obase）——避免 oskill/oprim 为 ORM 标签反向 import services.models。

``services.models`` 再 re-export 同名符号，保证 Alembic/ORM 与历史 import 路径不变。
"""

from __future__ import annotations

import enum


class ErrorType(str, enum.Enum):
    conceptual = "conceptual"
    transfer = "transfer"
    careless = "careless"
    logic_break = "logic_break"
    dontknow = "dontknow"
