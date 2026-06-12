# Mneme · 3O 元素代码级实施规格

> **用途**：Claude Code 依据本文档写出每个 3O 元素的代码并入库。
> **完整函数签名 + 数据结构 + 逻辑约束 + 测试用例**，读完直接动手。
> **权威**：业务语义见 `MNEME_MASTER_DESIGN.md`；入库标准见 `MNEME_3O元素清单与入库SPEC.md`；3O 范式规则见 `CLAUDE.md`。
> **实施顺序**：`obase` → `oprim/types.py`(共享数据结构) → `oprim`(纯计算) → `oprim`(LLM 调用) → `oskill` → `omodul`

---

## 目录

```
§0  实施前置条件
§1  共享数据结构（oprim/types.py）
§2  obase 关键子模块
§3  oprim · 已实现规范化迁移（BKT / FSRS）
§4  oprim · 确定性求解内核（solve_* / verify_step / kernel_to_*）
§5  oprim · LLM 单调用类
§6  oprim · 学习科学 / 价值层
§7  oskill
§8  omodul
```

---

## §0 实施前置条件

```
依赖安装（pyproject.toml 需含）：
  fsrs>=5.0  sympy>=1.12  numpy>=1.26
  anthropic>=0.25  pydantic>=2.0  fastapi>=0.110

目录结构（单 repo 逻辑分层，MVP 阶段）：
  oprim/
    __init__.py   types.py   bkt.py   fsrs_engine.py
    solve_conic.py  solve_function.py  solve_derivative.py
    solve_geometry3d.py  solve_sequence.py  solve_trig.py
    solve_probability.py  verify_step.py
    kernel_viz.py    llm_oprims.py
    learning_oprims.py
  oskill/
    __init__.py   cognitive_update.py   solve_and_visualize.py
    socratic_loop.py   interleave_select.py
    generate_practice_set.py   longitudinal_pattern.py
  omodul/
    __init__.py   base.py
    analyze_paper.py   generate_lesson_page.py   practice.py
    socratic_session.py   daily_mission.py   longitudinal_analysis.py
  obase/
    __init__.py   sympy_runtime.py   provider_registry.py
    cost_tracker.py   utils.py   auth.py   oss.py
  data/
    guangdong_math_kc.py    （留 Mneme，不入主库）

__init__.py 各包必须暴露：
  __version__ = "0.1.0"
  __manifest__ = {"version": __version__, "updated_at": "ISO",
                  "elements": [{"name":…, "layer":…, "summary":…}]}
```

---

## §1 共享数据结构（oprim/types.py）

```python
# oprim/types.py
"""Mneme oprim 层共享数据结构。由所有 oprim/oskill 导入，不依赖 obase/omodul。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Literal
from pydantic import BaseModel


# ── BKT ──────────────────────────────────────────────────────────────────────
@dataclass
class KCState:
    """单个学生在单个知识点上的认知状态（BKT + 识别维度）。"""
    kc_id: str
    p_init: float = 0.20
    p_transit: float = 0.20
    p_guess: float = 0.15
    p_slip: float = 0.12
    p_mastery: Optional[float] = None       # None = 用先验 p_init
    long_term_mastery: Optional[float] = None
    last_interaction_ts: Optional[float] = None
    n_attempts: int = 0
    # 识别维度（M-G）
    p_recognition: Optional[float] = None
    p_recognition_init: float = 0.20

    def current(self) -> float:
        return self.p_mastery if self.p_mastery is not None else self.p_init

    def current_recognition(self) -> float:
        return self.p_recognition if self.p_recognition is not None \
               else self.p_recognition_init


# ── 求解内核 ──────────────────────────────────────────────────────────────────
class SolveStep(BaseModel):
    step_no: int
    latex: str                      # LaTeX 表达式
    value: Optional[str] = None     # 数值结果（若有）
    description: str = ""


class SolveResult(BaseModel):
    """所有 solve_* oprim 的统一返回类型。"""
    solvable: bool
    answer: str                     # LaTeX，不可解时为 ""
    steps: list[SolveStep] = []
    plot_data: Optional[dict] = None  # 供 kernel_to_plot2d/three 使用的源数据
    error: Optional[str] = None     # solvable=False 时的原因


class StepCheckResult(BaseModel):
    """verify_step 返回类型。"""
    valid: bool
    reason: Optional[str] = None    # invalid 时必填


# ── 图示数据 ──────────────────────────────────────────────────────────────────
class Plot2DData(BaseModel):
    """kernel_to_plot2d 返回：Mafs 可直接消费的数据格式。"""
    kc_type: str                    # "function" | "conic" | "trig" | "stat"
    traces: list[dict]              # [{type:"fn"|"point"|"segment", params:{}}]
    annotations: list[dict] = []   # [{type:"label", x, y, text}]
    x_range: tuple[float,float] = (-10.0, 10.0)
    y_range: tuple[float,float] = (-10.0, 10.0)


class Three3DData(BaseModel):
    """kernel_to_three 返回：Three.js 可直接消费的数据格式。"""
    vertices: list[list[float]]     # [[x,y,z], ...]
    edges: list[list[int]]          # [[i,j], ...] 索引对
    faces: list[list[int]] = []     # [[i,j,k], ...] 三角面
    labels: list[dict] = []         # [{text, position:[x,y,z]}]


# ── 变式题 ────────────────────────────────────────────────────────────────────
class VariantItem(BaseModel):
    """generate_variant 返回的单道变式题。"""
    kc_id: str
    question_latex: str
    answer: str                     # 由 solve_* 内核验证后填入
    solution_steps: list[SolveStep]
    plot_data: Optional[Plot2DData] = None
    kernel_verified: bool = False   # solve_* 验过答案后置 True
    difficulty: float = 0.5         # 0.0~1.0


# ── 苏格拉底 ──────────────────────────────────────────────────────────────────
class SocraticTurnResult(BaseModel):
    text: str                       # AI 输出的追问文字
    emotion_signal: Optional[str] = None  # "anxious"|"crisis"|"angry"|None
    step_verified: Optional[bool] = None  # 若本轮含 verify_step 结果
```

---

## §2 obase 关键子模块

### 2.1 obase/sympy_runtime.py

```python
# obase/sympy_runtime.py
"""sympy 求解沙箱。所有 solve_* oprim 通过此模块调用 sympy，防病态输入卡死。"""

def safe_sympify(expr: str, *, timeout_s: float = 5.0) -> "sympy.Expr":
    """将字符串安全解析为 sympy 表达式（超时则 raise TimeoutError）。"""

def run_sympy(fn: Callable, *args, timeout_s: float = 8.0, **kwargs) -> Any:
    """在受限环境中运行任意 sympy 调用。
    - 超时：raise TimeoutError
    - 内存超限（256MB）：raise MemoryError
    - 任何异常向上透传
    实现：concurrent.futures.ThreadPoolExecutor + 超时 cancel
    """

def latex(expr: "sympy.Expr") -> str:
    """sympy 表达式 → LaTeX 字符串（安全包装）。"""
```

