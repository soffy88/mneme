"""测试库守卫：纯单测，不连库。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.db_guard import (
    is_production_mneme_url,
    load_postgres_password,
    resolve_pytest_database_url,
    rewrite_db_name,
)


def test_rewrite_mneme_to_mneme_test():
    src = "postgresql+asyncpg://postgres:x@localhost:5433/mneme"
    assert rewrite_db_name(src, "mneme_test").endswith("/mneme_test")


def test_rewrite_keeps_query():
    src = "postgresql+asyncpg://postgres:x@localhost:5433/mneme?ssl=disable"
    assert rewrite_db_name(src, "mneme_test").endswith("/mneme_test?ssl=disable")


def test_is_production_mneme_url():
    assert is_production_mneme_url(
        "postgresql+asyncpg://postgres:x@localhost:5433/mneme"
    )
    assert not is_production_mneme_url(
        "postgresql+asyncpg://postgres:x@localhost:5433/mneme_test"
    )


def test_builds_from_password_when_url_missing():
    url = resolve_pytest_database_url(environ={"POSTGRES_PASSWORD": "secret-pw"})
    assert url.endswith("/mneme_test")
    assert "secret-pw" in url
    assert ":postgres:" not in url or "postgres:secret-pw@" in url


def test_rewrites_explicit_prod_url_to_test():
    url = resolve_pytest_database_url(
        environ={
            "DATABASE_URL": "postgresql+asyncpg://postgres:real@localhost:5433/mneme"
        }
    )
    assert url.endswith("/mneme_test")
    assert "real" in url


def test_test_database_url_wins():
    url = resolve_pytest_database_url(
        environ={
            "DATABASE_URL": "postgresql+asyncpg://postgres:a@localhost:5433/mneme",
            "TEST_DATABASE_URL": (
                "postgresql+asyncpg://postgres:b@localhost:5433/mneme_test"
            ),
        }
    )
    assert url.endswith("/mneme_test")
    assert ":b@" in url


def test_rejects_unknown_db_name():
    with pytest.raises(RuntimeError, match="mneme_test"):
        resolve_pytest_database_url(
            environ={
                "DATABASE_URL": "postgresql+asyncpg://postgres:x@localhost:5433/other"
            }
        )


def test_missing_password_and_url_fails():
    with pytest.raises(RuntimeError, match="POSTGRES_PASSWORD"):
        resolve_pytest_database_url(
            environ={}, env_file=Path("/nonexistent/.env")
        )


def test_load_postgres_password_from_env_file(tmp_path: Path):
    f = tmp_path / ".env"
    f.write_text("FOO=1\nPOSTGRES_PASSWORD=from-file\n", encoding="utf-8")
    assert load_postgres_password(f) == "from-file"
