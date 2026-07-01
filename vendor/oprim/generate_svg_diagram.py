"""Generate SVG diagram from Plot2DData or Three3DData.

Pure deterministic kernel — no LLM calls.
Produces a minimal SVG string for a 2D function plot.  3D is projected
to 2D via isometric projection.

Version: oprim v3.4.0
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from oprim.types import Plot2DData, Three3DData


@dataclass(frozen=True)
class SVGConfig:
    """Configuration for SVG output."""

    width: int = 600
    height: int = 400
    padding: int = 50
    stroke_color: str = "#2563EB"     # Tailwind blue-600
    axis_color: str = "#374151"       # Tailwind gray-700
    annotation_color: str = "#DC2626" # Tailwind red-600
    font_family: str = "monospace"
    font_size: int = 11
    stroke_width: float = 1.5


def _map_x(x: float, x_min: float, x_max: float, px: int, w: int) -> float:
    """Map data x to SVG x coordinate."""
    return px + (x - x_min) / (x_max - x_min) * w


def _map_y(y: float, y_min: float, y_max: float, px: int, h: int) -> float:
    """Map data y to SVG y coordinate (flipped — SVG y increases downward)."""
    return px + h - (y - y_min) / (y_max - y_min) * h


def generate_svg_from_plot2d(data: Plot2DData, cfg: SVGConfig | None = None) -> str:
    """Generate an SVG string from Plot2DData.

    Parameters
    ----------
    data : Plot2DData
    cfg : SVGConfig | None

    Returns
    -------
    str
        Complete SVG document as a string.
    """
    c = cfg or SVGConfig()
    w = c.width - 2 * c.padding
    h = c.height - 2 * c.padding
    px = c.padding
    py = c.padding

    x_min, x_max = data.x_range
    y_min, y_max = data.y_range

    if abs(x_max - x_min) < 1e-12:
        x_min, x_max = -10.0, 10.0
    if abs(y_max - y_min) < 1e-12:
        y_min, y_max = -10.0, 10.0

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{c.width}" height="{c.height}" '
        f'viewBox="0 0 {c.width} {c.height}">'
    )

    # Background
    parts.append(f'<rect width="{c.width}" height="{c.height}" fill="white"/>')

    # Title
    if data.title:
        tx = c.width // 2
        ty = py // 2
        parts.append(
            f'<text x="{tx}" y="{ty}" text-anchor="middle" '
            f'font-family="{c.font_family}" font-size="{c.font_size + 2}" '
            f'fill="{c.axis_color}">{_esc(data.title)}</text>'
        )

    # Axes
    ax0 = _map_x(0, x_min, x_max, px, w) if x_min <= 0 <= x_max else px
    ay0 = _map_y(0, y_min, y_max, py, h) if y_min <= 0 <= y_max else py + h

    # X axis
    parts.append(
        f'<line x1="{px}" y1="{ay0:.1f}" x2="{px+w}" y2="{ay0:.1f}" '
        f'stroke="{c.axis_color}" stroke-width="1"/>'
    )
    # Y axis
    parts.append(
        f'<line x1="{ax0:.1f}" y1="{py}" x2="{ax0:.1f}" y2="{py+h}" '
        f'stroke="{c.axis_color}" stroke-width="1"/>'
    )

    # Axis labels
    parts.append(
        f'<text x="{px+w+5}" y="{ay0+4:.1f}" '
        f'font-family="{c.font_family}" font-size="{c.font_size}" '
        f'fill="{c.axis_color}">{_esc(data.x_label)}</text>'
    )
    parts.append(
        f'<text x="{ax0+5:.1f}" y="{py-5}" '
        f'font-family="{c.font_family}" font-size="{c.font_size}" '
        f'fill="{c.axis_color}">{_esc(data.y_label)}</text>'
    )

    # Plot polyline
    if data.x_values and data.y_values:
        points: list[str] = []
        for xv, yv in zip(data.x_values, data.y_values):
            svgx = _map_x(xv, x_min, x_max, px, w)
            svgy = _map_y(yv, y_min, y_max, py, h)
            points.append(f"{svgx:.1f},{svgy:.1f}")
        if points:
            pts_str = " ".join(points)
            parts.append(
                f'<polyline points="{pts_str}" '
                f'fill="none" stroke="{c.stroke_color}" '
                f'stroke-width="{c.stroke_width}"/>'
            )

    # Annotations (zero crossings, etc.)
    for ax, ay, alabel in data.annotations:
        svgx = _map_x(ax, x_min, x_max, px, w)
        svgy = _map_y(ay, y_min, y_max, py, h)
        parts.append(
            f'<circle cx="{svgx:.1f}" cy="{svgy:.1f}" r="3" '
            f'fill="{c.annotation_color}"/>'
        )
        parts.append(
            f'<text x="{svgx+5:.1f}" y="{svgy-5:.1f}" '
            f'font-family="{c.font_family}" font-size="{c.font_size - 1}" '
            f'fill="{c.annotation_color}">{_esc(alabel)}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def generate_svg_from_three(data: Three3DData, cfg: SVGConfig | None = None) -> str:
    """Generate an isometric projection SVG from Three3DData.

    Uses a simple isometric projection to render the surface points.

    Parameters
    ----------
    data : Three3DData
    cfg : SVGConfig | None

    Returns
    -------
    str
        Complete SVG document as a string.
    """
    c = cfg or SVGConfig()

    # Isometric projection constants
    ISO_X_SCALE = 0.5
    ISO_Y_SCALE = 0.3
    Z_SCALE = 0.6

    cx = c.width / 2
    cy = c.height * 0.6

    def iso_project(x: float, y: float, z: float) -> tuple[float, float]:
        scale = 20.0
        sx = (x - y) * ISO_X_SCALE * scale + cx
        sy = (x + y) * ISO_Y_SCALE * scale - z * Z_SCALE * scale + cy
        return sx, sy

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{c.width}" height="{c.height}" '
        f'viewBox="0 0 {c.width} {c.height}">'
    )
    parts.append(f'<rect width="{c.width}" height="{c.height}" fill="white"/>')

    if data.title:
        parts.append(
            f'<text x="{c.width//2}" y="20" text-anchor="middle" '
            f'font-family="{c.font_family}" font-size="{c.font_size + 2}" '
            f'fill="{c.axis_color}">{_esc(data.title)}</text>'
        )

    # Draw surface points
    for xv, yv, zv in zip(data.x_values, data.y_values, data.z_values):
        px_svg, py_svg = iso_project(xv, yv, zv)
        parts.append(
            f'<circle cx="{px_svg:.1f}" cy="{py_svg:.1f}" r="1.5" '
            f'fill="{c.stroke_color}" opacity="0.6"/>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def generate_svg_diagram(
    data: Plot2DData | Three3DData,
    cfg: SVGConfig | None = None,
) -> str:
    """Generate SVG diagram from Plot2DData or Three3DData.

    Parameters
    ----------
    data : Plot2DData | Three3DData
    cfg : SVGConfig | None

    Returns
    -------
    str
        Complete SVG document string.
    """
    if isinstance(data, Plot2DData):
        return generate_svg_from_plot2d(data, cfg)
    elif isinstance(data, Three3DData):
        return generate_svg_from_three(data, cfg)
    else:
        raise TypeError(f"Unsupported data type: {type(data)}")


def _esc(text: str) -> str:
    """Escape XML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