**实现约束**：
- 使用 `concurrent.futures.ThreadPoolExecutor`，不用 `multiprocessing`（节省启动开销）。
- `timeout_s` 默认 8s，单个 test 可降到 3s。
- 禁止在沙箱内执行 `exec`/`eval` 含外部字符串拼接。

**测试**：
```python
def test_timeout():
    with pytest.raises(TimeoutError):
        run_sympy(lambda: time.sleep(100), timeout_s=1.0)

def test_valid():
    import sympy as sp
    x = sp.Symbol('x')
    result = run_sympy(sp.factor, x**2 - 1)
    assert str(result) == "(x - 1)*(x + 1)"
```

---

### 2.2 obase/provider_registry.py

```python
# obase/provider_registry.py
"""LLM / Vision provider 注册与获取（服务层启动时注册，omodul/oprim 使用）。"""
from typing import Protocol, runtime_checkable

@runtime_checkable
class LLMCaller(Protocol):
    def __call__(self, *, messages: list[dict], max_tokens: int = 1000,
                 tools: list[dict] | None = None) -> dict: ...

@runtime_checkable
class VLMCaller(Protocol):
    def __call__(self, *, prompt: str, image_b64: str,
                 response_format: str = "text") -> dict: ...

class ProviderRegistry:
    """单例（per-进程）。"""
    _instance: "ProviderRegistry | None" = None

    @classmethod
    def get(cls) -> "ProviderRegistry": ...

    def register_llm(self, name: str, caller: LLMCaller) -> None: ...
    def register_vlm(self, name: str, caller: VLMCaller) -> None: ...
    def llm(self, name: str = "default") -> LLMCaller: ...
    def vlm(self, name: str = "default") -> VLMCaller: ...
```

---

### 2.3 obase/cost_tracker.py

```python
# obase/cost_tracker.py
"""LLM 成本追踪（ContextVar，omodul 启用 cost 支柱时使用）。"""
from contextvars import ContextVar
from dataclasses import dataclass, field

@dataclass
class CostTracker:
    budget_usd: float = 5.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_usd: float = 0.0

    def record(self, *, input_t: int, output_t: int, cost_usd: float) -> None: ...
    def check_budget(self) -> None:
        """超预算 raise BudgetExceededError。"""

# 全局 ContextVar：obase.ProviderRegistry 返回的 LLMCaller 自动写入
current_cost_tracker: ContextVar["CostTracker | None"] = \
    ContextVar("cost_tracker", default=None)
```

---

### 2.4 obase/utils.py

```python
# obase/utils.py
import hashlib, json

def sha256_hash(data: str | bytes) -> str:
    """返回 64 字符 hex SHA-256。"""
    if isinstance(data, str): data = data.encode()
    return hashlib.sha256(data).hexdigest()

def canonical_json(obj: dict) -> str:
    """确定性序列化（sort_keys=True, separators=(',',':')）。"""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
```

---

## §3 oprim · 已实现规范化迁移（BKT / FSRS）

> 现有代码在 `core/bkt.py`、`core/fsrs_engine.py`。**逻辑不变**，只做三件事：
> 1. 迁入 `oprim/bkt.py`、`oprim/fsrs_engine.py`。
> 2. 函数签名全部改为 **keyword-only**（`*,` 开头）。
> 3. 补完 docstring（含 Example）并注册 `__manifest__`。

### 3.1 oprim/bkt.py（全量规范签名）

```python
def bkt_update(
    *,
    state: KCState,
    is_correct: bool,
    retrievability: float | None = None,   # FSRS 的 R；None 则用 days_since 近似
    days_since: float | None = None,       # 距上次接触天数；两者都 None 则 R=1
) -> KCState:
    """forgetting-aware BKT 更新。修改 state 并返回（in-place + return）。
    掌握度封顶 0.97，long_term_mastery 用 EMA 平滑。
    """

def classify_error(*, state: KCState) -> str:
    """答错时判定错误根因。返回 'careless' | 'dontknow'。
    careless ∝ P(L)·P(S)；dontknow ∝ (1-P(L))·(1-P(G))
    """

def predict_correct(
    *, state: KCState, retrievability: float | None = None
) -> float:
    """预测下一题答对概率（用于 AUC 评估）。
    P = P(L_eff)·(1-S) + (1-P(L_eff))·G
    """

def exp_forgetting(*, days_since: float, halflife_days: float = 7.0) -> float:
    """指数遗忘近似 R = 0.5^(days/halflife)。无 FSRS 时的备用。"""

def new_state_from_prior(*, kc_id: str, prior: dict) -> KCState:
    """从 BKT 先验字典创建 KCState。
    prior 必须含 p_init/p_transit/p_guess/p_slip。
    """
```

**测试（必须通过）**：
```python
def test_mastery_cap():
    s = new_state_from_prior(kc_id="X", prior=dict(p_init=.2,p_transit=.3,p_guess=.2,p_slip=.1))
    for _ in range(20): bkt_update(state=s, is_correct=True)
    assert s.current() <= 0.97

def test_classify_careless():
    s = new_state_from_prior(kc_id="X", prior=dict(p_init=.2,p_transit=.4,p_guess=.2,p_slip=.15))
    for _ in range(10): bkt_update(state=s, is_correct=True)
    assert classify_error(state=s) == "careless"

def test_classify_dontknow():
    s = new_state_from_prior(kc_id="X", prior=dict(p_init=.05,p_transit=.1,p_guess=.1,p_slip=.1))
    assert classify_error(state=s) == "dontknow"

def test_auc_above_random():
    # 复用 test_engine.py 的 test_auc()，AUC >= 0.65
```

---

### 3.2 oprim/fsrs_engine.py（全量规范签名）

```python
def fsrs_new_card() -> dict:
    """创建新 FSRS 记忆卡片（py-fsrs Card 序列化为 dict）。"""

def fsrs_review(
    *, card_dict: dict, rating: "Rating", now: datetime | None = None
) -> dict:
    """对卡片做一次复习，返回更新后的 card dict。"""

def fsrs_retrievability(
    *, card_dict: dict, now: datetime | None = None
) -> float:
    """计算当前可提取性 R ∈ [0,1]（此刻能回忆起的概率）。"""

def fsrs_map_rating(
    *,
    is_correct: bool,
    used_answer: bool = False,
    struggled: bool = False,
    effortless: bool = False,
) -> "Rating":
    """学生表现 → FSRS Rating（Again/Hard/Good/Easy）。
    used_answer 或 not is_correct → Again
    struggled → Hard；effortless → Easy；默认 Good
    """

def fsrs_due_date(*, card_dict: dict) -> str | None:
    """返回下次复习日期 ISO 字符串，新卡片返回 None。"""
```

