"""obase.sympy_runtime — Sandboxed SymPy execution environment.

Provides a safe, isolated runtime for evaluating SymPy expressions with
resource limits and restricted function access. Used by oprim math-solving
elements (M-B batch) as the deterministic computation backbone.

Version: obase v0.13.0
"""

from __future__ import annotations

import ast
import multiprocessing as mp
import queue as _queue
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import ConfigDict


class SymPyRuntimeError(Exception):
    """Base exception for sympy_runtime errors."""


class SymPyTimeoutError(SymPyRuntimeError):
    """Raised when execution exceeds time limit."""


class SymPyMemoryError(SymPyRuntimeError):
    """Raised when execution exceeds memory limit."""


class SymPyRestrictedError(SymPyRuntimeError):
    """Raised when code uses restricted/forbidden operations."""


class SymPyEvalError(SymPyRuntimeError):
    """Raised when expression evaluation fails."""


def _read_rss_bytes(pid: int) -> int | None:
    """Read a process's current resident set size from /proc, in bytes.

    Returns ``None`` on non-Linux platforms or if the process has already
    exited (both are treated as "can't measure", not "zero usage").
    """
    try:
        with open(f"/proc/{pid}/status", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (FileNotFoundError, ProcessLookupError, ValueError, OSError):
        return None
    return None


@dataclass(frozen=True)
class RuntimeConfig:
    """Configuration for the sympy sandbox runtime."""

    timeout_seconds: float = 5.0
    max_memory_bytes: int = 64 * 1024 * 1024  # 64 MB
    max_expression_depth: int = 50
    max_string_length: int = 10000
    allowed_modules: tuple[str, ...] = ("sympy",)
    forbidden_names: tuple[str, ...] = (
        "exec",
        "eval",
        "compile",
        "import",
        "__import__",
        "globals",
        "locals",
        "vars",
        "dir",
        "getattr",
        "setattr",
        "delattr",
        "open",
        "os",
        "sys",
        "subprocess",
        "shutil",
        "pathlib",
    )

    model_config = ConfigDict(frozen=True)


@dataclass(frozen=True)
class EvalResult:
    """Result of a sympy expression evaluation."""

    value: Any
    expr_str: str
    result_str: str
    success: bool = True
    error: str | None = None
    wall_time_ms: float = 0.0

    model_config = ConfigDict(frozen=True)


class _SafeVisitor(ast.NodeVisitor):
    """AST visitor that rejects forbidden operations."""

    def __init__(self, config: RuntimeConfig) -> None:
        self._config = config
        self._depth = 0

    def visit(self, node: ast.AST) -> Any:
        self._depth += 1
        if self._depth > self._config.max_expression_depth:
            raise SymPyRestrictedError(
                f"Expression depth {self._depth} exceeds limit "
                f"{self._config.max_expression_depth}"
            )
        try:
            return super().visit(node)
        finally:
            self._depth -= 1

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            mod = alias.name.split(".")[0]
            if mod not in self._config.allowed_modules:
                raise SymPyRestrictedError(
                    f"Import of '{mod}' is not allowed. "
                    f"Allowed: {self._config.allowed_modules}"
                )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            mod = node.module.split(".")[0]
            if mod not in self._config.allowed_modules:
                raise SymPyRestrictedError(
                    f"Import from '{node.module}' is not allowed. "
                    f"Allowed: {self._config.allowed_modules}"
                )

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in (
            "exec",
            "eval",
            "compile",
            "__import__",
            "open",
            "globals",
            "locals",
            "vars",
            "getattr",
            "setattr",
            "delattr",
        ):
            raise SymPyRestrictedError(
                f"Call to '{node.func.id}' is not allowed in sandbox"
            )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in self._config.forbidden_names:
            raise SymPyRestrictedError(f"Name '{node.id}' is forbidden in sandbox")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_"):
            raise SymPyRestrictedError(
                f"Private attribute access '{node.attr}' is forbidden"
            )
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        raise SymPyRestrictedError(
            "Function definitions are not allowed in sandbox expressions"
        )

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        raise SymPyRestrictedError(
            "Async function definitions are not allowed in sandbox expressions"
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        raise SymPyRestrictedError(
            "Class definitions are not allowed in sandbox expressions"
        )

    def visit_For(self, node: ast.For) -> None:
        raise SymPyRestrictedError("For loops are not allowed in sandbox expressions")

    def visit_While(self, node: ast.While) -> None:
        raise SymPyRestrictedError("While loops are not allowed in sandbox expressions")

    def visit_With(self, node: ast.With) -> None:
        raise SymPyRestrictedError(
            "With statements are not allowed in sandbox expressions"
        )

    def visit_Lambda(self, node: ast.Lambda) -> None:
        raise SymPyRestrictedError(
            "Lambda expressions are not allowed in sandbox expressions"
        )


class SymPyRuntime:
    """Sandboxed SymPy execution environment.

    Provides safe evaluation of SymPy expressions with configurable resource
    limits. All expressions are AST-validated before execution to prevent
    injection attacks and forbidden operations.

    Usage:
        runtime = SymPyRuntime()
        result = runtime.evaluate("x**2 + 2*x + 1", {"x": 3})
        # result.value == 16
        result = runtime.solve("x**2 - 4", "x")
        # result.value == [-2, 2]
    """

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self._config = config or RuntimeConfig()
        self._sympy = None

    @property
    def _sympy_module(self) -> Any:
        """Lazy-load sympy to avoid import overhead."""
        if self._sympy is None:
            try:
                import sympy as sp

                self._sympy = sp
            except ImportError:
                raise SymPyRuntimeError(
                    "sympy is not installed. Install with: pip install sympy"
                )
        return self._sympy

    def _validate_ast(self, code: str) -> ast.Expression:
        """Parse and validate the expression AST."""
        if len(code) > self._config.max_string_length:
            raise SymPyRestrictedError(
                f"Expression length {len(code)} exceeds limit "
                f"{self._config.max_string_length}"
            )
        # Parse in exec mode first to catch statement-level forbidden constructs
        # (import, for, def, class, etc.) which are syntax errors in eval mode.
        try:
            tree_exec = ast.parse(code, mode="exec")
        except SyntaxError as exc:
            raise SymPyEvalError(f"Syntax error: {exc}") from exc

        # Validate the exec-mode tree with our safety visitor
        visitor = _SafeVisitor(self._config)
        visitor.visit(tree_exec)

        # Now parse in eval mode for actual execution
        try:
            tree = ast.parse(code, mode="eval")
        except SyntaxError as exc:
            raise SymPyEvalError(f"Syntax error: {exc}") from exc

        return tree

    def _make_namespace(
        self, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Build the safe namespace for evaluation."""
        sp = self._sympy_module
        ns: dict[str, Any] = {
            # Core sympy objects
            "Symbol": sp.Symbol,
            "symbols": sp.symbols,
            "Integer": sp.Integer,
            "Rational": sp.Rational,
            "Float": sp.Float,
            "pi": sp.pi,
            "E": sp.E,
            "I": sp.I,
            "oo": sp.oo,
            "zoo": sp.zoo,
            "nan": sp.nan,
            "S": sp.S,
            # Common functions
            "sqrt": sp.sqrt,
            "abs": sp.Abs,
            "exp": sp.exp,
            "log": sp.log,
            "ln": sp.ln,
            "sin": sp.sin,
            "cos": sp.cos,
            "tan": sp.tan,
            "asin": sp.asin,
            "acos": sp.acos,
            "atan": sp.atan,
            "sinh": sp.sinh,
            "cosh": sp.cosh,
            "tanh": sp.tanh,
            "factorial": sp.factorial,
            "gamma": sp.gamma,
            "diff": sp.diff,
            "integrate": sp.integrate,
            "simplify": sp.simplify,
            "expand": sp.expand,
            "factor": sp.factor,
            "cancel": sp.cancel,
            "apart": sp.apart,
            "together": sp.together,
            "collect": sp.collect,
            "solve": sp.solve,
            "dsolve": sp.dsolve,
            "series": sp.series,
            "limit": sp.limit,
            "Sum": sp.Sum,
            "Product": sp.Product,
            "Integral": sp.Integral,
            "Derivative": sp.Derivative,
            "Eq": sp.Eq,
            "Ne": sp.Ne,
            "Gt": sp.Gt,
            "Lt": sp.Lt,
            "Ge": sp.Ge,
            "Le": sp.Le,
            "And": sp.And,
            "Or": sp.Or,
            "Not": sp.Not,
            "Matrix": sp.Matrix,
            "eye": sp.eye,
            "zeros": sp.zeros,
            "ones": sp.ones,
            "diag": sp.diag,
            "det": sp.det,
            "trace": sp.trace,
            "Transpose": sp.Transpose,
            "Inverse": sp.Inverse,
            "Poly": sp.Poly,
            "roots": sp.roots,
            "real_roots": sp.real_roots,
            "nroots": sp.nroots,
            "count_roots": sp.count_roots,
            "factorint": sp.factorint,
            "isprime": sp.isprime,
            "gcd": sp.gcd,
            "lcm": sp.lcm,
            "mod_inverse": sp.mod_inverse,
            "binomial": sp.binomial,
            "bell": sp.bell,
            "fibonacci": sp.fibonacci,
            "bernoulli": sp.bernoulli,
            "harmonic": sp.harmonic,
            "Wild": sp.Wild,
            "WildFunction": sp.WildFunction,
        }
        if variables:
            for name, val in variables.items():
                if isinstance(val, sp.Basic):
                    ns[name] = val
                else:
                    ns[name] = val
        return ns

    def _run_with_timeout(
        self, func: Callable[[], Any], timeout: float | None = None
    ) -> Any:
        """Execute ``func`` under a hard, OS-enforced timeout.

        The computation runs in a forked child process so that even CPU-bound
        SymPy operations stuck inside C-level code (which never yield to the
        Python interpreter) can be forcibly killed with SIGTERM and, if needed,
        SIGKILL. This is the deterministic 沙箱红线 guarantee: a pathological
        input *must* be killed within the deadline.

        Returns ``func()``'s result (transported back via a pickle queue), or
        raises :class:`SymPyTimeoutError` if the deadline is exceeded. Any
        exception raised by ``func`` is re-raised in the parent process.

        On platforms without ``fork`` (non-Unix), falls back to an in-process
        ``SIGALRM`` guard which is only effective on the main thread.
        """
        import time as _time

        effective = timeout if timeout is not None else self._config.timeout_seconds

        try:
            ctx = mp.get_context("fork")
        except ValueError:
            return self._run_with_alarm(func, effective)

        result_q: Any = ctx.Queue()
        max_memory_bytes = self._config.max_memory_bytes

        def _worker() -> None:
            try:
                status, payload = "ok", func()
            except BaseException as exc:  # noqa: BLE001 - propagate to parent
                status, payload = "err", exc

            try:
                result_q.put((status, payload))
            except Exception:
                result_q.put(
                    ("err", SymPyRuntimeError(f"{type(payload).__name__}: {payload}"))
                )

        proc = ctx.Process(target=_worker, daemon=True)
        proc.start()

        # Memory is bounded by polling the *resident* (physical) growth of
        # the child from the parent side, not an in-child rlimit. This
        # process is forked from a long-lived host (e.g. the API server),
        # so the child inherits the parent's full virtual address space
        # (VmSize) immediately on fork — a real production process easily
        # sits at 1GB+ VSZ before any sympy code runs. RLIMIT_AS counts
        # *virtual* address space, so any fixed ceiling below that baseline
        # would make every single call fail immediately, not just
        # pathological ones. Resident memory (VmRSS) growth relative to the
        # child's own post-fork baseline is what actually reflects a
        # computation blowing up, independent of however big the host
        # process happens to be.
        baseline_rss = _read_rss_bytes(proc.pid) if max_memory_bytes else None

        deadline = _time.monotonic() + effective
        payload: tuple[str, Any] | None = None
        memory_exceeded = False
        while True:
            remaining = deadline - _time.monotonic()
            if remaining <= 0:
                break
            try:
                payload = result_q.get(timeout=min(remaining, 0.05))
                break
            except _queue.Empty:
                if not proc.is_alive():
                    break
                if max_memory_bytes and baseline_rss is not None:
                    rss = _read_rss_bytes(proc.pid)
                    if rss is not None and (rss - baseline_rss) > max_memory_bytes:
                        memory_exceeded = True
                        break

        if memory_exceeded:
            proc.terminate()
            proc.join(0.5)
            if proc.is_alive():
                proc.kill()
                proc.join()
            raise SymPyMemoryError(
                f"Execution exceeded memory limit of {max_memory_bytes} bytes "
                f"(process killed)"
            )

        if payload is None:
            # Either the deadline passed while the child was still running, or
            # the child died without producing a result.
            if proc.is_alive():
                proc.terminate()
                proc.join(0.5)
                if proc.is_alive():
                    proc.kill()
                    proc.join()
                raise SymPyTimeoutError(
                    f"Execution exceeded timeout of {effective}s (process killed)"
                )
            proc.join()
            exitcode = proc.exitcode
            if exitcode is not None and exitcode < 0:
                raise SymPyMemoryError(
                    f"Execution subprocess was killed by signal {-exitcode} "
                    f"(likely exceeded memory limit of {max_memory_bytes} bytes)"
                )
            raise SymPyRuntimeError(
                "SymPy computation subprocess terminated without a result"
            )

        proc.join(1.0)
        if proc.is_alive():
            proc.terminate()

        status, value = payload
        if status == "err":
            raise value
        return value

    def _run_with_alarm(self, func: Callable[[], Any], effective: float) -> Any:
        """Best-effort in-process timeout via SIGALRM (main thread only).

        Used only when ``fork`` is unavailable. SIGALRM can only interrupt the
        main thread, so if called from a worker thread no hard timeout can be
        enforced and the function is run uninterrupted.
        """
        import signal as _signal
        import threading as _threading

        if _threading.current_thread() is not _threading.main_thread():
            return func()

        def _handler(signum: int, frame: Any) -> None:
            raise SymPyTimeoutError(f"Execution exceeded timeout of {effective}s")

        old_handler = _signal.signal(_signal.SIGALRM, _handler)
        _signal.setitimer(_signal.ITIMER_REAL, effective)
        try:
            return func()
        finally:
            _signal.setitimer(_signal.ITIMER_REAL, 0)
            _signal.signal(_signal.SIGALRM, old_handler)

    @staticmethod
    def _auto_symbol_names(expression: str) -> set[str]:
        """Single-letter free-variable name detection — shared by
        simplify_expr()/to_latex()/evaluate_auto() (previously duplicated
        inline in each, now one implementation)."""
        import re

        return set(re.findall(r"\b([a-zA-Z])\b", expression))

    def evaluate_auto(
        self,
        expression: str,
        variables: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        simplify_result: bool = True,
    ) -> EvalResult:
        """Evaluate a SymPy expression safely, auto-declaring any
        single-letter free variable found in the string as a symbol (same
        auto-detection already used by simplify_expr()/to_latex()), merged
        with any explicitly pre-declared ``variables`` (which take
        precedence — e.g. a caller that already knows its primary variable
        still gets auto-detection for any *other* letters the expression
        turns out to reference).

        For callers that don't know all their variable names in advance —
        e.g. parsing an arbitrary external-input expression/equation
        (S0-W5: verify_step/grade_question/compute_feedback/
        socratic_service/paper_grading all needed exactly this and were,
        before this fix, calling raw sp.sympify()/parse_expr() directly
        instead).
        """
        merged = dict(variables or {})
        for name in self._auto_symbol_names(expression):
            if name not in merged:
                merged[name] = name
        return self.evaluate(
            expression, merged, timeout=timeout, simplify_result=simplify_result
        )

    def run_isolated(
        self, func: Callable[[], Any], *, timeout: float | None = None
    ) -> Any:
        """Run a plain Python callable under the same fork+timeout+memory-limit
        sandbox as expression evaluation (S0).

        For oprim kernels that compute with plain Python/math rather than a
        SymPy expression string (so there is nothing to AST-validate), but
        still need the timeout/memory DoS guarantees the sandbox provides
        against pathological numeric inputs (e.g. huge combinatorial n/k).
        Exceptions raised by ``func`` propagate to the caller unchanged.
        """
        return self._run_with_timeout(func, timeout)

    def evaluate(
        self,
        expression: str,
        variables: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        simplify_result: bool = True,
    ) -> EvalResult:
        """Evaluate a SymPy expression safely.

        Args:
            expression: The expression string to evaluate (e.g., "x**2 + 1").
            variables: Optional dict mapping variable names to values or SymPy symbols.
            timeout: Optional override for execution timeout.
            simplify_result: Whether to simplify the result (default True).

        Returns:
            EvalResult with the computed value and metadata.
        """
        import time

        start = time.monotonic()
        try:
            tree = self._validate_ast(expression)
            sp = self._sympy_module

            # Create symbols for any string variable names
            ns = self._make_namespace(variables)

            # Auto-create symbols for single-letter variable names
            if variables:
                for name, val in variables.items():
                    if isinstance(val, str):
                        ns[name] = sp.Symbol(val)

            def _compute() -> Any:
                code = compile(tree, "<sympy_expr>", "eval")
                return eval(code, {"__builtins__": {}}, ns)

            raw_value = self._run_with_timeout(_compute, timeout)

            # A bare-literal expression (e.g. "3", "2.5") evaluates via
            # plain Python eval() to a native int/float, not a sympy object
            # — unlike sp.sympify(), which always promotes literals to
            # sympy.Integer/Float. Coerce here so callers can reliably use
            # sympy attributes (.is_number/.is_Symbol/.free_symbols/etc) on
            # *any* successful result, not just ones that happened to
            # reference a symbol/function. Safe: this sympifies an
            # already-computed native Python number, not a string — no
            # parsing/eval of untrusted input happens in this call.
            if isinstance(raw_value, (int, float, complex)):
                raw_value = sp.sympify(raw_value)

            # Simplify if requested
            if simplify_result and hasattr(raw_value, "simplify"):
                result_value = raw_value.simplify()
            else:
                result_value = raw_value

            result_str = str(result_value)
            wall_time = (time.monotonic() - start) * 1000

            return EvalResult(
                value=result_value,
                expr_str=expression,
                result_str=result_str,
                success=True,
                wall_time_ms=wall_time,
            )
        except SymPyEvalError as exc:
            wall_time = (time.monotonic() - start) * 1000
            return EvalResult(
                value=None,
                expr_str=expression,
                result_str="",
                success=False,
                error=str(exc),
                wall_time_ms=wall_time,
            )
        except (SymPyRuntimeError, SymPyTimeoutError):
            wall_time = (time.monotonic() - start) * 1000
            raise
        except Exception as exc:
            wall_time = (time.monotonic() - start) * 1000
            return EvalResult(
                value=None,
                expr_str=expression,
                result_str="",
                success=False,
                error=str(exc),
                wall_time_ms=wall_time,
            )

    def solve_equation(
        self,
        equation: str,
        variable: str,
        *,
        timeout: float | None = None,
    ) -> EvalResult:
        """Solve an equation for a given variable.

        Args:
            equation: The equation string (e.g., "x**2 - 4").
            variable: The variable to solve for.
            timeout: Optional override for execution timeout.

        Returns:
            EvalResult with the solution set.
        """
        import time

        start = time.monotonic()
        try:
            sp = self._sympy_module
            x = sp.Symbol(variable)

            tree = self._validate_ast(equation)
            ns = self._make_namespace({variable: x})

            def _compute() -> Any:
                code = compile(tree, "<sympy_eq>", "eval")
                lhs = eval(code, {"__builtins__": {}}, ns)
                # Solve lhs == 0
                return sp.solve(lhs, x)

            solutions = self._run_with_timeout(_compute, timeout)

            result_str = str(solutions)
            wall_time = (time.monotonic() - start) * 1000

            return EvalResult(
                value=solutions,
                expr_str=equation,
                result_str=result_str,
                success=True,
                wall_time_ms=wall_time,
            )
        except (SymPyRuntimeError, SymPyTimeoutError):
            raise
        except Exception as exc:
            wall_time = (time.monotonic() - start) * 1000
            return EvalResult(
                value=None,
                expr_str=equation,
                result_str="",
                success=False,
                error=str(exc),
                wall_time_ms=wall_time,
            )

    def differentiate(
        self,
        expression: str,
        variable: str,
        order: int = 1,
        *,
        timeout: float | None = None,
    ) -> EvalResult:
        """Compute the derivative of an expression.

        Args:
            expression: The expression to differentiate.
            variable: The variable to differentiate with respect to.
            order: The order of differentiation (default 1).
            timeout: Optional override for execution timeout.

        Returns:
            EvalResult with the derivative.
        """
        import time

        start = time.monotonic()
        try:
            sp = self._sympy_module
            x = sp.Symbol(variable)

            tree = self._validate_ast(expression)
            ns = self._make_namespace({variable: x})

            def _compute() -> Any:
                code = compile(tree, "<sympy_diff>", "eval")
                expr = eval(code, {"__builtins__": {}}, ns)
                return sp.diff(expr, x, order)

            result_value = self._run_with_timeout(_compute, timeout)

            result_str = str(result_value)
            wall_time = (time.monotonic() - start) * 1000

            return EvalResult(
                value=result_value,
                expr_str=expression,
                result_str=result_str,
                success=True,
                wall_time_ms=wall_time,
            )
        except (SymPyRuntimeError, SymPyTimeoutError):
            raise
        except Exception as exc:
            wall_time = (time.monotonic() - start) * 1000
            return EvalResult(
                value=None,
                expr_str=expression,
                result_str="",
                success=False,
                error=str(exc),
                wall_time_ms=wall_time,
            )

    def integrate_expr(
        self,
        expression: str,
        variable: str,
        lower: float | None = None,
        upper: float | None = None,
        *,
        timeout: float | None = None,
    ) -> EvalResult:
        """Compute the integral of an expression.

        Args:
            expression: The expression to integrate.
            variable: The variable to integrate with respect to.
            lower: Lower bound for definite integral (None for indefinite).
            upper: Upper bound for definite integral (None for indefinite).
            timeout: Optional override for execution timeout.

        Returns:
            EvalResult with the integral.
        """
        import time

        start = time.monotonic()
        try:
            sp = self._sympy_module
            x = sp.Symbol(variable)

            tree = self._validate_ast(expression)
            ns = self._make_namespace({variable: x})

            def _compute() -> Any:
                code = compile(tree, "<sympy_int>", "eval")
                expr = eval(code, {"__builtins__": {}}, ns)
                if lower is not None and upper is not None:
                    return sp.integrate(expr, (x, lower, upper))
                return sp.integrate(expr, x)

            result_value = self._run_with_timeout(_compute, timeout)

            result_str = str(result_value)
            wall_time = (time.monotonic() - start) * 1000

            return EvalResult(
                value=result_value,
                expr_str=expression,
                result_str=result_str,
                success=True,
                wall_time_ms=wall_time,
            )
        except (SymPyRuntimeError, SymPyTimeoutError):
            raise
        except Exception as exc:
            wall_time = (time.monotonic() - start) * 1000
            return EvalResult(
                value=None,
                expr_str=expression,
                result_str="",
                success=False,
                error=str(exc),
                wall_time_ms=wall_time,
            )

    def simplify_expr(
        self,
        expression: str,
        *,
        timeout: float | None = None,
    ) -> EvalResult:
        """Simplify a SymPy expression.

        Args:
            expression: The expression to simplify.
            timeout: Optional override for execution timeout.

        Returns:
            EvalResult with the simplified expression.
        """
        import time

        start = time.monotonic()
        try:
            sp = self._sympy_module

            tree = self._validate_ast(expression)
            ns = self._make_namespace()

            for name in self._auto_symbol_names(expression):
                if name not in ns:
                    ns[name] = sp.Symbol(name)

            def _compute() -> Any:
                code = compile(tree, "<sympy_simplify>", "eval")
                expr = eval(code, {"__builtins__": {}}, ns)
                return sp.simplify(expr)

            result_value = self._run_with_timeout(_compute, timeout)

            result_str = str(result_value)
            wall_time = (time.monotonic() - start) * 1000

            return EvalResult(
                value=result_value,
                expr_str=expression,
                result_str=result_str,
                success=True,
                wall_time_ms=wall_time,
            )
        except (SymPyRuntimeError, SymPyTimeoutError):
            raise
        except Exception as exc:
            wall_time = (time.monotonic() - start) * 1000
            return EvalResult(
                value=None,
                expr_str=expression,
                result_str="",
                success=False,
                error=str(exc),
                wall_time_ms=wall_time,
            )

    def to_latex(
        self,
        expression: str,
        *,
        timeout: float | None = None,
    ) -> EvalResult:
        """Convert a SymPy expression to LaTeX string.

        Args:
            expression: The expression to convert.
            timeout: Optional override for execution timeout.

        Returns:
            EvalResult with the LaTeX string.
        """
        import time

        start = time.monotonic()
        try:
            sp = self._sympy_module

            tree = self._validate_ast(expression)
            ns = self._make_namespace()

            for name in self._auto_symbol_names(expression):
                if name not in ns:
                    ns[name] = sp.Symbol(name)

            def _compute() -> Any:
                code = compile(tree, "<sympy_latex>", "eval")
                expr = eval(code, {"__builtins__": {}}, ns)
                return sp.latex(expr)

            result_value = self._run_with_timeout(_compute, timeout)

            wall_time = (time.monotonic() - start) * 1000

            return EvalResult(
                value=result_value,
                expr_str=expression,
                result_str=result_value,
                success=True,
                wall_time_ms=wall_time,
            )
        except (SymPyRuntimeError, SymPyTimeoutError):
            raise
        except Exception as exc:
            wall_time = (time.monotonic() - start) * 1000
            return EvalResult(
                value=None,
                expr_str=expression,
                result_str="",
                success=False,
                error=str(exc),
                wall_time_ms=wall_time,
            )


# Module-level convenience instance
_default_runtime: SymPyRuntime | None = None


def get_runtime(config: RuntimeConfig | None = None) -> SymPyRuntime:
    """Get or create the module-level default SymPy runtime."""
    global _default_runtime
    if config is not None or _default_runtime is None:
        _default_runtime = SymPyRuntime(config)
    return _default_runtime


def evaluate(
    expression: str,
    variables: dict[str, Any] | None = None,
    *,
    timeout: float | None = None,
    simplify_result: bool = True,
) -> EvalResult:
    """Convenience function using the default runtime."""
    return get_runtime().evaluate(
        expression, variables, timeout=timeout, simplify_result=simplify_result
    )


def solve(
    equation: str,
    variable: str,
    *,
    timeout: float | None = None,
) -> EvalResult:
    """Convenience function using the default runtime."""
    return get_runtime().solve_equation(equation, variable, timeout=timeout)


def run_isolated(func: Callable[[], Any], *, timeout: float | None = None) -> Any:
    """Convenience function using the default runtime."""
    return get_runtime().run_isolated(func, timeout=timeout)


def diff(
    expression: str,
    variable: str,
    order: int = 1,
    *,
    timeout: float | None = None,
) -> EvalResult:
    """Convenience function using the default runtime."""
    return get_runtime().differentiate(expression, variable, order, timeout=timeout)


def integrate(
    expression: str,
    variable: str,
    lower: float | None = None,
    upper: float | None = None,
    *,
    timeout: float | None = None,
) -> EvalResult:
    """Convenience function using the default runtime."""
    return get_runtime().integrate_expr(
        expression, variable, lower, upper, timeout=timeout
    )


def simplify(
    expression: str,
    *,
    timeout: float | None = None,
) -> EvalResult:
    """Convenience function using the default runtime."""
    return get_runtime().simplify_expr(expression, timeout=timeout)


def latex(
    expression: str,
    *,
    timeout: float | None = None,
) -> EvalResult:
    """Convenience function using the default runtime."""
    return get_runtime().to_latex(expression, timeout=timeout)


def run_sympy(
    expression: str,
    variables: dict[str, Any] | None = None,
    *,
    timeout: float | None = None,
) -> EvalResult:
    """Alias for evaluate() — sandboxed SymPy expression runner."""
    return evaluate(expression, variables, timeout=timeout)
