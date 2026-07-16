"""B1 / V12 — build_path 校验：意图定性的 KC 必须有 rubric，否则构建失败并给**完整**缺失清单。

意图（gate.qualitative_intent）与判据（gate.rubric）分表（R2 §5/M1），故"删 ku004 rubric"
只撤判据不撤意图 → 仍被判失败——这正是 V12 要证的活锁防护。单 session 不 commit，退出回滚。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from obase.db import SessionLocal
from services.path_builder import PathBuildError, build_path

KU004 = "renjiao-math-g10-a-ku004"  # 意图定性 + 已播种 rubric
QUANT_KC = "renjiao-math-g10-a-ku-二次函数的零点"  # 量化，无 rubric


@pytest.mark.asyncio
async def test_qualitative_requires_rubric():
    async with SessionLocal() as db:
        # 1) ku004 意图定性且有 rubric；量化 KC 无 rubric 无所谓 → 通过，原样返回
        path = await build_path(db, [QUANT_KC, KU004])
        assert path == [QUANT_KC, KU004]

        # 2) 注入意图集含两个无 rubric 的定性 KC → 失败，缺失清单**完整**（非只报首个）
        fake_a, fake_b = f"fake-{uuid.uuid4().hex}", f"fake-{uuid.uuid4().hex}"
        with pytest.raises(PathBuildError) as ei:
            await build_path(db, [fake_a, QUANT_KC, fake_b], intent={fake_a, fake_b})
        assert set(ei.value.missing) == {fake_a, fake_b}  # 两个都在
        assert QUANT_KC not in ei.value.missing  # 非意图定性者不误报

        # 3) 混合：有 rubric(ku004) + 无 rubric(fake) 均意图定性 → 只 fake 缺失
        with pytest.raises(PathBuildError) as ei2:
            await build_path(db, [KU004, fake_a], intent={KU004, fake_a})
        assert ei2.value.missing == [fake_a]

        # 4) V12 直击：默认意图源含 ku004；删其 rubric → 构建失败（rollback 恢复）
        await db.execute(
            text("DELETE FROM gate.rubric WHERE kc_id = :kc"), {"kc": KU004}
        )
        with pytest.raises(PathBuildError) as ei3:
            await build_path(
                db, [KU004]
            )  # 默认 intent（gate.qualitative_intent 含 ku004）
        assert ei3.value.missing == [KU004]