**测试**：
```python
def test_review_increases_stability():
    c = fsrs_new_card()
    c2 = fsrs_review(card_dict=c, rating=Rating.Good)
    assert Card.from_dict(c2).stability > 0

def test_retrievability_new_card():
    c = fsrs_new_card()
    assert fsrs_retrievability(card_dict=c) == 1.0

def test_map_rating_used_answer():
    assert fsrs_map_rating(is_correct=False, used_answer=True) == Rating.Again
```

---

## §4 oprim · 确定性求解内核

### 4.1 共用模式（所有 solve_* 遵守）

```python
# 每个 solve_*.py 的文件结构模板
"""
oprim.solve_<kc> — <一句话简介>
在 obase.sympy_runtime 沙箱内执行 sympy，确定性给出答案。
禁止调用其他 oprim。
"""
from obase.sympy_runtime import run_sympy, latex as sym_latex
from oprim.types import SolveResult, SolveStep

def solve_<kc>(*, spec: <KcSpec>) -> SolveResult:
    """<单行简介>

    在 obase.sympy_runtime 沙箱内执行，超时返回 SolveResult(solvable=False)。
    solvable=True 时 answer 为 LaTeX，steps 含完整推导。

    Args:
        spec: <KcSpec> 题目规格

    Returns:
        SolveResult

    Raises:
        无（内部 try/except，失败 solvable=False）

    Example:
        >>> r = solve_<kc>(spec=<KcSpec>(...))
        >>> assert r.solvable
    """
    try:
        # ... sympy 计算 ...
        return SolveResult(solvable=True, answer=..., steps=..., plot_data=...)
    except Exception as e:
        return SolveResult(solvable=False, answer="", error=str(e))
```

**共同质量门（所有 solve_* 必须）**：
- ≥10 道样题自检（assert result.answer == 标准答案，标准答案人工确认）。
- 病态输入（超大幂、符号爆炸）在 `timeout_s` 内返回 `solvable=False`，不抛出。
- `plot_data` 若该 KC 支持可视化则填入（供 `kernel_to_plot2d` 消费），否则 None。

---

### 4.2 oprim/solve_conic.py

```python
from pydantic import BaseModel
from typing import Literal

class ConicSpec(BaseModel):
    conic_type: Literal["ellipse","hyperbola","parabola","circle"]
    # 椭圆/双曲线：给 a,b 或焦距、点等
    params: dict           # 灵活 KV；solve_conic 内部解析
    target: str            # 求什么："foci"|"eccentricity"|"equation"|"area"|"angle"|...

def solve_conic(*, spec: ConicSpec) -> SolveResult:
    """确定性求解圆锥曲线：椭圆/双曲线/抛物线/圆。"""
```

**样题自检（10 道）**：
```python
CONIC_CASES = [
    (ConicSpec(conic_type="ellipse", params={"a":3,"b":2}, target="foci"),
     r"(\pm\sqrt{5}, 0)"),
    (ConicSpec(conic_type="ellipse", params={"a":5,"b":4}, target="eccentricity"),
     r"\frac{3}{5}"),
    (ConicSpec(conic_type="parabola", params={"p":2}, target="focus"),
     r"(\frac{1}{2}, 0)"),
    # ... 共 10 条
]
def test_conic_cases():
    for spec, expected in CONIC_CASES:
        r = solve_conic(spec=spec)
        assert r.solvable, f"应可解: {spec}"
        assert expected in r.answer or r.answer == expected
```

---

### 4.3 oprim/solve_function.py

```python
class FunctionSpec(BaseModel):
    expression: str         # 函数表达式，如 "x**2 - 2*x + 1"
    variable: str = "x"
    domain: str | None = None  # 如 "(0, +oo)"；None 表示全实数
    target: Literal["monotonicity","parity","range","zeros",
                    "inequality_solve","max_min","image"]

def solve_function(*, spec: FunctionSpec) -> SolveResult:
    """确定性求解函数性质：单调性/奇偶性/值域/零点/不等式求解/极值。"""
```

---

### 4.4 oprim/solve_derivative.py

```python
class DerivativeSpec(BaseModel):
    expression: str         # 如 "x**3 - 3*x + 2"
    variable: str = "x"
    target: Literal["derivative","critical_points","monotonicity",
                    "extrema","second_derivative","tangent_line"]
    at_point: float | None = None  # target="tangent_line" 时必填

def solve_derivative(*, spec: DerivativeSpec) -> SolveResult:
    """确定性求导：导数计算/单调区间/极值/切线方程。"""
```

---

### 4.5 oprim/solve_geometry3d.py

```python
class Geometry3DSpec(BaseModel):
    # 用坐标向量法。顶点用字典描述
    vertices: dict[str, list[float]]  # {"A":[0,0,0], "B":[1,0,0], ...}
    target: Literal["dihedral_angle","line_plane_angle","distance_point_plane",
                    "volume","cross_section_area","normal_vector"]
    target_elements: list[str]        # 如 ["A","B","C","D"]（二面角的四点）

def solve_geometry3d(*, spec: Geometry3DSpec) -> SolveResult:
    """坐标向量法确定性求解立体几何：二面角/线面角/点面距/体积。
    plot_data 填入 Three3DData 序列化结果。
    """
```

---

### 4.6 oprim/solve_sequence.py

```python
class SequenceSpec(BaseModel):
    seq_type: Literal["arithmetic","geometric","general","recursive"]
    params: dict            # 等差：{"a1":..., "d":...}；等比：{"a1":..,"q":..}
    target: Literal["general_term","sum_n","find_n","nth_term"]
    n_value: int | None = None  # target="nth_term" 时

def solve_sequence(*, spec: SequenceSpec) -> SolveResult:
    """确定性求解数列：通项公式/前 n 项和/指定项。"""
```

---

### 4.7 oprim/solve_trig.py

```python
class TrigSpec(BaseModel):
    target: Literal["simplify","solve_equation","triangle_solve",
                    "graph_params","identity_verify"]
    expression: str | None = None   # 化简/求解时
    triangle: dict | None = None    # {"A":...,"B":...,"a":...} 解三角形时

def solve_trig(*, spec: TrigSpec) -> SolveResult:
    """确定性求解三角：化简/方程/解三角形(正余弦定理)/图象参数。"""
```

---

### 4.8 oprim/solve_probability.py

```python
class ProbabilitySpec(BaseModel):
    prob_type: Literal["classical","conditional","distribution",
                       "expectation","variance","binomial","normal_approx"]
    params: dict            # 各类型专属参数

def solve_probability(*, spec: ProbabilitySpec) -> SolveResult:
    """确定性求解概率统计：古典概型/条件概率/分布/期望方差/二项分布。"""
```

---

### 4.9 oprim/verify_step.py

```python
class StepClaim(BaseModel):
    kc_id: str
    claim_latex: str        # 学生声称成立的表达式或等式，如 "x^2-1=(x-1)(x+1)"
    context: dict = {}      # 已知条件，如 {"a":3,"b":2}

def verify_step(*, claim: StepClaim) -> StepCheckResult:
    """确定性校验学生某一步是否成立。
    对可符号验证的命题（等式/不等式/可化简表达式）用 sympy 验证。
    无法符号验证时返回 StepCheckResult(valid=False, reason="无法确定性验证")。
    禁止调用 LLM。
    """
```

