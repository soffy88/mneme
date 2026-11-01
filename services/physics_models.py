"""物理真值模型 + 不变量检查（Atlas of Physics 方法论的 Mneme 干净实现）。

只学方法，不搬代码、文本或题目：atlas 的纪律是“一个纯函数真值模型
是唯一数值来源，checks 用另一算法独立重算每个量”——本模块把这条纪律
写成 Mneme 的 TruthModel 协议实现。模型、参数值、检查项、代码全部自写，
公式取自通用物理（平抛运动、单摆小角度近似），与 atlas 章节的具体数值、
题目、代码结构均无关系。

- 真值模型：实现 teaching_figure 的 TruthModel 协议（initial_state /
  apply_action / derive / step），语义态只含物理量；非法输入拒绝、
  越界 clamp，绝不编造看似合理的结果。
- 不变量检查：每个数值读数都有一条独立重算路径（数值积分、步进模拟、
  二分求根、中心差分、RK4），与 derive 的解析路径对上才算通过；
  另有能量守恒等物理定律检查。任一检查失败，模型整体 unverified。
- 忽略项明示：每个模型声明 ignored_terms（理想化假设），规格 caveat
  必须逐条点名，缺一不可——门禁只验“写了”，语义由作者自查。
- 注册：本模块导入时把物理模型幂等地注册进 teaching_figure 的
  MODEL_REGISTRY，于是 verify_figure 的模型门禁可直接认物理模型；
  teaching_figure 的既有行为一字不改。

本模块是纯函数，无 DB、无网络、无 LLM 调用，可脱服务直测。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from services.teaching_figure import (
    MODEL_REGISTRY,
    ImpossibleStateError,
    ModelParameter,
    NumberKind,
    TaggedNumber,
    TruthModel,
    ValidationIssue,
    ValidationResult,
    _check_expectations,
    find_untagged_numbers,
)

__all__ = [
    "InvariantCheck",
    "PHYSICS_MODEL_REGISTRY",
    "PhysicsTruthModel",
    "ProjectileMotionModel",
    "PendulumModel",
    "register_physics_models",
    "run_invariant_checks",
    "verify_physics_model",
]

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")
_BILINGUAL_FIELDS = ("title", "lead", "caveat")


# ── 数值独立重算的通用工具（标准数值方法，自写）────────────────────────


def _integrate_midpoint(fn: Callable[[float], float], a: float, b: float, n: int) -> float:
    """中点法数值积分（另一算法，与解析积分对照用）。"""
    if n <= 0:
        raise ValueError("n must be positive")
    h = (b - a) / n
    return sum(fn(a + (i + 0.5) * h) for i in range(n)) * h


def _central_diff(fn: Callable[[float], float], t: float, h: float = 1e-6) -> float:
    """中心差分求导（另一算法，与解析速度/角速度对照用）。"""
    return (fn(t + h) - fn(t - h)) / (2.0 * h)


def _bisect(fn: Callable[[float], float], a: float, b: float, iters: int = 200) -> float:
    """二分求根：fn(a) 与 fn(b) 须异号，返回根的近似值。"""
    fa, fb = fn(a), fn(b)
    if fa == 0.0:
        return a
    if fb == 0.0:
        return b
    if fa * fb > 0:
        raise ValueError("bisection needs a sign change on [a, b]")
    for _ in range(iters):
        m = 0.5 * (a + b)
        if fn(a) * fn(m) <= 0:
            b = m
        else:
            a = m
    return 0.5 * (a + b)


def _close(a: float, b: float, rel: float = 1e-6, abs_tol: float = 1e-9) -> bool:
    return abs(a - b) <= abs_tol + rel * abs(b)


@dataclass(frozen=True)
class InvariantCheck:
    """一条不变量检查的结果：名字、是否通过、说明（数值对账细节）。"""

    name: str
    passed: bool
    detail: str = ""


class PhysicsTruthModel(TruthModel):
    """物理真值模型：TruthModel 协议 + 独立重算 + 忽略项声明。

    子类必须实现 recompute：用与 derive 不同的算法算出同一读数。
    没有独立重算路径的数值读数，门禁判失败（fail-closed）。
    """

    def ignored_terms(self) -> list[dict[str, str]]:
        """模型忽略的项（理想化假设），每项 {zh, en}，caveat 必须点名。"""
        return []

    def probe_actions(
        self, bound: Mapping[str, TaggedNumber | bool | str]
    ) -> list[tuple[str, tuple[dict, ...]]]:
        """检查探针：(探针名, 动作序列)，覆盖复位态与有意义的演化态。"""
        return [("reset", ())]

    def recompute(
        self,
        readout: str,
        bound: Mapping[str, TaggedNumber | bool | str],
        actions: Sequence[dict] = (),
    ) -> float:
        """独立重算某读数：另一算法、另一路径。无此路径则 raise KeyError。"""
        raise KeyError(f"no independent recomputation for readout {readout!r}")

    def compare_tolerance(
        self,
        readout: str,
        value: float,
        bound: Mapping[str, TaggedNumber | bool | str],
    ) -> tuple[float, float]:
        """derive 与 recompute 的比对容差（相对，绝对）：默认 1e-6/1e-9。

        近似模型（如小角度单摆）可放宽到其近似误差阶，并在文档中
        写明放宽的依据；放宽绝不能掩盖符号/量级错误。
        """
        return 1e-6, 1e-9

    def extra_invariant_checks(
        self, bound: Mapping[str, TaggedNumber | bool | str]
    ) -> list[InvariantCheck]:
        """物理定律类检查（能量守恒、行为约束等），子类按需补充。"""
        return []

    def _state_after(
        self,
        bound: Mapping[str, TaggedNumber | bool | str],
        actions: Sequence[dict],
    ) -> dict:
        state = self.initial_state(bound)
        for action in actions:
            if not isinstance(action, dict):
                raise ImpossibleStateError("action must be an object")
            state = self.apply_action(state, action)
        return state

    def _compare_check(
        self,
        probe: str,
        readout: str,
        bound: Mapping[str, TaggedNumber | bool | str],
        actions: Sequence[dict],
    ) -> InvariantCheck:
        name = f"{probe}:{readout}"
        try:
            state = self._state_after(bound, actions)
            derived = self.derive(state)
            value = derived.get(readout)
            if not isinstance(value, TaggedNumber):
                return InvariantCheck(name, False, f"readout {readout!r} is not numeric")
            other = self.recompute(readout, bound, actions)
        except (ImpossibleStateError, KeyError, ValueError) as exc:
            return InvariantCheck(name, False, f"recompute failed: {exc}")
        rel, abs_tol = self.compare_tolerance(readout, value.value, bound)
        ok = _close(value.value, other, rel=rel, abs_tol=abs_tol)
        return InvariantCheck(
            name,
            ok,
            f"derive {value.value!r} {value.unit} vs recomputed {other!r} {value.unit}",
        )

    def invariant_checks(
        self, bound: Mapping[str, TaggedNumber | bool | str]
    ) -> list[InvariantCheck]:
        """默认检查集：每个探针 × 每个数值读数，derive 对 recompute。"""
        checks: list[InvariantCheck] = []
        for probe, actions in self.probe_actions(bound):
            try:
                state = self._state_after(bound, actions)
                derived = self.derive(state)
            except ImpossibleStateError as exc:
                checks.append(
                    InvariantCheck(probe, False, f"probe state rejected: {exc}")
                )
                continue
            for readout, value in derived.items():
                if isinstance(value, TaggedNumber):
                    checks.append(self._compare_check(probe, readout, bound, actions))
        checks.extend(self.extra_invariant_checks(bound))
        return checks


def run_invariant_checks(
    model: PhysicsTruthModel,
    bound: Mapping[str, TaggedNumber | bool | str],
) -> list[InvariantCheck]:
    """跑完模型的不变量检查：逐条列结果，检查本身抛错也记为失败。"""
    try:
        return model.invariant_checks(bound)
    except Exception as exc:  # 检查集整体崩溃也 fail-closed，不抛给调用方
        return [InvariantCheck("checks_ran", False, f"invariant checks raised: {exc}")]


# ── 参照模型 1：平抛运动 ─────────────────────────────────────────────────


class ProjectileMotionModel(PhysicsTruthModel):
    """平抛运动（Mneme 自有 K12 物理内容）：水平匀速 + 竖直自由落体。

    水平方向不受力（忽略空气阻力与风），竖直方向只受重力。落地后
    状态停在落地点（t 钉在飞行时间），不再往地下演化。
    """

    name = "projectile_motion"
    parameters = (
        ModelParameter("v0", unit="m/s", kind=NumberKind.SOURCE_FACT, minimum=0.0),
        ModelParameter(
            "height", unit="m", kind=NumberKind.SOURCE_FACT, minimum=0.0
        ),
        ModelParameter("g", unit="m/s²", kind=NumberKind.SOURCE_FACT, minimum=0.0),
    )

    def ignored_terms(self) -> list[dict[str, str]]:
        return [
            {"zh": "空气阻力", "en": "air resistance"},
            {"zh": "风", "en": "wind"},
        ]

    def _flight_time(self, v0: float, height: float, g: float) -> float:
        return math.sqrt(2.0 * height / g)

    def initial_state(self, config):
        v0 = config["v0"].value
        height = config["height"].value
        g = config["g"].value
        if v0 <= 0:
            raise ImpossibleStateError("v0 must be positive")
        if height <= 0:
            raise ImpossibleStateError("height must be positive")
        if g <= 0:
            raise ImpossibleStateError("g must be positive")
        return {"t": 0.0, "v0": v0, "height": height, "g": g}

    def apply_action(self, state, action):
        if action.get("kind") == "advance":
            dt = action.get("dt")
            if not isinstance(dt, (int, float)) or isinstance(dt, bool):
                raise ImpossibleStateError("advance action requires numeric dt")
            if dt < 0:
                raise ImpossibleStateError("dt cannot be negative")
            new_t = state["t"] + min(float(dt), 60.0)
        elif action.get("kind") == "set_time":
            t = action.get("t")
            if not isinstance(t, (int, float)) or isinstance(t, bool):
                raise ImpossibleStateError("set_time action requires numeric t")
            if t < 0:
                raise ImpossibleStateError("t cannot be negative")
            new_t = min(float(t), 60.0)
        else:
            raise ImpossibleStateError(f"unknown action: {action.get('kind')!r}")
        flight = self._flight_time(state["v0"], state["height"], state["g"])
        new_state = dict(state)
        new_state["t"] = min(new_t, flight)
        return new_state

    def step(self, state, dt_seconds: float) -> dict:
        return self.apply_action(state, {"kind": "advance", "dt": dt_seconds})

    def derive(self, state):
        t = state["t"]
        v0, height, g = state["v0"], state["height"], state["g"]
        x = v0 * t
        y = height - 0.5 * g * t * t
        vx = v0
        vy = -g * t
        flight = self._flight_time(v0, height, g)
        return {
            "x": TaggedNumber(
                x, "m", NumberKind.CALCULATION, "水平位移＝水平初速度×时间"
            ),
            "y": TaggedNumber(
                y, "m", NumberKind.CALCULATION, "竖直高度＝抛出高度－½gt²"
            ),
            "vx": TaggedNumber(
                vx, "m/s", NumberKind.CALCULATION, "水平分速度不变＝水平初速度"
            ),
            "vy": TaggedNumber(
                vy, "m/s", NumberKind.CALCULATION, "竖直分速度＝－gt"
            ),
            "speed": TaggedNumber(
                math.hypot(vx, vy),
                "m/s",
                NumberKind.CALCULATION,
                "合速度＝√(vx²＋vy²)",
            ),
            "flight_time": TaggedNumber(
                flight, "s", NumberKind.CALCULATION, "飞行时间＝√(2h/g)"
            ),
            "range": TaggedNumber(
                v0 * flight, "m", NumberKind.CALCULATION, "射程＝水平初速度×飞行时间"
            ),
            "phase": "landed" if t >= flight else "in_flight",
        }

    def probe_actions(self, bound):
        flight = self._flight_time(
            bound["v0"].value, bound["height"].value, bound["g"].value
        )
        return [
            ("reset", ()),
            ("mid_flight", ({"kind": "set_time", "t": 0.5 * flight},)),
            ("landing", ({"kind": "set_time", "t": flight},)),
        ]

    def recompute(self, readout, bound, actions=()):
        state = self._state_after(bound, actions)
        t, v0, height, g = state["t"], state["v0"], state["height"], state["g"]
        def x_of(u: float) -> float:
            return v0 * u

        def y_of(u: float) -> float:
            return height - 0.5 * g * u * u
        if readout == "x":
            n = max(1, math.ceil(t / 1e-3)) if t > 0 else 1
            dt = t / n if t > 0 else 0.0
            return sum(v0 * dt for _ in range(n))
        if readout == "y":
            return height + _integrate_midpoint(lambda u: -g * u, 0.0, t, 2000)
        if readout == "vx":
            return _central_diff(x_of, t)
        if readout == "vy":
            return _central_diff(y_of, t)
        if readout == "speed":
            return math.hypot(
                self.recompute("vx", bound, actions),
                self.recompute("vy", bound, actions),
            )
        if readout == "flight_time":
            return _bisect(y_of, 0.0, 60.0)
        if readout == "range":
            return v0 * self.recompute("flight_time", bound, actions)
        raise KeyError(f"no independent recomputation for readout {readout!r}")

    def extra_invariant_checks(self, bound):
        checks: list[InvariantCheck] = []
        v0, height, g = bound["v0"].value, bound["height"].value, bound["g"].value
        flight = self._flight_time(v0, height, g)
        energy0 = 0.5 * v0 * v0 + g * height
        for probe, actions in self.probe_actions(bound):
            state = self._state_after(bound, actions)
            d = self.derive(state)
            energy = (
                0.5 * (d["vx"].value ** 2 + d["vy"].value ** 2)
                + g * d["y"].value
            )
            ok = _close(energy, energy0)
            checks.append(
                InvariantCheck(
                    f"{probe}:energy_conserved",
                    ok,
                    f"mechanical energy per unit mass {energy!r} vs initial {energy0!r}",
                )
            )
        # 步进模拟落地：小步长积分直到 y<=0，落点横坐标须与射程一致。
        dt = 1e-3
        x = 0.0
        y = height
        vy = 0.0
        while y > 0:
            vy -= g * dt
            y += vy * dt
            x += v0 * dt
        checks.append(
            InvariantCheck(
                "stepped_landing_matches_range",
                _close(x, v0 * flight, rel=1e-3),
                f"stepped landing x {x!r} vs range {v0 * flight!r}",
            )
        )
        # 落地后不再演化：继续 advance，t 钉在飞行时间。
        landed = self._state_after(bound, ({"kind": "set_time", "t": flight},))
        rested = self.apply_action(landed, {"kind": "advance", "dt": 5.0})
        checks.append(
            InvariantCheck(
                "rest_after_landing",
                rested["t"] == flight
                and _close(self.derive(rested)["y"].value, 0.0),
                f"t after rest {rested['t']!r}, flight {flight!r}",
            )
        )
        return checks


# ── 参照模型 2：单摆（小角度近似）────────────────────────────────────────


class PendulumModel(PhysicsTruthModel):
    """单摆小角度近似（Mneme 自有 K12 物理内容）：θ＝θ0·cos(ωt)。

    摆角须 ≤10°，超出则模型拒绝（小角度近似不再成立，不编结果）。
    摆线质量、空气阻力忽略；重力加速度取当地值，由参数给定。
    """

    name = "pendulum_small_angle"
    parameters = (
        ModelParameter(
            "length", unit="m", kind=NumberKind.SOURCE_FACT, minimum=0.0
        ),
        ModelParameter(
            "amplitude_deg", unit="deg", kind=NumberKind.SOURCE_FACT, minimum=0.0
        ),
        ModelParameter("g", unit="m/s²", kind=NumberKind.SOURCE_FACT, minimum=0.0),
    )

    def ignored_terms(self) -> list[dict[str, str]]:
        return [
            {"zh": "空气阻力", "en": "air resistance"},
            {"zh": "摆线质量", "en": "mass of the string"},
            {"zh": "大角度修正", "en": "large-angle correction"},
        ]

    def compare_tolerance(self, readout, value, bound):
        theta0 = math.radians(bound["amplitude_deg"].value)
        length = bound["length"].value
        omega = self._omega(length, bound["g"].value)
        scales = {
            "angle": 1.0,
            "angular_velocity": omega,
            "angular_acceleration": omega * omega,
            "speed": length * omega,
            "height": length,
        }
        if readout in scales:
            # RK4 解的是精确非线性方程，与线性化解的差正在小角度
            # 近似的误差阶 theta0^3；容差取该阶，符号/量级错误仍会落网。
            return 1e-6, (theta0 ** 3) * scales[readout]
        return super().compare_tolerance(readout, value, bound)

    def _omega(self, length: float, g: float) -> float:
        return math.sqrt(g / length)

    def initial_state(self, config):
        length = config["length"].value
        amplitude = config["amplitude_deg"].value
        g = config["g"].value
        if length <= 0:
            raise ImpossibleStateError("length must be positive")
        if g <= 0:
            raise ImpossibleStateError("g must be positive")
        if amplitude <= 0 or amplitude > 10.0:
            raise ImpossibleStateError(
                "amplitude_deg must be in (0, 10] for the small-angle approximation"
            )
        return {
            "t": 0.0,
            "length": length,
            "amplitude_rad": math.radians(amplitude),
            "g": g,
        }

    def apply_action(self, state, action):
        if action.get("kind") == "advance":
            dt = action.get("dt")
            if not isinstance(dt, (int, float)) or isinstance(dt, bool):
                raise ImpossibleStateError("advance action requires numeric dt")
            if dt < 0:
                raise ImpossibleStateError("dt cannot be negative")
            new_t = state["t"] + min(float(dt), 60.0)
        elif action.get("kind") == "set_time":
            t = action.get("t")
            if not isinstance(t, (int, float)) or isinstance(t, bool):
                raise ImpossibleStateError("set_time action requires numeric t")
            if t < 0:
                raise ImpossibleStateError("t cannot be negative")
            new_t = min(float(t), 60.0)
        else:
            raise ImpossibleStateError(f"unknown action: {action.get('kind')!r}")
        new_state = dict(state)
        new_state["t"] = new_t
        return new_state

    def step(self, state, dt_seconds: float) -> dict:
        return self.apply_action(state, {"kind": "advance", "dt": dt_seconds})

    def derive(self, state):
        t = state["t"]
        length, theta0, g = state["length"], state["amplitude_rad"], state["g"]
        omega = self._omega(length, g)
        theta = theta0 * math.cos(omega * t)
        omega_t = -theta0 * omega * math.sin(omega * t)
        period = 2.0 * math.pi / omega
        return {
            "angle": TaggedNumber(
                theta, "rad", NumberKind.CALCULATION, "摆角＝θ0·cos(ωt)"
            ),
            "angular_velocity": TaggedNumber(
                omega_t,
                "rad/s",
                NumberKind.CALCULATION,
                "角速度＝－θ0·ω·sin(ωt)",
            ),
            "angular_acceleration": TaggedNumber(
                -omega * omega * theta,
                "rad/s²",
                NumberKind.CALCULATION,
                "角加速度＝－ω²·θ（回复力矩的线性化）",
            ),
            "speed": TaggedNumber(
                length * abs(omega_t),
                "m/s",
                NumberKind.CALCULATION,
                "摆锤速率＝摆长×|角速度|",
            ),
            "period": TaggedNumber(
                period, "s", NumberKind.CALCULATION, "周期＝2π√(L/g)"
            ),
            "height": TaggedNumber(
                length * (1.0 - math.cos(theta)),
                "m",
                NumberKind.CALCULATION,
                "摆锤升高＝L(1－cosθ)",
            ),
        }

    def probe_actions(self, bound):
        period = 2.0 * math.pi / self._omega(bound["length"].value, bound["g"].value)
        return [
            ("reset", ()),
            ("quarter_period", ({"kind": "set_time", "t": 0.25 * period},)),
            ("half_period", ({"kind": "set_time", "t": 0.5 * period},)),
        ]

    def _rk4_angle(self, length: float, g: float, theta0: float, t_end: float):
        """精确非线性方程 θ''＝－(g/L)sinθ 的 RK4 积分（另一算法）。"""
        dt = 1e-3
        n = max(1, int(round(t_end / dt))) if t_end > 0 else 0
        h = t_end / n if n else 0.0
        w2 = g / length
        th, om = theta0, 0.0
        for _ in range(n):
            k1_th, k1_om = om, -w2 * math.sin(th)
            k2_th, k2_om = om + 0.5 * h * k1_om, -w2 * math.sin(th + 0.5 * h * k1_th)
            k3_th, k3_om = om + 0.5 * h * k2_om, -w2 * math.sin(th + 0.5 * h * k2_th)
            k4_th, k4_om = om + h * k3_om, -w2 * math.sin(th + h * k3_th)
            th += h * (k1_th + 2 * k2_th + 2 * k3_th + k4_th) / 6.0
            om += h * (k1_om + 2 * k2_om + 2 * k3_om + k4_om) / 6.0
        return th, om

    def recompute(self, readout, bound, actions=()):
        state = self._state_after(bound, actions)
        t = state["t"]
        length, theta0, g = state["length"], state["amplitude_rad"], state["g"]
        omega = self._omega(length, g)
        def theta_of(u: float) -> float:
            return theta0 * math.cos(omega * u)

        def omega_of(u: float) -> float:
            return -theta0 * omega * math.sin(omega * u)
        if readout == "angle":
            return self._rk4_angle(length, g, theta0, t)[0]
        if readout == "angular_velocity":
            return _central_diff(theta_of, t)
        if readout == "angular_acceleration":
            return _central_diff(omega_of, t)
        if readout == "speed":
            return length * abs(self.recompute("angular_velocity", bound, actions))
        if readout == "period":
            period = 2.0 * math.pi / omega
            first_zero = _bisect(theta_of, 0.0, 0.5 * period)
            return 4.0 * first_zero
        if readout == "height":
            return length * (1.0 - math.cos(self.recompute("angle", bound, actions)))
        raise KeyError(f"no independent recomputation for readout {readout!r}")

    def extra_invariant_checks(self, bound):
        checks: list[InvariantCheck] = []
        length, theta0 = bound["length"].value, math.radians(
            bound["amplitude_deg"].value
        )
        g = bound["g"].value
        # 线性化动力学守恒的是二次型能量 1/2 (Lw)^2 + 1/2 gL theta^2；
        # 精确势能 gL(1-cos theta) 与它的差为 O(theta^4)，另立一门以
        # theta0^4 为界（2 倍裕量），如实记录近似的代价。
        lin0 = 0.5 * g * length * theta0 * theta0
        gap_bound = 2.0 * g * length * theta0 ** 4 / 24.0
        for probe, actions in self.probe_actions(bound):
            state = self._state_after(bound, actions)
            d = self.derive(state)
            lin_energy = (
                0.5 * (length * d["angular_velocity"].value) ** 2
                + 0.5 * g * length * d["angle"].value ** 2
            )
            checks.append(
                InvariantCheck(
                    f"{probe}:energy_conserved",
                    _close(lin_energy, lin0),
                    f"linearized energy {lin_energy!r} vs initial {lin0!r}",
                )
            )
            exact_energy = (
                0.5 * (length * d["angular_velocity"].value) ** 2
                + g * d["height"].value
            )
            gap = abs(exact_energy - lin_energy)
            checks.append(
                InvariantCheck(
                    f"{probe}:approximation_gap_bounded",
                    gap <= gap_bound,
                    f"exact-vs-linearized energy gap {gap!r} <= bound {gap_bound!r}",
                )
            )
        checks.append(
            InvariantCheck(
                "small_angle_regime",
                0.0 < bound["amplitude_deg"].value <= 10.0,
                f"amplitude {bound['amplitude_deg'].value!r} deg within (0, 10]",
            )
        )
        return checks


PHYSICS_MODEL_REGISTRY: dict[str, PhysicsTruthModel] = {
    ProjectileMotionModel.name: ProjectileMotionModel(),
    PendulumModel.name: PendulumModel(),
}


def register_physics_models() -> None:
    """把物理模型注册进 teaching_figure 的 MODEL_REGISTRY（幂等）。

    verify_figure 按名查模型，注册后物理模型可直接作教学图的
    model_ref 后端；teaching_figure 本身一字不改。
    """
    MODEL_REGISTRY.update(PHYSICS_MODEL_REGISTRY)


register_physics_models()


# ── 模型规格验证门 ─────────────────────────────────────────────────────────


def _bilingual_text(
    value: object, field_name: str, issues: list[ValidationIssue]
) -> dict[str, str] | None:
    if not isinstance(value, dict):
        issues.append(
            ValidationIssue(
                field_name,
                "not_bilingual",
                f"{field_name} must be an object with zh and en text",
            )
        )
        return None
    zh, en = value.get("zh"), value.get("en")
    ok = True
    for lang, text in (("zh", zh), ("en", en)):
        if not isinstance(text, str) or not text.strip():
            issues.append(
                ValidationIssue(
                    field_name,
                    "missing_language",
                    f"{field_name}.{lang} must be a non-empty string",
                )
            )
            ok = False
    return {"zh": zh, "en": en} if ok else None


def verify_physics_model(
    spec: object,
    *,
    known_ku_ids: object | None = None,
) -> ValidationResult:
    """验证门：p1–p6 全过才 verified，失败逐条列原因。

    p1 schema（id 唯一、必填齐全、verified 字段禁入、双语齐全）；
    p2 锚点 KU 真实存在（known_ku_ids 为 None 时 fail-closed）；
    p3 模型已知、参数绑定成功、期望含复位态与跃迁态且与模型一致、
    动作不改原状态、复位可恢复；
    p4 caveat 非空且逐条点名模型的忽略项；
    p5 不变量检查全过；
    p6 数字三标签全覆盖。
    """
    issues: list[ValidationIssue] = []
    notes: list[str] = []
    gates: dict[str, bool] = {f"p{i}": True for i in range(1, 7)}

    def fail(gate: str, issue: ValidationIssue) -> None:
        gates[gate] = False
        issues.append(issue)

    if not isinstance(spec, dict):
        fail("p1", ValidationIssue("$", "not_object", "spec must be an object"))
        return ValidationResult(False, issues, notes, gates)

    # p1：schema。
    spec_id = spec.get("id")
    if not isinstance(spec_id, str) or not _ID_RE.match(spec_id):
        fail(
            "p1",
            ValidationIssue(
                "id", "bad_id", "id must be a slug: [a-z0-9][a-z0-9_-]{0,99}"
            ),
        )
    if "verified" in spec:
        fail(
            "p1",
            ValidationIssue(
                "verified",
                "verified_field_forbidden",
                "verified is set by the server-side gate only",
            ),
        )
    for field_name in ("ku_id", "title", "lead", "caveat", "language", "model_ref"):
        if field_name not in spec:
            fail(
                "p1",
                ValidationIssue(
                    field_name, "missing_field", f"missing required field {field_name!r}"
                ),
            )
    texts: dict[str, dict[str, str] | None] = {}
    for field_name in _BILINGUAL_FIELDS:
        if field_name in spec:
            texts[field_name] = _bilingual_text(spec[field_name], field_name, issues)
    if any(v is None for v in texts.values()):
        gates["p1"] = False
    if spec.get("language") not in ("zh", "en"):
        fail(
            "p1",
            ValidationIssue(
                "language", "bad_language", "language must be 'zh' or 'en'"
            ),
        )

    # p2：锚点 KU（ku_id 可为空：不锚定具体知识点时传空字符串或缺失
    # 均视为无锚点，跳过本门；一旦给出则必须真实存在）。
    ku_id = spec.get("ku_id")
    if isinstance(ku_id, str) and ku_id.strip():
        if known_ku_ids is None:
            fail(
                "p2",
                ValidationIssue(
                    "ku_id",
                    "ku_existence_unchecked",
                    "anchor existence was not checked",
                ),
            )
        elif ku_id not in known_ku_ids:
            fail(
                "p2",
                ValidationIssue(
                    "ku_id", "ku_not_found", f"knowledge unit {ku_id!r} does not exist"
                ),
            )
    elif ku_id is not None and not isinstance(ku_id, str):
        fail(
            "p2",
            ValidationIssue("ku_id", "bad_ku_id", "ku_id must be a string"),
        )

    # p3：模型与期望。
    model: TruthModel | None = None
    bound: Mapping[str, TaggedNumber | bool | str] | None = None
    model_ref = spec.get("model_ref")
    if isinstance(model_ref, dict):
        model_name = model_ref.get("model")
        model = MODEL_REGISTRY.get(model_name) if isinstance(model_name, str) else None
        if model is None:
            fail(
                "p3",
                ValidationIssue(
                    "model_ref.model",
                    "unknown_model",
                    f"unknown truth model: {model_name!r}",
                ),
            )
        else:
            params = model_ref.get("parameters")
            if not isinstance(params, dict):
                fail(
                    "p3",
                    ValidationIssue(
                        "model_ref.parameters",
                        "bad_parameters",
                        "parameters must be an object",
                    ),
                )
            else:
                bound, bind_issues, clamped = model.bind_parameters(params)
                for msg in bind_issues:
                    fail(
                        "p3",
                        ValidationIssue("model_ref.parameters", "bind_failed", msg),
                    )
                for name in clamped:
                    notes.append(f"parameter {name!r} was clamped to its declared bound")
            if bound is not None and not any(
                i.field == "model_ref.parameters" for i in issues
            ):
                _check_expectations(model, bound, model_ref.get("expected"), issues)
                for issue in issues:
                    if issue.code in (
                        "expected_required",
                        "expected_too_few",
                        "bad_entry",
                        "bad_actions",
                        "bad_expected",
                        "model_rejected",
                        "unknown_readout",
                        "bad_expected_number",
                        "readout_not_number",
                        "expectation_mismatch",
                        "no_reset_case",
                        "no_transition_case",
                        "stochastic_not_reproducible",
                        "stochastic_no_sample",
                    ):
                        gates["p3"] = False
                try:
                    initial = model.initial_state(bound)
                    derived0 = model.derive(initial)
                    initial_copy = dict(initial)
                    state = initial
                    for entry in model_ref.get("expected") or []:
                        if not isinstance(entry, dict):
                            continue
                        for action in entry.get("actions", []) or []:
                            if isinstance(action, dict):
                                state = model.apply_action(state, action)
                    if dict(initial) != initial_copy:
                        fail(
                            "p3",
                            ValidationIssue(
                                "model",
                                "state_mutated",
                                "apply_action must not mutate its input state",
                            ),
                        )
                    if model.derive(model.initial_state(bound)) != derived0:
                        fail(
                            "p3",
                            ValidationIssue(
                                "model",
                                "reset_not_restored",
                                "reset did not restore the initial derived state",
                            ),
                        )
                except ImpossibleStateError as exc:
                    fail(
                        "p3",
                        ValidationIssue(
                            "model",
                            "model_rejected",
                            f"model rejected the bound config: {exc}",
                        ),
                    )
    elif "model_ref" in spec:
        fail(
            "p3",
            ValidationIssue(
                "model_ref", "bad_model_ref", "model_ref must be an object"
            ),
        )

    # p4：caveat 点名忽略项。
    caveat = texts.get("caveat")
    if caveat is not None:
        for lang in ("zh", "en"):
            if len(caveat[lang].strip()) < 8:
                fail(
                    "p4",
                    ValidationIssue(
                        "caveat",
                        "caveat_too_short",
                        f"caveat.{lang} must state assumptions and limits",
                    ),
                )
        if isinstance(model, PhysicsTruthModel):
            for term in model.ignored_terms():
                if term["zh"] not in caveat["zh"]:
                    fail(
                        "p4",
                        ValidationIssue(
                            "caveat",
                            "ignored_term_missing",
                            f"caveat.zh must name the ignored item {term['zh']!r}",
                        ),
                    )
                if term["en"].lower() not in caveat["en"].lower():
                    fail(
                        "p4",
                        ValidationIssue(
                            "caveat",
                            "ignored_term_missing",
                            f"caveat.en must name the ignored item {term['en']!r}",
                        ),
                    )

    # p5：不变量检查（模型已知且参数绑定成功时才跑；否则 p3 已失败，
    # 这里不重复记 fail，避免同一根因淹没门禁读数——但门禁汇总仍以
    # issues 为准，p5 在模型不可用时记 False）。
    if isinstance(model, PhysicsTruthModel) and bound is not None and not any(
        i.field == "model_ref.parameters" for i in issues
    ):
        try:
            state = model.initial_state(bound)
            _ = state
        except ImpossibleStateError:
            gates["p5"] = False
        else:
            for check in run_invariant_checks(model, bound):
                if not check.passed:
                    fail(
                        "p5",
                        ValidationIssue(
                            "invariant_checks",
                            "invariant_failed",
                            f"{check.name}: {check.detail}",
                        ),
                    )
    elif model is not None and not isinstance(model, PhysicsTruthModel):
        gates["p5"] = False
        notes.append(
            "model is not a physics truth model: no invariant checks available"
        )
    elif model is None or bound is None:
        gates["p5"] = False

    # p6：数字三标签全覆盖。
    for problem in find_untagged_numbers(spec):
        fail("p6", ValidationIssue("numbers", "untagged_number", problem))

    # 门禁汇总：以 issues 代码为准统一结算（fail() 已同步置位，这里
    # 补上 _check_expectations 追加的 issue 对 p3 的映射，见上）。
    _CODE_TO_GATE = {
        "not_object": "p1",
        "bad_id": "p1",
        "verified_field_forbidden": "p1",
        "missing_field": "p1",
        "not_bilingual": "p1",
        "missing_language": "p1",
        "bad_language": "p1",
        "bad_ku_id": "p2",
        "ku_existence_unchecked": "p2",
        "ku_not_found": "p2",
        "unknown_model": "p3",
        "bad_parameters": "p3",
        "bind_failed": "p3",
        "bad_model_ref": "p3",
        "model_rejected": "p3",
        "state_mutated": "p3",
        "reset_not_restored": "p3",
        "caveat_too_short": "p4",
        "ignored_term_missing": "p4",
        "invariant_failed": "p5",
        "untagged_number": "p6",
    }
    for issue in issues:
        gate = _CODE_TO_GATE.get(issue.code)
        if gate is not None:
            gates[gate] = False

    passed = not issues
    return ValidationResult(passed=passed, issues=issues, notes=notes, gates=gates)
