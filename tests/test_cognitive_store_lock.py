"""掌握度行锁：读路径默认不加 FOR UPDATE，写路径显式加锁。"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path
from uuid import uuid4

import pytest

from obase.cognitive_store import InMemoryStore, PgStore

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_inmemory_get_or_create_accepts_for_update_kwarg():
    store = InMemoryStore()
    sid = uuid4()
    a, _ = await store.get_or_create(sid, "kc-lock", for_update=False)
    b, _ = await store.get_or_create(sid, "kc-lock", for_update=True)
    assert a.kc_id == b.kc_id == "kc-lock"


def test_pgstore_only_locks_when_for_update():
    src = textwrap.dedent(inspect.getsource(PgStore.get_or_create))
    assert "for_update: bool = False" in src
    assert "with_for_update" in src
    assert "if for_update" in src
    # 禁止回到无条件 lock_stmt = select(...).with_for_update()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "lock_stmt":
                    raise AssertionError(
                        "PgStore.get_or_create 又出现无条件 lock_stmt，读路径会被行锁堵住"
                    )


def test_write_workflows_pass_for_update_true():
    cognitive = (ROOT / "vendor" / "omodul" / "cognitive.py").read_text(
        encoding="utf-8"
    )
    paper = (ROOT / "vendor" / "omodul" / "analyze_paper.py").read_text(
        encoding="utf-8"
    )
    assert "for_update=True" in cognitive
    assert "for_update=True" in paper
