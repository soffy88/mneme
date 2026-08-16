"""宿主 pytest 的测试库解析：只打 mneme_test，绝不碰活库 mneme。

C4 轮换了 postgres 口令后，`obase.config.Settings.DATABASE_URL` 的默认值仍是
`postgres:postgres@localhost:5433/mneme`。.env 只有 POSTGRES_PASSWORD、没有
DATABASE_URL，所以裸 `pytest` 会整片 InvalidPasswordError，或在口令碰巧对上时
误写生产库。本模块在 import settings 之前钉死 URL。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_PROD_NAME = re.compile(r"/mneme(?:\?|$)")
_TEST_NAME = re.compile(r"/mneme_test(?:\?|$)")


def load_postgres_password(env_file: Path | None = None) -> str:
    """环境变量优先，否则读仓库 .env 的 POSTGRES_PASSWORD。"""
    pw = os.environ.get("POSTGRES_PASSWORD", "").strip()
    if pw:
        return pw
    path = env_file or Path(__file__).resolve().parents[1] / ".env"
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("POSTGRES_PASSWORD="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def rewrite_db_name(url: str, dbname: str) -> str:
    return re.sub(r"/(mneme(?:_test)?)(\?[^ ]*)?$", rf"/{dbname}\2", url)


def is_production_mneme_url(url: str) -> bool:
    head = url.split("?", 1)[0]
    return bool(_PROD_NAME.search(head)) and not bool(_TEST_NAME.search(head))


def resolve_pytest_database_url(
    *,
    environ: dict[str, str] | None = None,
    env_file: Path | None = None,
    allow_prod: bool = False,
) -> str:
    env = os.environ if environ is None else environ
    url = (env.get("TEST_DATABASE_URL") or env.get("DATABASE_URL") or "").strip()
    if not url:
        pw = (env.get("POSTGRES_PASSWORD") or "").strip() or load_postgres_password(
            env_file
        )
        if not pw:
            raise RuntimeError(
                "pytest 无法解析测试库 URL：请设 TEST_DATABASE_URL，"
                "或在环境/.env 提供 POSTGRES_PASSWORD"
            )
        url = f"postgresql+asyncpg://postgres:{pw}@localhost:5433/mneme_test"
    allow = allow_prod or env.get("ALLOW_PROD_DB") == "1"
    if is_production_mneme_url(url):
        if allow:
            return url
        url = rewrite_db_name(url, "mneme_test")
    if not _TEST_NAME.search(url.split("?", 1)[0]) and not allow:
        raise RuntimeError(
            "拒绝：测试库必须是 mneme_test（"
            f"得到 …/{url.rsplit('/', 1)[-1]}）"
        )
    return url


def install_pytest_database_url() -> str:
    """写入进程环境，供随后 import 的 Settings / create_async_engine 读取。"""
    url = resolve_pytest_database_url()
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("TEST_DATABASE_URL", url)
    return url
