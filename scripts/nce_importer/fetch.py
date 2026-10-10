"""HTTP resource fetching: fetch → validate → hash.

Network failures are tracked per resource and reported as RESOURCE_UNAVAILABLE;
they are never silently turned into a PASS.
"""

import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import List, Optional

import aiohttp

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass
class FetchedResource:
    url: str
    status: int
    sha256: str
    size_bytes: int
    body: bytes = b""
    content_type: Optional[str] = None
    elapsed_ms: int = 0


@dataclass
class FetchFailure:
    url: str
    reason: str


@dataclass
class FetchReport:
    ok: List[FetchedResource] = field(default_factory=list)
    failed: List[FetchFailure] = field(default_factory=list)

    @property
    def failure_count(self) -> int:
        return len(self.failed)

    def failures_for(self, url_substr: str) -> List[FetchFailure]:
        return [f for f in self.failed if url_substr in f.url]


class ResourceFetcher:
    """Concurrent fetcher with per-host politeness and sha256 hashing."""

    def __init__(
        self,
        concurrency: int = 8,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_s: int = 120,
    ) -> None:
        self._concurrency = concurrency
        self._user_agent = user_agent
        self._timeout_s = timeout_s
        self._semaphore: Optional[asyncio.Semaphore] = None

    async def _fetch_one(
        self, session: aiohttp.ClientSession, url: str
    ) -> None:
        assert self._semaphore is not None
        async with self._semaphore:
            try:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=self._timeout_s)
                ) as resp:
                    body = await resp.read()
                    if resp.status != 200:
                        self._report.failed.append(
                            FetchFailure(url=url, reason=f"HTTP {resp.status}")
                        )
                        return
                    self._report.ok.append(
                        FetchedResource(
                            url=url,
                            status=resp.status,
                            sha256=hashlib.sha256(body).hexdigest(),
                            size_bytes=len(body),
                            body=body,
                            content_type=resp.headers.get("Content-Type"),
                            elapsed_ms=0,
                        )
                    )
            except asyncio.TimeoutError:
                self._report.failed.append(FetchFailure(url=url, reason="TIMEOUT"))
            except Exception as exc:  # noqa: BLE001 - network layer, report verbatim
                self._report.failed.append(
                    FetchFailure(url=url, reason=f"{type(exc).__name__}: {exc}")
                )

    async def fetch_all(self, urls: List[str]) -> "FetchReport":
        self._report = FetchReport()
        self._semaphore = asyncio.Semaphore(self._concurrency)
        headers = {"User-Agent": self._user_agent}
        async with aiohttp.ClientSession(headers=headers) as session:
            await asyncio.gather(*(self._fetch_one(session, u) for u in urls))
        return self._report

    async def fetch_one(self, url: str) -> FetchedResource:
        report = await self.fetch_all([url])
        if report.failed:
            raise RuntimeError(f"RESOURCE_UNAVAILABLE: {url} ({report.failed[0].reason})")
        return report.ok[0]
