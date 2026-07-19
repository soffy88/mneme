"""
S0-2 验收：RuntimeConfig.max_memory_bytes 必须真正 enforce，不能是纸面限制。

加固前：obase/sympy_runtime.py 声明了 max_memory_bytes 字段，但 fork 子进程里
从未调用任何 setrlimit/cgroup 之类的真实内存限制机制——文档写的 64MB 上限，
实际是不设防的（子进程能吃多少内存就吃多少，唯一的兜底是 timeout）。这条测试
直接证明：喂一个真正会超过给定内存上限的计算，断言 (1) 真的被杀，不是跑完；
(2) 抛出的是 SymPyMemoryError，不是被误判成 SymPyTimeoutError 或吞掉不报错；
(3) 在远小于 timeout 的时间内返回，证明是内存墙杀的，不是凑巧撞上超时墙。
"""

from __future__ import annotations

import time

import pytest

from obase.sympy_runtime import RuntimeConfig, SymPyMemoryError, SymPyRuntime


def _allocate_far_past_limit() -> int:
    """确定性地分配远超设定内存上限的内存——用 bytearray 直接吃物理/虚拟
    地址空间，不依赖 sympy 内部行为是否恰好吃内存，避免测试 flaky。"""
    chunks = []
    for _ in range(50):  # 50 * 10MB = 500MB，远超下面配置的 32MB 上限
        chunks.append(bytearray(10 * 1024 * 1024))
    return len(chunks)


def test_memory_limit_actually_kills_over_limit_execution():
    rt = SymPyRuntime(
        RuntimeConfig(timeout_seconds=5.0, max_memory_bytes=32 * 1024 * 1024)
    )
    start = time.monotonic()
    with pytest.raises(SymPyMemoryError):
        rt.run_isolated(_allocate_far_past_limit)
    elapsed = time.monotonic() - start
    # 必须是内存墙杀的，不是等到 timeout 才被杀——远小于配置的 5s 超时
    assert elapsed < 2.0
    print(f"  超内存上限的分配在 {elapsed:.2f}s 内被内存墙杀掉（非等到超时）✓")


def test_computation_within_memory_limit_still_succeeds():
    """负向对照：内存限制不能误杀正常范围内的计算——防止把上限设进沙箱之后，
    把所有内核都变得动不动就假阳性失败。"""
    rt = SymPyRuntime(
        RuntimeConfig(timeout_seconds=5.0, max_memory_bytes=32 * 1024 * 1024)
    )

    def _small_computation() -> int:
        return sum(range(10_000))

    result = rt.run_isolated(_small_computation)
    assert result == sum(range(10_000))
    print("  32MB 上限下，正常小计算不受影响，未被误杀 ✓")


def test_pathological_combinatorics_gets_killed_via_real_solve_probability():
    """端到端：不孤立测沙箱工具本身，走真实求解主链路（solve_probability，
    S0 加固前完全绕过沙箱的两个纯数值内核之一）。math.comb(2_000_000, 1_000_000)
    实测：原始（无沙箱）耗时 ~12.6s，但结果本身只有 ~1.9M bit（约 240KB）—
    大 n/k 组合数是 CPU-bound（大数乘法链很长），不是内存-bound（这里不会撑爆
    64MB）。所以这条真实内核的病态输入实际撞的是超时墙，不是内存墙——两道墙
    哪个先触发是输入的资源消耗模式决定的，S0-2 真正的"内存墙确实生效"证明
    见上面的合成 bytearray 测试（更快、更确定性，不依赖具体输入恰好撑爆内存）。
    这条测试的价值在于确认：加固前完全绕过沙箱的 solve_probability，现在接了
    run_isolated() 之后，喂真实病态量级输入也会在有界时间内优雅降级，不是
    挂起或吃光宿主内存。"""
    from oprim.solve_probability import ProbabilitySolveInput, solve_probability

    start = time.monotonic()
    result = solve_probability(
        ProbabilitySolveInput(
            task="combinations",
            n=2_000_000,
            k=1_000_000,
            timeout=5.0,
        )
    )
    elapsed = time.monotonic() - start
    assert elapsed < 10.0
    assert result.solvable is False
    error_lower = (result.error or "").lower()
    assert "memory limit" in error_lower or "timeout" in error_lower
    print(f"  病态组合数计算在 {elapsed:.2f}s 内被沙箱杀掉（error={result.error!r}）✓")
