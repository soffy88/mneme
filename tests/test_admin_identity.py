"""W5 Part B：obase.admin_identity —— ADMIN_USER_IDS 环境变量白名单。"""

from __future__ import annotations

import uuid

from obase.admin_identity import is_admin, is_admin_id


def test_not_admin_when_env_unset(monkeypatch):
    monkeypatch.delenv("ADMIN_USER_IDS", raising=False)
    assert is_admin_id(uuid.uuid4()) is False


def test_admin_when_id_listed(monkeypatch):
    uid = uuid.uuid4()
    monkeypatch.setenv("ADMIN_USER_IDS", f"{uuid.uuid4()},{uid},{uuid.uuid4()}")
    assert is_admin_id(uid) is True


def test_not_admin_when_id_not_listed(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", f"{uuid.uuid4()},{uuid.uuid4()}")
    assert is_admin_id(uuid.uuid4()) is False


def test_is_admin_convenience_wrapper_reads_dot_id(monkeypatch):
    uid = uuid.uuid4()
    monkeypatch.setenv("ADMIN_USER_IDS", str(uid))

    class _FakeUser:
        id = uid

    assert is_admin(_FakeUser()) is True