**测试**：
```python
def test_verify_correct():
    r = verify_step(claim=StepClaim(kc_id="X",
        claim_latex=r"x^2-1=(x-1)(x+1)", context={}))
    assert r.valid

def test_verify_wrong():
    r = verify_step(claim=StepClaim(kc_id="X",
        claim_latex=r"x^2+1=(x+1)^2", context={}))
    assert not r.valid

def test_verify_uncertain():
    # 语言型命题无法符号验证
    r = verify_step(claim=StepClaim(kc_id="X",
        claim_latex=r"\text{因为三角形相似}", context={}))
    assert not r.valid and "无法确定性验证" in r.reason
```

---

### 4.10 oprim/kernel_viz.py

```python
def kernel_to_plot2d(*, solve_result: SolveResult, kc_id: str) -> Plot2DData | None:
    """求解结果 → 2D 图示数据（Mafs 可消费）。
    与 solve_result 同源，数值不重新计算。
    plot_data 为 None 或 kc 不支持 2D 时返回 None。
    禁止调用 LLM 或其他 oprim。
    """

def kernel_to_three(*, solve_result: SolveResult, kc_id: str) -> Three3DData | None:
    """求解结果 → 3D 顶点/边数据（Three.js 可消费）。
    仅 solve_geometry3d 的结果有意义，其余返回 None。
    """
```

**同源约束（MUST）**：图示数值必须来自 `solve_result.plot_data`（由 `solve_*` 填入），不重新计算，杜绝"图和答案对不上"。

**测试**：
```python
def test_plot2d_ellipse_consistent():
    r = solve_conic(spec=ConicSpec(conic_type="ellipse",
                                   params={"a":3,"b":2}, target="equation"))
    p = kernel_to_plot2d(solve_result=r, kc_id="GDMATH-CONIC-01")
    assert p is not None
    # 图示中的 a,b 与 solve_result 中的数值一致
    a_in_plot = [t["params"]["a"] for t in p.traces if "a" in t.get("params",{})]
    assert any(abs(v-3)<1e-6 for v in a_in_plot)
```

---

## §5 oprim · LLM 单调用类

> **共同规则**：每个函数是一次 LLM/VLM API 调用。通过 `obase.ProviderRegistry` 取 caller，不直接 import anthropic SDK。prompt 字符串放函数内（版本化）。

### 5.1–5.5 oprim/llm_oprims.py（合并在一个文件）

```python
# oprim/llm_oprims.py
"""LLM/Vision 单调用 oprim。每个函数 = 一次 API 调用。"""
from obase.provider_registry import ProviderRegistry
from oprim.types import SolveStep, VariantItem, SocraticTurnResult

# ── §5.1 ocr_paper ───────────────────────────────────────────────────────────
class PaperOCRResult(BaseModel):
    questions: list[dict]  # [{no, question_text, student_answer, correct_answer, subject}]
    raw_text: str

def ocr_paper(*, image_b64: str, subject: str = "math") -> PaperOCRResult:
    """单 Vision 调用：试卷图片 → 结构化题目列表。
    Prompt 要求：返回 JSON，字段含 no/question_text/student_answer/correct_answer。
    无法识别的题目 question_text 标注 "[OCR失败]"，不跳过。
    """
    vlm = ProviderRegistry.get().vlm()
    prompt = _OCR_PROMPT.format(subject=subject)
    raw = vlm(prompt=prompt, image_b64=image_b64, response_format="json")
    # parse + 兜底
    ...

_OCR_PROMPT = """
你是一个专业的试卷 OCR 系统。分析图片中的{subject}试卷，提取每道题目。
严格返回 JSON，结构：
{{"questions":[{{"no":"题号","question_text":"题干(LaTeX)","student_answer":"学生答案","correct_answer":"标准答案"}}]}}
无法识别的字段填 "[OCR失败]"，不要遗漏任何题号。
"""

# ── §5.2 grade_question ───────────────────────────────────────────────────────
class GradeResult(BaseModel):
    is_correct: bool
    method: Literal["kernel","llm"]  # 用了哪种批改方式
    reason: str | None = None

def grade_question(
    *,
    question_text: str,
    student_answer: str,
    correct_answer: str,
    kc_id: str | None = None,
    solve_result: "SolveResult | None" = None,  # 有内核结果时优先用
) -> GradeResult:
    """单题批改（确定性优先：有 solve_result 则与内核答案比对；否则 LLM）。
    确定性优先红线：solve_result 不为 None 且 solvable=True 时，
    必须比对 solve_result.answer，禁止直接让 LLM 给对错判断。
    """

# ── §5.3 profiler_analyze ─────────────────────────────────────────────────────
class ProfilerResult(BaseModel):
    error_type: Literal["conceptual","transfer","careless","logic_break","dontknow"]
    error_reason: str           # 一句话
    knowledge_points: list[str] # KC ID 列表
    cognitive_break_point: str  # 推导在哪步断裂
    socratic_questions: list[str]  # 3 个递进追问（不含答案）
    mastery_estimate: float        # 0.0~1.0
    parent_note: str               # 家长能听懂的一句话

def profiler_analyze(
    *,
    question_text: str,
    student_answer: str,
    correct_answer: str,
    kc_candidates: list[str],      # 可能关联的 KC ID 列表
) -> ProfilerResult:
    """单 LLM 调用：错题深度认知分析。
    Prompt 铁律：输出纯 JSON，不含 markdown fence。
    socratic_questions 三条不得含标准答案或解题步骤。
    """

_PROFILER_PROMPT = """
你是高中教育心理学专家，精通高考考纲。
分析以下错题，输出 JSON，字段：
error_type(conceptual|transfer|careless|logic_break|dontknow)
error_reason(一句话)  knowledge_points(KC ID列表)
cognitive_break_point(推导断点)  socratic_questions(3条追问，不含答案)
mastery_estimate(0.0~1.0)  parent_note(家长能懂的一句话)
题目：{question_text}
学生答案：{student_answer}  正确答案：{correct_answer}
候选KC：{kc_candidates}
"""

# ── §5.4 socratic_turn ────────────────────────────────────────────────────────
def socratic_turn(
    *,
    conversation_history: list[dict],  # [{role, content}]
    cognitive_break_point: str,
    mode: Literal["deep","mixed","sprint"],
    step_check: "StepCheckResult | None" = None,  # verify_step 的结果
    system_prompt_override: str | None = None,
) -> SocraticTurnResult:
    """单 LLM 调用：一轮苏格拉底追问。
    苏格拉底红线（MUST，写进 system prompt）：
      1. 绝不输出标准答案或完整解题步骤。
      2. 每次只问一个问题。
      3. step_check.valid=False 时，提示学生"这一步有问题，再想想"，不说哪错了。
    情绪检测：对 AI 输出扫描关键词，填 emotion_signal。
    """

_SOCRATIC_SYSTEM = {
    "deep": """你是苏格拉底式高中老师。铁律：
1. 绝不输出答案或完整步骤。2. 每次只问一个问题。3. 学生说"不会"时从最基础概念追问。
认知断点参考：{cognitive_break_point}""",
    "mixed": """苏格拉底为主，学生连续3轮卡壳可给部分提示（不给完整步骤）。
每次只问一个问题。认知断点：{cognitive_break_point}""",
    "sprint": """快速确认理解，给出解题模板要点（不做推导）。每次只问一个问题。""",
}

# ── §5.5 generate_variant ─────────────────────────────────────────────────────
class VariantSpec(BaseModel):
    kc_id: str
    difficulty: float = 0.5         # 0.0~1.0
    question_type: Literal["choice","fill","solve"]
    exam_style: str = "广东高考"

def generate_variant(*, spec: VariantSpec) -> VariantItem:
    """单 LLM 调用：按 KC 生成变式题骨架（题干 + 参数）。
    注意：此时 answer 为空，kernel_verified=False。
    调用方（generate_practice_set oskill）负责调 solve_* 填 answer，置 kernel_verified=True。
    Prompt 要求：返回 JSON，含 question_latex / answer_template（供内核填充）。
    禁止 LLM 直接给出数值答案（由内核负责）。
    """
```

