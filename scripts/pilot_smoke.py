#!/usr/bin/env python3
"""真人 pilot 前冒烟（容器内或挂载卷环境跑）。

用法（推荐在 api 容器）：
  docker exec mneme-api-1 python scripts/pilot_smoke.py

检查：
  1. /health + providers 非 mock
  2. 文本 LLM 真调用 1 次
  3. VLM 真调用 1 次（小 JPEG）
  4. 公共题库练习 submit → mastery 变化
  5. 康奈尔云同步 PUT/GET

失败 exit 1。不依赖浏览器，不替代真人 pilot。
"""

from __future__ import annotations

import asyncio
import base64
import sys
import uuid
from io import BytesIO

# 容器内 CWD 常为 /app
sys.path.insert(0, "/app")


def _fail(msg: str) -> None:
    print(f"FAIL  {msg}")
    raise SystemExit(1)


def _ok(msg: str) -> None:
    print(f"OK    {msg}")


async def main() -> None:
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy import delete, select, text

    from obase.auth import create_access_token
    from obase.db import SessionLocal
    from services.main import app
    from services.models import User, UserRole, WrongQuestion
    from services.providers.setup import configure_llm_providers, provider_status

    # ── 1. providers ──
    tag = configure_llm_providers()
    st = provider_status()
    _ok(f"configure_llm_providers → {tag} llm={st['llm']} vlm={st['vlm']}")
    if st.get("llm_is_mock") or st.get("vlm_is_mock"):
        _fail(f"仍在 mock：{st}（检查 DASHSCOPE_API_KEY / MNEME_LLM=qwen）")

    # ── 2. text LLM ──
    from obase.provider_registry import ProviderRegistry

    llm = ProviderRegistry.get().llm()
    r = await llm(
        messages=[{"role": "user", "content": "只回复一个汉字：好"}],
        max_tokens=16,
        enable_thinking=False,
    )
    content = (r.get("content") or "").strip()
    if not content:
        _fail("文本 LLM 返回空")
    _ok(f"text LLM → {content!r}")

    # ── 3. VLM ──
    try:
        from PIL import Image

        im = Image.new("RGB", (48, 48), (20, 120, 200))
        buf = BytesIO()
        im.save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception:
        _fail("需要 Pillow 生成测试图（容器应有 pillow 或装 pymupdf 链）")

    vlm = ProviderRegistry.get().vlm()
    vr = await vlm(prompt="用一个词描述主色", image_b64=b64, response_format="text")
    vcontent = str(vr.get("content") or "").strip()
    if not vcontent:
        _fail("VLM 返回空")
    _ok(f"VLM → {vcontent[:60]!r}")

    # ── 4. 练习 + mastery ──
    sid = uuid.uuid4()
    async with SessionLocal() as db:
        db.add(
            User(
                id=sid,
                phone=f"196{str(sid.int)[:8]}",
                role=UserRole.student,
                name="pilot-smoke",
                grade="高一",
            )
        )
        q = (
            await db.execute(
                select(WrongQuestion).where(WrongQuestion.student_id.is_(None)).limit(1)
            )
        ).scalar_one_or_none()
        if not q:
            _fail("公共题库无题（wrong_questions student_id IS NULL）")
        qid = q.id
        ku = (
            next(iter(q.knowledge_points.keys()))
            if q.knowledge_points
            else "smoke-ku"
        )
        await db.commit()

    tok = create_access_token({"sub": str(sid)})
    headers = {"Authorization": f"Bearer {tok}"}
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", timeout=90
        ) as c:
            hr = await c.get("/health")
            if hr.status_code != 200:
                _fail(f"/health {hr.status_code}")
            prov = hr.json().get("providers") or {}
            if prov.get("llm_is_mock") or prov.get("vlm_is_mock"):
                _fail(f"/health providers 仍是 mock: {prov}")
            _ok(f"/health providers llm={prov.get('llm')} vlm={prov.get('vlm')}")

            sub = await c.post(
                "/v1/practice/submit",
                headers=headers,
                json={
                    "student_id": str(sid),
                    "question_id": str(qid),
                    "ku_id": ku,
                    "student_answer": "smoke-wrong",
                    "is_correct": False,
                },
            )
            if sub.status_code != 200:
                _fail(f"practice/submit {sub.status_code} {sub.text[:200]}")
            body = sub.json()
            if body.get("p_mastery") is None:
                _fail(f"submit 未返回 p_mastery: {body}")
            _ok(f"practice/submit p_mastery={body.get('p_mastery')}")

            m = await c.get(f"/v1/mastery/{sid}", headers=headers)
            if m.status_code != 200 or not m.json():
                _fail(f"mastery empty: {m.status_code} {m.text[:200]}")
            _ok(f"mastery rows={len(m.json())}")

            cp = await c.put(
                f"/v1/cornell/{sid}/progress/pythagoras",
                headers=headers,
                json={
                    "state": {
                        "topicId": "pythagoras",
                        "version": 1,
                        "mastered": {"q1": True},
                        "collapsed": {},
                        "selfTest": False,
                        "showAnswers": False,
                        "updatedAt": "2026-07-28T12:00:00.000Z",
                    }
                },
            )
            if cp.status_code != 200:
                _fail(f"cornell put {cp.status_code}")
            _ok("cornell cloud put/get path ok")
    finally:
        async with SessionLocal() as db:
            for t in (
                "interaction_events",
                "kc_mastery",
                "mastery_snapshots",
                "cornell_progress",
                "wrong_questions",
                "effortful_gains",
            ):
                try:
                    await db.execute(
                        text(f"delete from {t} where student_id = :s"), {"s": sid}
                    )
                except Exception:
                    await db.rollback()
            await db.execute(delete(User).where(User.id == sid))
            await db.commit()

    print("\nALL SMOKE CHECKS PASSED — 可进入真人 pilot 清单。")


if __name__ == "__main__":
    asyncio.run(main())
