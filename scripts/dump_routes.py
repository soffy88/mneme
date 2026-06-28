"""导出 FastAPI 实际路由全表（根治 Master §8 手抄漂移 / DRIFT D3）。

用法：
    python scripts/dump_routes.py            # 打印 method + path
    python scripts/dump_routes.py --md       # 输出 Markdown 表，便于贴回文档

实际路由以本脚本输出为准；Master §8 仅作"核心契约"说明。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 让从 scripts/ 运行时也能 import 仓库根的 services/data 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def iter_routes():
    from services.main import app
    rows = []
    for r in app.routes:
        methods = getattr(r, "methods", None)
        path = getattr(r, "path", None)
        if not methods or not path:
            continue
        for m in sorted(methods):
            if m in ("HEAD", "OPTIONS"):
                continue
            rows.append((m, path, (getattr(r, "summary", "") or "").strip()))
    return sorted(rows, key=lambda x: (x[1], x[0]))


def main() -> None:
    rows = iter_routes()
    md = "--md" in sys.argv
    if md:
        print("| Method | Path | Summary |")
        print("|--------|------|---------|")
        for m, p, s in rows:
            print(f"| {m} | `{p}` | {s} |")
    else:
        for m, p, s in rows:
            print(f"{m:6} {p}")
    print(f"\n# 共 {len(rows)} 条路由", file=sys.stderr)


if __name__ == "__main__":
    main()