---

## §6 oprim · 学习科学 / 价值层

### oprim/learning_oprims.py

```python
# oprim/learning_oprims.py
"""学习科学与价值层 oprim：recognition / effortful_gain / peer_percentile。"""
from oprim.types import KCState

# ── §6.1 recognition_update ───────────────────────────────────────────────────
def recognition_update(
    *,
    state: KCState,
    is_correct: bool,
    is_interleaved: bool,           # 是否来自交错情境（交错才训练 recognition）
) -> KCState:
    """识别维度贝叶斯更新（M-G）。
    更新 state.p_recognition（in-place + return）。
    交错情境下答对 → 提升 recognition；专项做对 → 只提升 mastery 不动 recognition；
    任何情境下答错 → 小幅降低 recognition。
    参数（hardcode 先验，与 BKT 参数分离）：
      p_transit_rec = 0.20（交错答对时的识别提升率）
      p_slip_rec = 0.08（识别退化率）
    """

# ── §6.2 compute_effortful_gain ───────────────────────────────────────────────
def compute_effortful_gain(
    *,
    struggle_score: float,          # 0.0~1.0（用时长+FSRS Hard/Again 信号综合）
    retention_delta: float,         # FSRS 稳定性 S 的提升量（正数）
) -> float:
    """难度×记忆增益指标（M-F 努力错觉对抗）。
    effortful_gain = struggle_score * log1p(retention_delta)
    返回 0.0~∞（无上限，展示时 clip 到 0~1 normalized）
    """
    import math
    return struggle_score * math.log1p(max(0.0, retention_delta))

# ── §6.3 compute_peer_percentile ──────────────────────────────────────────────
def compute_peer_percentile(
    *,
    student_mastery: float,         # 当前学生该 KC 的 long_term_mastery
    distribution: list[float],      # 同省同年级该 KC 的掌握度分布（由服务层传入）
) -> float:
    """学生掌握度在同组的百分位（0.0~1.0）。
    纯统计计算，不调用外部 IO。
    """
    if not distribution: return 0.5
    return sum(1 for x in distribution if x < student_mastery) / len(distribution)
```

**测试**：
```python
def test_recognition_interleaved():
    s = KCState(kc_id="X", p_recognition_init=0.2)
    for _ in range(5):
        recognition_update(state=s, is_correct=True, is_interleaved=True)
    assert (s.p_recognition or s.p_recognition_init) > 0.2

def test_recognition_massed_no_change():
    s = KCState(kc_id="X", p_recognition=0.3)
    for _ in range(5):
        recognition_update(state=s, is_correct=True, is_interleaved=False)
    assert abs((s.p_recognition or 0.3) - 0.3) < 1e-6

def test_effortful_gain_positive():
    g = compute_effortful_gain(struggle_score=0.8, retention_delta=5.0)
    assert g > 0

def test_percentile():
    dist = [0.1, 0.3, 0.5, 0.7, 0.9]
    p = compute_peer_percentile(student_mastery=0.6, distribution=dist)
    assert 0.6 <= p <= 0.8   # 超过 3/5 = 0.6
```

---

## §7 oskill

> **共同规则**：
> - 函数 keyword-only，stateless（无全局状态，依赖注入）。
> - docstring 必须含 "Internal oprim composition" 段列出所有组合的 oprim。
> - 不持久化（不写文件、不入库），返回纯计算结果。
> - 可受限互调 sibling oskill（深度≤2，被调 stateless）。

### 7.1 oskill/cognitive_update.py

```python
# oskill/cognitive_update.py
"""cognitive_update：forgetting-aware BKT + FSRS + recognition 统一认知更新。
纯算法，stateless。存储编排（CognitiveStore/DB 写入）由 Mneme 服务层负责。
"""
from oprim.bkt import bkt_update, classify_error
from oprim.fsrs_engine import fsrs_retrievability, fsrs_review, fsrs_map_rating
from oprim.learning_oprims import recognition_update
from oprim.types import KCState
from datetime import datetime

class CognitiveUpdateInput(BaseModel):
    state: KCState           # 当前认知状态（由调用方从存储取出传入）
    card_dict: dict          # 当前 FSRS card（由调用方从存储取出传入）
    is_correct: bool
    used_answer: bool = False
    struggled: bool = False
    effortless: bool = False
    is_interleaved: bool = False
    now: datetime | None = None

class CognitiveUpdateResult(BaseModel):
    state: KCState           # 更新后（调用方负责写回存储）
    card_dict: dict          # 更新后（调用方负责写回存储）
    error_type: str | None   # "careless"|"dontknow"|None（答对时 None）
    rating: str              # FSRS rating 名称
    effective_mastery: float # long_term_mastery × R（含遗忘）

def cognitive_update(*, input: CognitiveUpdateInput) -> CognitiveUpdateResult:
    """forgetting-aware BKT + FSRS + recognition 统一更新。

    Internal oprim composition:
    - oprim.fsrs_retrievability  (算 R)
    - oprim.bkt_update           (forgetting-aware 掌握度更新)
    - oprim.classify_error       (粗心/不会判定)
    - oprim.fsrs_review          (FSRS 卡片更新)
    - oprim.recognition_update   (识别维度更新)
    - oprim.fsrs_map_rating      (表现→Rating)

    更新顺序（MUST，与 CLAUDE.md 红线一致）：
    1. 用旧卡片算 R
    2. forgetting-aware BKT 更新（R 衰减先验）
    3. 答错则 classify_error
    4. FSRS review
    5. recognition_update
    """
    now = input.now or datetime.now(timezone.utc)
    R = fsrs_retrievability(card_dict=input.card_dict, now=now)
    bkt_update(state=input.state, is_correct=input.is_correct, retrievability=R)
    error_type = classify_error(state=input.state) if not input.is_correct else None
    rating = fsrs_map_rating(is_correct=input.is_correct, used_answer=input.used_answer,
                             struggled=input.struggled, effortless=input.effortless)
    new_card = fsrs_review(card_dict=input.card_dict, rating=rating, now=now)
    recognition_update(state=input.state, is_correct=input.is_correct,
                       is_interleaved=input.is_interleaved)
    eff = (input.state.long_term_mastery or input.state.current()) * R
    return CognitiveUpdateResult(
        state=input.state, card_dict=new_card,
        error_type=error_type, rating=rating.name, effective_mastery=eff)
```

