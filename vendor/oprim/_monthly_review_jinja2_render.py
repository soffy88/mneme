"""月度复盘 Jinja2 模板渲染 (oprim B8)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from oprim._exceptions import OprimError


class RenderedReport(BaseModel):
    """Jinja2 渲染结果.

    Attributes:
        content:       渲染后的完整文本.
        template_name: 使用的模板文件名.
        rendered_at:   渲染完成时间 (UTC).
    """

    content: str
    template_name: str
    rendered_at: datetime


def monthly_review_jinja2_render(
    *,
    template_name: str,
    context: dict[str, Any],
    template_dir: Path | str,
) -> RenderedReport:
    """Render a monthly review report from a Jinja2 template file.

    Args:
        template_name: Template filename relative to ``template_dir``
                       (e.g. ``"monthly_review.md.j2"``).
        context:       Template variables dict passed to ``render()``.
        template_dir:  Directory containing Jinja2 templates.  Must exist.

    Returns:
        :class:`RenderedReport` with rendered content and metadata.

    Raises:
        OprimError: If ``template_dir`` does not exist, the template file is
                    not found, or Jinja2 rendering fails.

    Example:
        >>> import tempfile, pathlib
        >>> with tempfile.TemporaryDirectory() as d:
        ...     p = pathlib.Path(d) / "t.j2"
        ...     _ = p.write_text("月份: {{ month }}")
        ...     r = monthly_review_jinja2_render(
        ...         template_name="t.j2", context={"month": "2024-03"}, template_dir=d
        ...     )
        ...     r.content
        '月份: 2024-03'
    """
    try:
        from jinja2 import Environment, FileSystemLoader, TemplateNotFound, TemplateError
    except ImportError as exc:
        raise OprimError("jinja2 is required: pip install jinja2") from exc

    tdir = Path(template_dir)
    if not tdir.is_dir():
        raise OprimError(f"template_dir does not exist: {tdir}")

    env = Environment(loader=FileSystemLoader(str(tdir)), autoescape=False)  # noqa: S701
    try:
        template = env.get_template(template_name)
    except TemplateNotFound as exc:
        raise OprimError(f"Template {template_name!r} not found in {tdir}") from exc

    try:
        content = template.render(**context)
    except TemplateError as exc:
        raise OprimError(f"Jinja2 render error in {template_name!r}: {exc}") from exc

    return RenderedReport(
        content=content,
        template_name=template_name,
        rendered_at=datetime.now(tz=timezone.utc),
    )
