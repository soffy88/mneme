"""oprim.okx_ws_msg — Subscribe to a single OKX WebSocket channel message."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

_OKX_WS_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"
_OKX_WS_PRIVATE = "wss://ws.okx.com:8443/ws/v5/private"


async def okx_ws_msg(
    channel: str,
    *,
    inst_id: str,
    callback: Callable[[dict[str, Any]], Any],
    timeout: float = 10.0,
    ws_url: str = _OKX_WS_PUBLIC,
) -> None:
    """Subscribe to an OKX WebSocket channel and call *callback* for each data push.

    Connects, sends a subscribe frame, then loops calling *callback* until
    *timeout* seconds elapse or the connection closes.

    Args:
        channel: OKX channel name, e.g. ``"tickers"``, ``"books5"``.
        inst_id: Instrument ID, e.g. ``"BTC-USDT-SWAP"``.
        callback: Callable invoked with the parsed push dict.  May be async.
        timeout: Maximum time to listen before returning.
        ws_url: WebSocket endpoint (override for tests or private channels).

    Raises:
        OkxWsError: Connection refused or subscribe error returned by OKX.
    """
    try:
        import websockets  # noqa: PLC0415
    except ImportError:
        raise OkxWsError("websockets package not installed") from None

    subscribe_msg = json.dumps({
        "op": "subscribe",
        "args": [{"channel": channel, "instId": inst_id}],
    })

    try:
        async with websockets.connect(ws_url, open_timeout=timeout) as ws:
            await ws.send(subscribe_msg)
            deadline = asyncio.get_event_loop().time() + timeout
            while asyncio.get_event_loop().time() < deadline:
                remaining = deadline - asyncio.get_event_loop().time()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, remaining))
                except asyncio.TimeoutError:
                    break
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("event") == "error":
                    raise OkxWsError(f"OKX subscribe error: {msg}")
                if "data" in msg:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(msg)
                    else:
                        callback(msg)
    except OkxWsError:
        raise
    except Exception as exc:
        raise OkxWsError(f"WebSocket error: {exc}") from exc


class OkxWsError(Exception):
    """OKX WebSocket subscription failed."""