**测试**：
```python
def test_update_order_correct():
    """答对后 error_type 为 None，rating 为 Good 默认。"""
    s = KCState(kc_id="X", p_init=0.3, p_transit=0.2, p_guess=0.2, p_slip=0.1)
    r = cognitive_update(input=CognitiveUpdateInput(
        state=s, card_dict=fsrs_new_card(), is_correct=True))
    assert r.error_type is None
    assert r.rating == "Good"
    assert r.state.current() > 0.3

def test_classify_after_mastered():
    s = KCState(kc_id="X", p_init=0.2, p_transit=0.4, p_guess=0.2, p_slip=0.15)
    for _ in range(8): bkt_update(state=s, is_correct=True)
    r = cognitive_update(input=CognitiveUpdateInput(
        state=s, card_dict=fsrs_new_card(), is_correct=False))
    assert r.error_type == "careless"
```

---

### 7.2 oskill/solve_and_visualize.py

```python
# oskill/solve_and_visualize.py
from oprim.solve_conic import solve_conic, ConicSpec
# ... 其他 solve_* 按需导入
from oprim.kernel_viz import kernel_to_plot2d, kernel_to_three
from oprim.llm_oprims import generate_svg_diagram, evaluate_diagram

class VisualizeInput(BaseModel):
    kc_id: str
    problem_spec: dict              # 对应各 solve_* 的 Spec
    prefer_3d: bool = False

class VisualizeResult(BaseModel):
    solve_result: "SolveResult"
    plot2d: "Plot2DData | None"
    three3d: "Three3DData | None"
    svg_fallback: str | None        # LLM 生成的 SVG（无内核图示时）
    self_check_passed: bool         # 三处一致自检

def solve_and_visualize(*, input: VisualizeInput) -> VisualizeResult:
    """求解 + 图示数据生成 + 同源自检。

    Internal oprim composition:
    - oprim.solve_{kc}           (确定性求解，按 kc_id 路由)
    - oprim.kernel_to_plot2d     (2D 图示数据，同源)
    - oprim.kernel_to_three      (3D 图示数据，同源，prefer_3d=True 时)
    - oprim.generate_svg_diagram (无内核图示时的 LLM 备选)
    - oprim.evaluate_diagram     (图示质量自检)

    同源自检（MUST）：
      plot2d/three3d 中的关键数值 必须来自 solve_result.plot_data，
      不重新计算。self_check_passed=False 时调用方不应展示图示。

    备选 pipeline（内核无图示时）：
      generate_svg_diagram → evaluate_diagram → 不合格重试≤2次 → 仍不合格 svg_fallback=None
    """
```

---

### 7.3 oskill/socratic_loop.py

```python
# oskill/socratic_loop.py
from oprim.llm_oprims import socratic_turn
from oprim.verify_step import verify_step, StepClaim

class SocraticLoopInput(BaseModel):
    question_text: str
    correct_answer: str
    cognitive_break_point: str
    socratic_questions: list[str]   # profiler_analyze 给出的推荐追问序列
    mode: Literal["deep","mixed","sprint"]
    max_turns: int = 20
    kc_id: str

class SocraticLoopResult(BaseModel):
    messages: list[dict]            # 完整对话 [{role, content, ts}]
    outcome: Literal["success","partial","failed","abandoned"]
    emotion_log: list[dict]         # [{turn, signal}]
    used_escape_hatch: bool
    total_turns: int

def socratic_loop(
    *,
    input: SocraticLoopInput,
    on_turn: Callable[[SocraticTurnResult], None] | None = None,  # SSE 回调
) -> SocraticLoopResult:
    """苏格拉底多轮对话引导循环（agentic oskill）。

    Internal oprim composition (agentic loop):
    - oprim.socratic_turn     (每轮追问，循环调用)
    - oprim.verify_step       (学生输入含可验证步骤时调用)

    苏格拉底红线（MUST，每轮 socratic_turn 都遵守）：
    - 不输出答案或完整步骤
    - step_check.valid=False 时提示"这一步有问题"，不说哪里错
    - 情绪 signal 出现 ≥3 次 → outcome="abandoned"，停止追问

    循环终止条件：
    - 学生输入含正确完整思路（LLM 判定）→ "success"
    - 达到 max_turns → "failed"
    - 情绪危机 ≥3 次 → "abandoned"
    - 调用方发 escape_hatch 信号 → "abandoned" + used_escape_hatch=True
    """
```

---

### 7.4 oskill/interleave_select.py

```python
# oskill/interleave_select.py
from oprim.learning_oprims import compute_effortful_gain

class InterleaveInput(BaseModel):
    due_items: list[dict]           # [{kc_id, question_id, long_term_mastery, ...}]
    confusion_pairs: list[tuple[str,str]]  # 易混淆 KC 对，如 [("GDMATH-CONIC-01","GDMATH-CONIC-02")]
    budget_minutes: int = 30
    min_mastery_for_review: float = 0.0  # 已掌握题(>0.7)穿插比例

class InterleaveResult(BaseModel):
    ordered_items: list[dict]       # 交错排布后的题序
    interleaved: bool               # 是否成功交错（池太小时可能 False）

def interleave_select(*, input: InterleaveInput) -> InterleaveResult:
    """交错练习选题算法（M-B）。纯算法，stateless。

    Internal oprim composition:
    - oprim.compute_effortful_gain  (排序权重计算)

    排布规则（MUST）：
    1. 相邻题 kc_id 不同（硬约束）
    2. confusion_pairs 中的 KC 优先相邻出现（强化辨别）
    3. mastery>0.7 的已掌握题穿插（用于检索巩固），比例约 30%
    4. 难度梯度：不连续出现 3 道以上 effective_mastery<0.3 的题
    5. 总预计时长 ≤ budget_minutes（每题按 KC 难度估算时长）

    池太小（<3 题）时 interleaved=False，按原序返回。
    """
```

**测试**：
```python
def test_no_adjacent_same_kc():
    items = [{"kc_id":"A","question_id":"q1","long_term_mastery":0.3},
             {"kc_id":"A","question_id":"q2","long_term_mastery":0.4},
             {"kc_id":"B","question_id":"q3","long_term_mastery":0.5},
             {"kc_id":"C","question_id":"q4","long_term_mastery":0.6}]
    r = interleave_select(input=InterleaveInput(due_items=items, confusion_pairs=[]))
    kcs = [x["kc_id"] for x in r.ordered_items]
    assert all(kcs[i] != kcs[i+1] for i in range(len(kcs)-1))
```

