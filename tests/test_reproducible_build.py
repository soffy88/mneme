"""Blueprint P0：依赖解析和 Docker 构建不能依赖宿主机绝对路径。"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_python_project_has_no_host_local_3o_dependencies() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text()

    assert "file:///home/" not in pyproject
    assert "obase @" not in pyproject
    assert "oprim @" not in pyproject
    assert "oskill @" not in pyproject
    assert "omodul @" not in pyproject


def test_docker_build_uses_checked_in_vendor_closure() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text()

    assert "COPY platform/3O/" not in dockerfile
    assert "COPY uv.lock ." in dockerfile
    assert "COPY pyproject.toml ." in dockerfile
    # 整个已检入的构建上下文（含 vendor/ 闭包）必须被复制进镜像；允许 COPY 带
    # --chown 等标志（8145420 起用 COPY --chown 在复制时设属主）。
    assert re.search(r"^COPY(?:\s+--[\w-]+=\S+)*\s+\.\s+\.\s*$", dockerfile, re.M)
    # 镜像瘦身守卫：不得再用单独的 chown -R 层复制整棵 app 树（约 6GB 重复层）。
    assert "chown -R" not in dockerfile
    assert "uv export --frozen" in dockerfile
    assert "vendor/" in dockerfile


def test_lockfile_is_checked_in() -> None:
    assert (ROOT / "uv.lock").is_file()
