"""rag_client — Stratum 检索客户端（HTTP，C4/W2C）。

FC-6 分类筛判定（书面记录）：任务原文写"obase.rag"，但 `obase` 是纯 pip 装的跨项目
共享包（实测 `obase.db.__file__` 落在 `site-packages/obase/`，本仓库无本地 `obase/`
目录）——改共享包需要跨项目发布协调，而本客户端又绑定 Stratum 的具体契约（登录/
检索端点形状、`mode=strict|augmented` 等 Stratum 特有概念，不是通用检索抽象）。
故不进共享 `obase` 包，落 `services/rag_client.py`（Mneme 本地，Layer4）。若未来
多个项目都要接 Stratum，再抽取共享层。

定调：只 HTTP 调既有 Stratum 服务，不把 Stratum 的栈拉进 Mneme。

前置（C4-0 已查证并处理）：
  - mneme-api-1 已 `docker network connect stratum-net`，经
    `http://stratum-api:9302` 直连（Stratum 只在宿主机 127.0.0.1 暴露端口，
    host.docker.internal 够不到，故走 docker network，不改 Stratum 自己的
    compose 配置）。
  - Stratum 无服务账号机制（只有用户登录），已注册专用 service 账号
    `mneme-rag-service@sxueji.com`（凭据存 .env 的
    STRATUM_SERVICE_EMAIL/STRATUM_SERVICE_PASSWORD，非硬编码）。

用途：为 chat/tutor loop 提供内容素材召回（呈现层）。

红线：RAG 召回只作素材，**不进门控判据**——本模块不得 import 任何门控/判分模块
（mastery_gate/gate_store/grade/verdict_guard/cognitive_service）。
`tests/test_rag_client_no_gating_coupling.py` 静态断言此边界（对照 C3 persona /
C5 memory 同一模式）。

fail-safe：无凭据/网络失败/非 2xx 一律返回空列表，不阻断调用方——RAG 缺失不该
打断对话。
"""

from __future__ import annotations

import os
import time
from typing import Optional

import httpx

_token_cache: dict[str, object] = {}


def _base_url() -> str:
    return os.environ.get("STRATUM_BASE_URL", "http://stratum-api:9302").rstrip("/")


async def _get_token() -> Optional[str]:
    """懒登录：缓存的 token 还有效（留 30s 余量）就用；否则用 service 账号现登录。

    未配置凭据 → None（调用方据此静默降级，不报错）。
    """
    now = time.time()
    cached_token = _token_cache.get("token")
    cached_expiry = _token_cache.get("expires_at")
    if (
        cached_token
        and isinstance(cached_expiry, (int, float))
        and cached_expiry > now + 30
    ):
        return str(cached_token)

    email = os.environ.get("STRATUM_SERVICE_EMAIL")
    password = os.environ.get("STRATUM_SERVICE_PASSWORD")
    if not email or not password:
        return None

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_base_url()}/api/auth/login",
                json={"email_or_username": email, "password": password},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None

    token = data.get("access_token")
    if not token:
        return None
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + data.get("expires_in", 900)
    return str(token)


async def search(query: str, *, top_k: int = 5) -> list[dict]:
    """检索 Stratum 知识库，返回呈现层素材列表（不含判分/门控相关信息）。

    不可用（无凭据/网络失败/非 2xx）→ 返回空列表，不阻断调用方。
    """
    token = await _get_token()
    if token is None:
        return []

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{_base_url()}/api/search",
                json={"query": query, "top_k": top_k},
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []

    return [
        {
            "id": item["id"],
            "title": item["title"],
            "highlight": item.get("highlight"),
            "score": item["score"],
        }
        for item in data.get("results", [])
    ]