---

### 7.5 oskill/generate_practice_set.py

```python
# oskill/generate_practice_set.py
from oprim.llm_oprims import generate_variant, VariantSpec
from oprim.solve_conic import solve_conic
# ... 其他 solve_* 按需
from oprim.kernel_viz import kernel_to_plot2d

class PracticeSetInput(BaseModel):
    kc_id: str
    count: int = 3              # 出几道
    difficulty: float = 0.5
    question_type: Literal["choice","fill","solve"] = "solve"

class PracticeSetResult(BaseModel):
    items: list["VariantItem"]
    all_kernel_verified: bool   # 所有题答案都经内核验证

def generate_practice_set(*, input: PracticeSetInput) -> PracticeSetResult:
    """生成一组个性化变式题（绕版权的活题库）。

    Internal oprim composition:
    - oprim.generate_variant     (LLM 出题型骨架)
    - oprim.solve_{kc}           (内核验答，填 answer + solution_steps)
    - oprim.kernel_to_plot2d     (配图)

    确定性优先红线（MUST）：
    - solve_* 有覆盖的 kc_id，answer 必须由内核给出（kernel_verified=True）
    - 内核不可解（solvable=False）的题：丢弃该题，重新生成，最多重试 3 次
    - 所有题 kernel_verified=True 才返回 all_kernel_verified=True
    """
```

---

### 7.6 oskill/longitudinal_pattern.py

```python
# oskill/longitudinal_pattern.py

class PatternInput(BaseModel):
    student_id: str
    mastery_history: list[dict]   # [{kc_id, month, long_term_mastery, dominant_error_type}]
    min_months: int = 3           # 数据不足时不输出

class PatternResult(BaseModel):
    patterns: list[dict]          # [{type, description, confidence, suggestion}]
    insufficient_data: bool

def longitudinal_pattern(*, input: PatternInput) -> PatternResult:
    """纵向学习模式识别。

    Internal oprim composition:
    - 统计计算（无外部 oprim，内部计算历史序列）
    - oprim.socratic_turn 风格的单 LLM 调用（解读时间序列）

    规则：
    - 数据 < min_months 月：insufficient_data=True，patterns=[]，不编造
    - confidence < 0.6 的模式不输出
    - pattern_type: reasoning_chain|topic_pref|time_of_day|cross_stage
    """
```

---

## §8 omodul

### 8.1 omodul/base.py（基类，所有 omodul 继承）

```python
# omodul/base.py
"""omodul 基类。所有 omodul Config 继承 BaseConfig，遵守标准签名。"""
from pydantic import BaseModel
from typing import ClassVar, Literal, Callable
from pathlib import Path
import hashlib, json, traceback
from datetime import datetime, timezone

class BaseConfig(BaseModel):
    """所有 omodul Config 基类。"""
    llm_provider: str = "default"
    budget_usd: float = 5.0
    output_format: Literal["markdown","json","both"] = "markdown"
    overwrite: bool = True

    # 子类必须覆盖
    _omodul_name: ClassVar[str] = ""
    _omodul_version: ClassVar[str] = ""
    _fingerprint_fields: ClassVar[set[str]] = set()
    _enabled_pillars: ClassVar[set[str]] = {"fingerprint","decision_trail","report","cost"}

def build_fingerprint(config: BaseConfig, input_hash: str) -> str:
    """计算 omodul fingerprint（SHA-256，64 字符）。"""
    subset = {k: getattr(config, k) for k in sorted(config._fingerprint_fields)
              if hasattr(config, k)}
    obj = {"omodul_name": config._omodul_name,
           "omodul_version": config._omodul_version,
           "config_subset": subset, "input_hash": input_hash}
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",",":"), default=str)
        .encode()).hexdigest()

def standard_return(*, findings, status, error, fingerprint, trail,
                    report_path, cost_usd) -> dict:
    """omodul 标准返回结构。"""
    return {"findings": findings, "status": status, "error": error,
            "fingerprint": fingerprint, "decision_trail": trail,
            "report_path": report_path, "cost_usd": cost_usd}
```

---

### 8.2 omodul/analyze_paper.py

```python
# omodul/analyze_paper.py
"""analyze_paper_workflow：试卷分析全流程业务事务。"""
from omodul.base import BaseConfig, build_fingerprint, standard_return
from oskill.cognitive_update import cognitive_update, CognitiveUpdateInput

class AnalyzePaperConfig(BaseConfig):
    _omodul_name = "analyze_paper_workflow"
    _omodul_version = "0.1.0"
    _fingerprint_fields = {"subject","grade"}
    _enabled_pillars = {"fingerprint","decision_trail","report","cost"}

    subject: str = "math"
    grade: str = "高三"
    kc_priors: dict = {}            # {kc_id: {p_init,p_transit,p_guess,p_slip}}

class AnalyzePaperInput(BaseModel):
    image_b64_list: list[str]       # 试卷图片（base64）
    student_id: str                 # 仅用于 trail 记录，不进 fingerprint

class AnalyzePaperFindings(BaseModel):
    wrong_questions: list[dict]     # [{question_text,kc_id,error_type,profiler,...}]
    common_breakpoint: str | None   # 共同断点（冷启动钩子）
    cognitive_updates: list[dict]   # [{kc_id, p_mastery, error_type, ...}]
    total_questions: int
    correct_count: int

def analyze_paper_workflow(
    config: AnalyzePaperConfig,
    input_data: AnalyzePaperInput,
    output_dir: Path,
    *,
    on_step: Callable[[dict], None] | None = None,
) -> dict:
    """试卷分析全流程业务事务。

    Stage pipeline（私有 _stage_* 函数串联）：
    _stage_ocr       → ocr_paper × len(images)（并发）
    _stage_grade     → grade_question × 题数（确定性优先）
    _stage_profiler  → profiler_analyze × 错题数
    _stage_cognitive → cognitive_update × 错题数（传入 kc_priors）
    _stage_breakpoint→ 单 LLM 调用找共同断点

    失败不 raise，返回 status="failed" + error。
    启用全 4 支柱：fingerprint/trail/report/cost。
    """
```

**测试**：
```python
def test_analyze_paper_smoke(mocker):
    """smoke test，LLM 全 mock。"""
    mocker.patch("oprim.llm_oprims.ocr_paper", return_value=PaperOCRResult(
        questions=[{"no":"1","question_text":"1+1=?",
                    "student_answer":"3","correct_answer":"2","subject":"math"}],
        raw_text=""))
    mocker.patch("oprim.llm_oprims.grade_question",
                 return_value=GradeResult(is_correct=False, method="kernel"))
    mocker.patch("oprim.llm_oprims.profiler_analyze",
                 return_value=ProfilerResult(
                     error_type="careless", error_reason="粗心",
                     knowledge_points=["GDMATH-SET-01"], cognitive_break_point="",
                     socratic_questions=["q1","q2","q3"],
                     mastery_estimate=0.6, parent_note="粗心了"))
    r = analyze_paper_workflow(
        AnalyzePaperConfig(), AnalyzePaperInput(image_b64_list=["fake"],student_id="s1"),
        Path("/tmp/test_out"))
    assert r["status"] == "completed"
    assert r["fingerprint"] is not None
    assert len(r["findings"].wrong_questions) == 1
```

