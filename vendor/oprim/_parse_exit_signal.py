"""Parse a process exit code into a SignalInfo descriptor."""
from __future__ import annotations

import signal

from oprim._hicode_types import SignalInfo


def parse_exit_signal(code: int) -> SignalInfo:
    """Convert a raw process exit code to a :class:`SignalInfo`.

    Args:
        code: Raw exit code from a subprocess.

    Returns:
        A populated :class:`SignalInfo` instance.

    Raises:
        ValueError: If *code* is negative.
    """
    if code < 0:
        raise ValueError(f"Exit code must be >= 0, got {code!r}")

    if code > 255:
        code = code % 256

    if code == 0:
        return SignalInfo(code=0, is_signal=False, name="SUCCESS")

    if code > 128:
        signal_no = code - 128
        name: str | None = None
        try:
            sig = signal.Signals(signal_no)
            name = sig.name
        except ValueError:
            name = f"SIG{signal_no}"
        return SignalInfo(code=code, is_signal=True, signal_no=signal_no, name=name)

    return SignalInfo(code=code, is_signal=False)
