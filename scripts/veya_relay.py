"""scripts/veya_relay.py — 把宿主 loopback 上的 Veya 网关桥接进 docker 网络。

## 为什么需要它

Veya gateway 是**宿主机进程**，且只 bind `127.0.0.1:8791`。api 容器在 docker
bridge 网络里，`host.docker.internal` 解析到的是宿主网卡地址（实测
`192.168.0.168`），而服务只监听 loopback —— 于是容器内一律
`Connection refused [Errno 111]`（2026-10-03 实测）。

人决策：**不修改 Veya 自己的 listener 地址**。所以本脚本是**新增**一个转发器，
而不是改网关配置。

## 暴露面（重要）

只 bind **docker bridge 网关地址**（默认 `172.22.0.1`，由 `DOCKER_BRIDGE_IP`
或 `--bind` 指定），**不** bind `0.0.0.0`。因此：

- 同一 bridge 上的容器可达（mneme 的 api/worker/beat 正在这个网络）；
- 宿主自己的脚本也可用（宿主拥有该 IP）；
- **局域网与公网不可达** —— 192.168.0.168 / 外部接口上没有这个监听。

## 长期正解

这是权宜之计。真正的解法是把网关本身跑进 docker 网络（或让它显式监听 bridge
地址）。本脚本存在的价值是：**在不动别人项目配置的前提下，让容器能用 LLM**，
并且它是可一键回滚的（停掉单元 + 从 `.env` 去掉 `VEYA_BASE_URL` 的改动）。

## 跑法

```bash
python scripts/veya_relay.py --listen 172.22.0.1:8792 --target 127.0.0.1:8791
```

作为 `systemd --user` 单元运行（见 `deploy/` 下的单元文件模板）。
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys

# 单条连接的上限：转发器是给几条 LLM 连接用的，不是给高并发压测用的。
_MAX_BACKLOG = 32
_RECV_CHUNK = 65536


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(_RECV_CHUNK)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
        pass
    finally:
        try:
            writer.close()
        except Exception:  # noqa: BLE001 — 关连接失败无需再抛
            pass


async def _handle(local_r: asyncio.StreamReader, local_w: asyncio.StreamWriter,
                  target: tuple[str, int]) -> None:
    try:
        remote_r, remote_w = await asyncio.open_connection(*target)
    except OSError as exc:
        local_w.close()
        print(f"relay: 无法连接上游 {target}: {exc}", file=sys.stderr, flush=True)
        return
    # 双向转发：任一方向结束就整体收掉，避免半开连接堆积
    await asyncio.gather(
        _pipe(local_r, remote_w),
        _pipe(remote_r, local_w),
        return_exceptions=True,
    )
    for w in (local_w, remote_w):
        try:
            w.close()
        except Exception:  # noqa: BLE001
            pass


async def serve(listen: tuple[str, int], target: tuple[str, int]) -> None:
    server = await asyncio.start_server(
        lambda r, w: _handle(r, w, target),  # type: ignore[misc]
        host=listen[0],
        port=listen[1],
        backlog=_MAX_BACKLOG,
        limit=_RECV_CHUNK,
    )
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets or [])
    print(f"relay: {addrs} -> {target[0]}:{target[1]}", flush=True)

    stop = asyncio.get_running_loop().create_future()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(
                sig, lambda: stop.done() or stop.set_result(None)
            )
        except NotImplementedError:  # pragma: no cover — 非 POSIX
            pass
    async with server:
        await stop


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--listen",
        default="172.22.0.1:8792",
        help="本地监听地址。**只填 docker bridge 网关地址**，别填 0.0.0.0",
    )
    parser.add_argument("--target", default="127.0.0.1:8791", help="上游（Veya）地址")
    args = parser.parse_args()

    def _split(v: str) -> tuple[str, int]:
        host, _, port = v.rpartition(":")
        if not host or not port.isdigit():
            raise SystemExit(f"地址格式应为 host:port，收到 {v!r}")
        return host, int(port)

    listen = _split(args.listen)
    if listen[0] == "0.0.0.0":
        raise SystemExit(
            "拒绝 bind 0.0.0.0：这会把 LLM 网关暴露到局域网/公网。"
            "只填 docker bridge 网关地址。"
        )
    try:
        asyncio.run(serve(listen, _split(args.target)))
    except KeyboardInterrupt:  # pragma: no cover
        pass


if __name__ == "__main__":
    main()