---

### 8.3 omodul/generate_lesson_page.py

```python
class LessonPageConfig(BaseConfig):
    _omodul_name = "generate_lesson_page"
    _omodul_version = "0.1.0"
    _fingerprint_fields = {"kc_id","question_hash"}
    _enabled_pillars = {"fingerprint","report"}

    kc_id: str
    question_hash: str              # 题目内容 hash（进 fingerprint 去重同题）

class LessonPageInput(BaseModel):
    question_text: str
    correct_answer: str
    problem_spec: dict              # 传给 solve_and_visualize

class LessonPageFindings(BaseModel):
    solve_result: dict
    plot2d: dict | None
    three3d: dict | None
    svg_fallback: str | None
    self_check_passed: bool         # 三处一致（图/答案/末步）

def generate_lesson_page(
    config: LessonPageConfig,
    input_data: LessonPageInput,
    output_dir: Path, *, on_step=None) -> dict:
    """题目→讲解页业务事务（edulab 式）。
    self_check_passed=False 时 findings 仍返回，但 report 标注"图示未通过自检"。
    """
```

---

### 8.4 omodul/practice.py

```python
class PracticeConfig(BaseConfig):
    _omodul_name = "practice_workflow"
    _omodul_version = "0.1.0"
    _fingerprint_fields = {"kc_id","difficulty","question_type","count"}
    _enabled_pillars = {"fingerprint","report"}

    kc_id: str
    count: int = 3
    difficulty: float = 0.5
    question_type: Literal["choice","fill","solve"] = "solve"

class PracticeFindings(BaseModel):
    items: list[dict]               # VariantItem 序列化
    all_kernel_verified: bool

def practice_workflow(config: PracticeConfig, input_data: None,
                      output_dir: Path, *, on_step=None) -> dict:
    """按弱点出题业务事务（绕版权的活题库）。
    fingerprint 去重：同参数不重复出同组题（TTL 1 小时）。
    """
```

---

### 8.5 omodul/socratic_session.py

```python
class SocraticConfig(BaseConfig):
    _omodul_name = "socratic_session_workflow"
    _omodul_version = "0.1.0"
    _fingerprint_fields = {}        # 每次会话唯一，不去重
    _enabled_pillars = {"decision_trail","cost"}

    mode: Literal["deep","mixed","sprint"] = "deep"
    max_turns: int = 20

class SocraticInput(BaseModel):
    question_text: str
    correct_answer: str
    kc_id: str
    profiler_result: dict           # profiler_analyze 输出

def socratic_session_workflow(
    config: SocraticConfig, input_data: SocraticInput,
    output_dir: Path, *, on_step=None) -> dict:
    """苏格拉底会话业务事务。
    on_step 用于 SSE 流式推送每轮输出。
    结束后调用方负责触发 cognitive_update 回写掌握度。
    """
```

---

### 8.6 omodul/daily_mission.py

```python
class DailyMissionConfig(BaseConfig):
    _omodul_name = "daily_mission_workflow"
    _omodul_version = "0.1.0"
    _fingerprint_fields = {"student_id_hash","date"}
    _enabled_pillars = {"decision_trail"}

    student_id_hash: str            # sha256(student_id)，不存原始 ID
    date: str                       # "YYYY-MM-DD"
    budget_minutes: int = 30
    hour_of_day: int = 20           # 当前时段（≥23 触发降级）

class DailyMissionInput(BaseModel):
    due_items: list[dict]
    all_kc_states: list[dict]
    effortful_gains: list[dict]     # 近期 compute_effortful_gain 结果
    confusion_pairs: list[tuple[str,str]]

class DailyMissionFindings(BaseModel):
    mission_type: str
    content: dict
    estimated_minutes: int
    interleaved: bool
    requires_active_recall: bool
    degraded: bool                  # hour≥23 触发降级

def daily_mission_workflow(
    config: DailyMissionConfig, input_data: DailyMissionInput,
    output_dir: Path, *, on_step=None) -> dict:
    """今日目标生成业务事务（含交错+检索约束+努力错觉）。
    hour_of_day ≥ 23：降级为 mission_type="rest"，estimated_minutes=0。
    """
```

---

## 总结：实施顺序与交付检查表

```
Phase A（obase + oprim 纯计算）：
  □ obase: sympy_runtime / provider_registry / cost_tracker / utils
  □ oprim/types.py（共享数据结构）
  □ oprim/bkt.py（规范化迁移）       → pytest tests/test_bkt.py ✓
  □ oprim/fsrs_engine.py（规范化）   → pytest tests/test_fsrs.py ✓
  □ oprim/kernel_viz.py              → 同源自检测试 ✓

Phase B（oprim 求解内核，依赖 sympy_runtime）：
  □ solve_conic → 10 样题自检 ✓
  □ solve_function / solve_derivative / verify_step
  □ solve_geometry3d / solve_sequence / solve_trig / solve_probability

Phase C（oprim LLM 类，依赖 provider_registry）：
  □ llm_oprims.py（ocr/grade/profiler/socratic_turn/generate_variant）
  □ learning_oprims.py（recognition/effortful_gain/peer_percentile）

Phase D（oskill，依赖 Phase A-C）：
  □ cognitive_update → 更新顺序红线测试 ✓
  □ solve_and_visualize → 同源自检测试 ✓
  □ socratic_loop → 不泄露答案红线测试 ✓
  □ interleave_select → 相邻 KC 不同测试 ✓
  □ generate_practice_set → kernel_verified=True 测试 ✓
  □ longitudinal_pattern

Phase E（omodul，依赖 Phase D）：
  □ omodul/base.py（BaseConfig + build_fingerprint）
  □ analyze_paper / generate_lesson_page / practice
  □ socratic_session / daily_mission / longitudinal_analysis

每个 Phase 完成后运行：
  pytest -q && ruff check . && mypy oprim oskill omodul obase
  python3 -c "import oprim; print(oprim.__manifest__['elements'])"
```

**入库红线最终检查（CC 完成全部后）**：
```bash
# 命名红线：无项目前缀
grep -r "mneme_\|gdmath_" oprim/ oskill/ omodul/ && echo "❌ 发现项目前缀" || echo "✓"
# 学科耦合红线：主库源码不含领域数据
grep -r "广东\|GDMATH\|高考" oprim/ oskill/ omodul/ && echo "❌ 学科耦合" || echo "✓"
# manifest 完整
python3 -c "import oprim,oskill,omodul,obase; [print(p.__manifest__) for p in [oprim,oskill,omodul,obase]]"
```
