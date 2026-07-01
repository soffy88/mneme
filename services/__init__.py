"""services package.

vendor 优先：把 mneme 自带的内核副本(vendor/，含 edu-audit 改动)插到 sys.path 最前，
使 import oprim/oskill/omodul/obase 走 vendor，而非共享 platform/3O（会被别的项目切分支）。
必须在任何内核 import 之前执行，故放在包 __init__ 顶部。
"""
import os as _os
import sys as _sys

_vendor = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "vendor")
if _os.path.isdir(_vendor) and _vendor not in _sys.path:
    _sys.path.insert(0, _vendor)
