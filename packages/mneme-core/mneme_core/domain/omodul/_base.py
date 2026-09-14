"""omodul 三件套共用基座（platform/3O HELIOS_3O_SPEC_v3_0.md §5）。

mneme-core 是零依赖纯库（pyproject.toml ``dependencies = []``），故用 dataclass
承载 config/input/findings，不引入 pydantic —— 与 oprim/models.py 既有风格一致。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import ClassVar, Optional


@dataclass
class BaseConfig:
    """所有 omodul Config 的基类：声明三件套契约的 ClassVar 部分。

    子类必须覆盖 ``_omodul_name``/``_omodul_version``/``_enabled_pillars``；
    ``_fingerprint_fields`` 仅当 ``"fingerprint" in _enabled_pillars`` 时才需非空。
    """

    _omodul_name: ClassVar[str] = ""
    _omodul_version: ClassVar[str] = ""
    _fingerprint_fields: ClassVar[frozenset[str]] = frozenset()
    _enabled_pillars: ClassVar[frozenset[str]] = frozenset()


def compute_fingerprint(config: BaseConfig, input_hash: str) -> str:
    """sha256(omodul_name + version + config 子集 + input_hash)，供 fingerprint 支柱用。

    只对启用 fingerprint 支柱的 omodul 有意义；调用方须自行保证 input_hash 不含
    真实 PII（服务层先经 anon_ref 等伪名化）。
    """
    subset = {
        k: getattr(config, k)
        for k in sorted(config._fingerprint_fields)
        if hasattr(config, k)
    }
    obj = {
        "omodul_name": config._omodul_name,
        "omodul_version": config._omodul_version,
        "config_subset": subset,
        "input_hash": input_hash,
    }
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def standard_return(
    *,
    findings,
    status: str,
    error: Optional[dict] = None,
    fingerprint: Optional[str] = None,
    decision_trail: Optional[dict] = None,
    report_path=None,
    cost_usd: float = 0.0,
) -> dict:
    """omodul 标准返回结构（§5.1 判定标准 4：status/error 字段必返回）。"""
    return {
        "findings": findings,
        "status": status,
        "error": error,
        "fingerprint": fingerprint,
        "decision_trail": decision_trail,
        "report_path": report_path,
        "cost_usd": cost_usd,
    }
