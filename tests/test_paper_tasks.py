"""D.2 Celery 装配任务：瞬时失败走 self.retry，永久失败不重试。

CRG 审查发现 process_paper/_RetryableError 零测试覆盖。这里不连 broker，直接
调任务 run()（self 由 Celery 自动绑定为任务对象），用 monkeypatch 替换
process_paper.retry 来断言重试语义：成功直返、_RetryableError → retry(exc=...)、
非 RetryableError → 原样上抛（任务失败而非吞错）。"""

from __future__ import annotations

import pytest

from tasks import paper_tasks
from tasks.paper_tasks import _RetryableError, process_paper


def test_process_paper_success(monkeypatch):
    async def _ok(_paper_id: str) -> dict:
        return {"status": "done", "wrong_count": 3}

    monkeypatch.setattr(paper_tasks, "_process_paper_async", _ok)
    assert process_paper.run("paper-1") == {"status": "done", "wrong_count": 3}


def test_process_paper_retries_on_retryable(monkeypatch):
    async def _boom(_paper_id: str) -> dict:
        raise _RetryableError("MinIO 抖动")

    monkeypatch.setattr(paper_tasks, "_process_paper_async", _boom)

    retried: list = []

    def _fake_retry(exc=None, **kwargs):
        retried.append(exc)
        raise exc

    monkeypatch.setattr(process_paper, "retry", _fake_retry)
    with pytest.raises(_RetryableError):
        process_paper.run("paper-2")
    assert len(retried) == 1
    assert isinstance(retried[0], _RetryableError)


def test_process_paper_non_retryable_propagates(monkeypatch):
    async def _boom(_paper_id: str) -> dict:
        raise ValueError("paper record corrupt")

    monkeypatch.setattr(paper_tasks, "_process_paper_async", _boom)
    with pytest.raises(ValueError):
        process_paper.run("paper-3")  # 永久失败不重试


def test_retryable_error_is_exception_subclass():
    assert issubclass(_RetryableError, Exception)
