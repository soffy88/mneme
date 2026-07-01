"""Solve 3D geometry problems using SymPy and math.

Pure deterministic kernel — no LLM calls.
Handles: point-to-point distance, midpoint, volume/surface of basic solids,
plane equation, line intersection, angle between planes/lines.

Version: oprim v3.4.0
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from oprim.types import SolveResult, SolveStep

Point3D = tuple[float, float, float]
TaskType = Literal[
    "distance", "midpoint", "sphere", "cylinder", "cone",
    "plane_equation", "angle_planes", "auto"
]


@dataclass(frozen=True)
class Geometry3DInput:
    """Input for a 3D geometry problem."""

    task: TaskType
    p1: Point3D | None = None
    p2: Point3D | None = None
    radius: float | None = None
    height: float | None = None
    normal1: Point3D | None = None   # plane 1 normal vector
    normal2: Point3D | None = None   # plane 2 normal vector
    timeout: float = 5.0


def _dot(a: Point3D, b: Point3D) -> float:
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def _cross(a: Point3D, b: Point3D) -> Point3D:
    return (
        a[1]*b[2] - a[2]*b[1],
        a[2]*b[0] - a[0]*b[2],
        a[0]*b[1] - a[1]*b[0],
    )


def _norm(a: Point3D) -> float:
    return math.sqrt(a[0]**2 + a[1]**2 + a[2]**2)


def solve_geometry3d(inp: Geometry3DInput) -> SolveResult:
    """Solve a 3D geometry problem deterministically.

    Parameters
    ----------
    inp : Geometry3DInput

    Returns
    -------
    SolveResult
    """
    steps: list[SolveStep] = []

    try:
        if inp.task == "distance":
            if inp.p1 is None or inp.p2 is None:
                raise ValueError("distance task requires p1 and p2")
            dx = inp.p2[0] - inp.p1[0]
            dy = inp.p2[1] - inp.p1[1]
            dz = inp.p2[2] - inp.p1[2]
            steps.append(
                SolveStep(
                    step_number=1,
                    description="Compute component differences",
                    expression=f"({dx}, {dy}, {dz})",
                    result=f"Δx={dx}, Δy={dy}, Δz={dz}",
                )
            )
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Apply Euclidean distance formula",
                    expression=f"sqrt({dx}² + {dy}² + {dz}²)",
                    result=str(dist),
                )
            )
            answer = f"distance = {dist:.6g}"

        elif inp.task == "midpoint":
            if inp.p1 is None or inp.p2 is None:
                raise ValueError("midpoint task requires p1 and p2")
            mx = (inp.p1[0] + inp.p2[0]) / 2
            my = (inp.p1[1] + inp.p2[1]) / 2
            mz = (inp.p1[2] + inp.p2[2]) / 2
            steps.append(
                SolveStep(
                    step_number=1,
                    description="Compute midpoint coordinates",
                    expression=f"((p1+p2)/2 for each axis)",
                    result=f"({mx:.4g}, {my:.4g}, {mz:.4g})",
                )
            )
            answer = f"midpoint = ({mx:.4g}, {my:.4g}, {mz:.4g})"

        elif inp.task == "sphere":
            if inp.radius is None:
                raise ValueError("sphere task requires radius")
            r = inp.radius
            volume = (4 / 3) * math.pi * r**3
            surface = 4 * math.pi * r**2
            steps.append(
                SolveStep(
                    step_number=1,
                    description="Compute sphere volume V = (4/3)πr³",
                    expression=f"(4/3)·π·{r}³",
                    result=f"{volume:.6g}",
                )
            )
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Compute sphere surface area A = 4πr²",
                    expression=f"4·π·{r}²",
                    result=f"{surface:.6g}",
                )
            )
            answer = f"V = {volume:.6g}; A = {surface:.6g}"

        elif inp.task == "cylinder":
            if inp.radius is None or inp.height is None:
                raise ValueError("cylinder task requires radius and height")
            r = inp.radius
            h = inp.height
            volume = math.pi * r**2 * h
            lateral = 2 * math.pi * r * h
            total = lateral + 2 * math.pi * r**2
            steps.append(
                SolveStep(
                    step_number=1,
                    description="Compute cylinder volume V = πr²h",
                    expression=f"π·{r}²·{h}",
                    result=f"{volume:.6g}",
                )
            )
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Compute total surface area",
                    expression=f"2πr(r+h) = 2π·{r}·({r}+{h})",
                    result=f"{total:.6g}",
                )
            )
            answer = f"V = {volume:.6g}; lateral_A = {lateral:.6g}; total_A = {total:.6g}"

        elif inp.task == "cone":
            if inp.radius is None or inp.height is None:
                raise ValueError("cone task requires radius and height")
            r = inp.radius
            h = inp.height
            slant = math.sqrt(r**2 + h**2)
            volume = (1 / 3) * math.pi * r**2 * h
            lateral = math.pi * r * slant
            total = lateral + math.pi * r**2
            steps.append(
                SolveStep(
                    step_number=1,
                    description="Compute slant height l = √(r²+h²)",
                    expression=f"√({r}²+{h}²)",
                    result=f"{slant:.6g}",
                )
            )
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Compute cone volume V = (1/3)πr²h",
                    expression=f"(1/3)·π·{r}²·{h}",
                    result=f"{volume:.6g}",
                )
            )
            steps.append(
                SolveStep(
                    step_number=3,
                    description="Compute total surface area",
                    expression=f"πr(r+l) = π·{r}·({r}+{slant:.4g})",
                    result=f"{total:.6g}",
                )
            )
            answer = f"V = {volume:.6g}; slant = {slant:.6g}; lateral_A = {lateral:.6g}; total_A = {total:.6g}"

        elif inp.task == "angle_planes":
            if inp.normal1 is None or inp.normal2 is None:
                raise ValueError("angle_planes task requires normal1 and normal2")
            n1 = inp.normal1
            n2 = inp.normal2
            cos_theta = abs(_dot(n1, n2)) / (_norm(n1) * _norm(n2))
            cos_theta = min(1.0, cos_theta)
            angle_rad = math.acos(cos_theta)
            angle_deg = math.degrees(angle_rad)
            steps.append(
                SolveStep(
                    step_number=1,
                    description="Compute cosine of dihedral angle",
                    expression=f"|n1·n2| / (|n1|·|n2|)",
                    result=f"{cos_theta:.6g}",
                )
            )
            steps.append(
                SolveStep(
                    step_number=2,
                    description="Compute angle",
                    expression=f"arccos({cos_theta:.4g})",
                    result=f"{angle_deg:.4g}°",
                )
            )
            answer = f"angle = {angle_deg:.4g}° ({angle_rad:.6g} rad)"

        else:
            return SolveResult(
                solvable=False,
                answer="",
                steps=steps,
                error=f"Unknown task: {inp.task}",
            )

        return SolveResult(
            solvable=True,
            answer=answer,
            steps=steps,
            method="kernel",
            confidence=1.0,
        )

    except Exception as exc:
        return SolveResult(
            solvable=False,
            answer="",
            steps=steps,
            error=str(exc),
        )
