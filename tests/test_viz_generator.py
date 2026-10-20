"""AetherViz 知识点互动课：生成/后处理/质检/缓存 + 授权 + 课内测验只经 SubmitAnswer 回写。

LLM 用桩（不出网），MinIO 换内存 store；DB 打测试库（同 test_prereq_writeback_grants）。
"""

from __future__ import annotations

import ast
import json
import pathlib
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from obase.auth import create_access_token
from obase.config import settings
from services import viz_generator as vg
from services.main import app
from services.models import KCMastery, User, UserRole
from services.tool_grants import DEFAULT_STUDENT_TOOLS

from .db_test_helpers import cleanup_test_student

ROOT = pathlib.Path(__file__).resolve().parents[1]
KU = "cnmath:cnm_148"

QUIZ = {
    "items": [
        {"id": "q1", "prompt": "计算 $(x+3)^2$", "choices": ["$x^2+9$", "$x^2+3x+9$", "$x^2+6x+9$", "$2x+6$"], "answer": 2},
        {"id": "q2", "prompt": "$(a-b)^2=$", "choices": ["$a^2-b^2$", "$a^2-2ab+b^2$", "$a^2+b^2$", "$a^2+2ab-b^2$"], "answer": 1},
    ]
}

GOOD = (
    "<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>"
    "<script src='https://cdn.tailwindcss.com'></script>"
    "<link rel='stylesheet' href='https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css'>"
    "<script src='https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js'></script>"
    "<script src='https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js'></script>"
    "<script src='https://cdnjs.cloudflare.com/ajax/libs/three.js/r134/three.min.js'></script>"
    "<style>body{margin:0}</style></head><body><h1>完全平方公式</h1>"
    "<p>$$(a+b)^2=a^2+2ab+b^2$$ 以及 \\(2ab\\)</p>"
    "<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    f"<script type='application/json' id='mneme-quiz'>{json.dumps(QUIZ, ensure_ascii=False)}</script>"
    "<script>renderMathInElement(document.body);"
    "function pick(id,i){if(window.mnemeQuizAnswer)window.mnemeQuizAnswer(id,i);}</script>"
    "<footer>加油！由 AetherViz Master 为你生成 ❤️</footer></body></html>"
)


class _MemStore:
    def __init__(self) -> None:
        self.d: dict[str, dict] = {}

    def get(self, key):
        return self.d.get(key)

    def put(self, key, doc):
        self.d[key] = json.loads(json.dumps(doc))


class _Caller:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []
        self.model = "stub-llm"

    async def __call__(self, **kw):
        self.calls.append(kw)
        out = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        return {"content": "```html\n" + out + "\n```", "usage": {"input_tokens": 5000, "output_tokens": 7000}}


@pytest.fixture
def mem(monkeypatch):
    store = _MemStore()
    monkeypatch.setattr(vg, "_store", store)
    vg._inflight.clear()
    vg._last_error.clear()
    return store


@pytest.fixture
def stub(monkeypatch):
    def _install(*outputs):
        c = _Caller(outputs or [GOOD])
        monkeypatch.setattr(vg, "_caller", lambda: c)
        return c

    return _install


# ------------------------------------------------------------------ 纯函数


def test_vendored_skill_untouched_and_attributed():
    d = ROOT / "data" / "aetherviz"
    skill = (d / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: aetherviz-master")
    assert vg.UPSTREAM_FOOTER in skill  # vendored 原样（页脚靠提示词+后处理去掉，不改文件）
    assert "MIT License" in (d / "LICENSE").read_text(encoding="utf-8")
    assert "andyhuo520/aetherviz-master" in (d / "NOTICE").read_text(encoding="utf-8")


def test_prompt_overrides_and_ku_context():
    ku = vg.load_ku(KU)
    system, user = vg.build_messages(ku, ["漏掉中间项 2ab"])
    assert "Mneme（善学记）覆盖说明" in system and "不要**输出「由 AetherViz Master" in system
    for u in vg.LIBS.values():
        assert u in system
    assert "完全平方公式" in user and "8 年级" in user and "多项式乘多项式" in user and "漏掉中间项" in user


def test_variant_is_stable_and_order_free():
    assert vg.variant_of(None) == vg.variant_of([" "]) == "base"
    assert vg.variant_of(["b", "a"]) == vg.variant_of(["a", "b", "a"]) != "base"


def test_postprocess_rewrites_cdn_strips_footer_injects_hook():
    page = vg.postprocess(vg.extract_html("说明\n```html\n" + GOOD + "\n```"), KU, "base")
    assert "cdn.tailwindcss.com" not in page and "jsdelivr" not in page and "cdnjs" not in page
    assert vg.LIBS["three"] in page and vg.LIBS["katex_js"] in page and vg.LIBS["katex_auto"] in page
    assert "AetherViz" not in page
    assert "Content-Security-Policy" in page and "connect-src 'none'" in page
    assert "window.mnemeQuizAnswer=function" in page and "mneme-viz" in page
    qc = vg.quality_check(page)
    assert qc["ok"], qc
    assert qc["quiz_count"] == 2 and qc["tex_count"] == 2


def test_quality_check_rejects_external_and_broken():
    page = vg.postprocess(GOOD, KU, "base")
    bad = page.replace("</body>", "<img src='https://evil.example.com/x.png'></body>")
    qc = vg.quality_check(bad)
    assert not qc["ok"] and any("evil.example.com" in i for i in qc["fatal"])
    bad2 = page.replace("\\(2ab\\)", "\\(2ab\\）")
    assert "tex_delims_unbalanced" in vg.quality_check(bad2)["fatal"]
    bad3 = page.replace("renderMathInElement(document.body);", "fetch('/x');renderMathInElement(document.body);")
    assert "network_api_in_script" in vg.quality_check(bad3)["fatal"]
    with pytest.raises(vg.VizError):
        vg.extract_html("<html><body>截断")


def test_extract_quiz_validates_key():
    q = vg.extract_quiz(GOOD.replace('"answer": 1', '"answer": 9'))
    assert [x["id"] for x in q] == ["q1"]


# ------------------------------------------------------------------ 生成 + 缓存


@pytest.mark.asyncio
async def test_generate_caches_and_retries_on_bad_output(mem, stub):
    c = stub("<html><body>no closing", GOOD)
    out = await vg.get_or_generate(KU, wait_seconds=10)
    assert out["status"] == "ready" and out["cached"] is False and len(c.calls) == 2
    assert out["ku_id"] == KU and out["variant"] == "base"
    assert all("answer" not in q for q in out["quiz"]) and len(out["quiz"]) == 2
    doc = mem.d[vg._obj_key(KU, "base")]
    assert doc["quiz_key"][0]["answer"] == 2 and doc["model"] == "stub-llm" and doc["usage"]["output_tokens"] == 7000
    again = await vg.get_or_generate("cnm_148", wait_seconds=1)
    assert again["status"] == "ready" and again["cached"] is True and len(c.calls) == 2


@pytest.mark.asyncio
async def test_generation_failure_reported(mem, stub):
    stub("<p>not html</p>")
    out = await vg.get_or_generate(KU, wait_seconds=10)
    assert out["status"] == "failed" and "生成失败" in out["error"]


@pytest.mark.asyncio
async def test_pending_when_slow(mem, monkeypatch):
    import asyncio

    gate = asyncio.Event()

    async def slow(**kw):
        await gate.wait()
        return {"content": GOOD, "usage": {}}

    monkeypatch.setattr(vg, "_caller", lambda: slow)
    out = await vg.get_or_generate(KU, wait_seconds=0.05)
    assert out["status"] == "pending"
    gate.set()
    await asyncio.sleep(0.05)
    for _ in range(50):
        if not vg._inflight:
            break
        await asyncio.sleep(0.02)
    assert (await vg.get_or_generate(KU, wait_seconds=1))["cached"] is True


def test_asset_base_override(monkeypatch):
    monkeypatch.setenv("MNEME_VIZ_ASSET_BASE", "https://sxueji.com/")
    doc = {"ku_id": KU, "variant": "base", "html": vg.postprocess(GOOD, KU, "base"), "quiz_key": []}
    page = vg.public_view(doc, cached=True)["html"]
    assert "src='https://sxueji.com/v1/edu-assets/three-0.134.0/three.min.js'" in page
    assert "'/v1/edu-assets/" not in page and '"/v1/edu-assets/' not in page


def test_vendor_assets_served_by_edu_assets():
    from services.routers.edu_assets import resolve_asset

    for u in vg.LIBS.values():
        assert resolve_asset(u.removeprefix("/v1/edu-assets/")) is not None, u


# ------------------------------------------------------------------ HTTP + 授权 + SubmitAnswer 回写


def _h(user_id):
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user_id)})}"}


@pytest.fixture
async def db():
    engine = create_async_engine(settings.DATABASE_URL)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def actors(db, monkeypatch):
    admin_id, stu, par = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    monkeypatch.setenv("ADMIN_USER_IDS", str(admin_id))
    db.add(User(id=admin_id, role=UserRole.student, name="管理员"))
    db.add(User(id=stu, role=UserRole.student, name="可视化学生"))
    db.add(User(id=par, role=UserRole.parent, name="家长"))
    await db.commit()
    yield {"admin": admin_id, "stu": stu, "par": par}
    await db.rollback()
    for sid in (stu, admin_id, par):
        await db.execute(text("DELETE FROM agent.audit_log WHERE student_id = :s"), {"s": sid})
        await db.execute(text("DELETE FROM gate.pending_question WHERE student_id = :s"), {"s": sid})
        await db.execute(text("DELETE FROM agent.user_grants WHERE student_id = :s"), {"s": sid})
        await db.commit()
        await cleanup_test_student(db, sid)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def test_default_grant_and_tutor_tool_registered():
    assert "GenerateKUVisualization" in DEFAULT_STUDENT_TOOLS
    src = (ROOT / "packages/mneme-agent/mneme_agent/assembly/tutor_loop.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {
        n.args[1].value
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_spec" and len(n.args) > 1
        and isinstance(n.args[1], ast.Constant)
    }
    assert "GenerateKUVisualization" in names


@pytest.mark.asyncio
async def test_rest_and_mcp_generate_with_grants(actors, client, mem, stub):
    stub(GOOD)
    r = await client.post("/v1/viz/ku", json={"ku_id": KU, "wait_seconds": 10}, headers=_h(actors["stu"]))
    assert r.status_code == 200 and r.json()["status"] == "ready", r.text
    r2 = await client.post("/mcp/GenerateKUVisualization", json={"ku_id": "cnm_148"}, headers=_h(actors["stu"]))
    assert r2.status_code == 200 and r2.json()["cached"] is True
    assert (await client.post("/v1/viz/ku", json={"ku_id": KU}, headers=_h(actors["par"]))).status_code == 403
    assert (await client.post("/v1/viz/ku", json={"ku_id": KU, "force": True}, headers=_h(actors["stu"]))).status_code == 403
    assert (await client.post("/v1/viz/ku", json={"ku_id": "cnmath:nope"}, headers=_h(actors["stu"]))).status_code == 404
    assert (await client.post("/v1/viz/ku", json={"ku_id": KU})).status_code in (401, 403)


async def _mastery(db, sid, kc):
    db.expire_all()
    return (
        await db.execute(select(KCMastery).where(KCMastery.student_id == sid, KCMastery.knowledge_point == kc))
    ).scalars().first()


@pytest.mark.asyncio
async def test_quiz_answer_writes_bkt_only_via_submit_answer(actors, client, db, mem, stub):
    stub(GOOD)
    stu = actors["stu"]
    out = (await client.post("/v1/viz/ku", json={"ku_id": KU, "wait_seconds": 10}, headers=_h(stu))).json()
    body = {"ku_id": out["ku_id"], "variant": out["variant"], "quiz_id": "q1", "choice": 2}
    r = await client.post("/v1/viz/quiz-answer", json=body, headers=_h(stu))
    wb = r.json()
    assert r.status_code == 200 and wb["written"] is True and wb["is_correct"] is True and wb["kc_id"] == KU, wb
    row = await _mastery(db, stu, KU)
    assert row is not None and 0 < (row.p_mastery or 0) <= 0.97
    left = (await db.execute(text("SELECT count(*) FROM gate.pending_question WHERE student_id=:s"), {"s": stu})).scalar()
    assert left == 0
    # 重放不重复写
    r2 = await client.post("/v1/viz/quiz-answer", json=body, headers=_h(stu))
    assert r2.json()["reason"] == "duplicate"
    # 错答 q2
    r3 = await client.post("/v1/viz/quiz-answer", json={**body, "quiz_id": "q2", "choice": 0}, headers=_h(stu))
    assert r3.json()["written"] is True and r3.json()["is_correct"] is False
    n = (await db.execute(text("SELECT count(*) FROM interaction_events WHERE student_id=:s"), {"s": stu})).scalar()
    assert n == 2
    # 非法题号/选项/家长
    assert (await client.post("/v1/viz/quiz-answer", json={**body, "quiz_id": "zz"}, headers=_h(stu))).json()["reason"] == "unknown_question"
    assert (await client.post("/v1/viz/quiz-answer", json={**body, "quiz_id": "q1", "choice": 5}, headers=_h(stu))).json()["reason"] == "invalid_choice"
    assert (await client.post("/v1/viz/quiz-answer", json=body, headers=_h(actors["par"]))).status_code == 403


def test_viz_service_never_writes_mastery_directly():
    src = (ROOT / "services/viz_generator.py").read_text(encoding="utf-8")
    for forbidden in ("KCMastery", "process_interaction", "kc_mastery", "bkt_update"):
        assert forbidden not in src


def test_quiz_json_with_raw_tex_backslashes_is_repaired_and_normalized():
    raw = '{"items":[{"id":"q1","prompt":"计算 \\((x+3)^2\\)，\\frac{1}{2}","choices":["\\(a\\)","b","c","d"],"answer":2}]}'
    page = GOOD.replace(json.dumps(QUIZ, ensure_ascii=False), raw)
    with pytest.raises(ValueError):
        json.loads(raw)
    out = vg.postprocess(page, KU, "base")
    q = vg.extract_quiz(out)
    assert q and q[0]["prompt"] == "计算 \\((x+3)^2\\)，\\frac{1}{2}" and q[0]["answer"] == 2
    block = vg._QUIZ_BLOCK.search(out).group(2)
    assert json.loads(block)["items"][0]["choices"][0] == "\\(a\\)"  # 页内 JSON.parse 可用


def test_quiz_missing_is_fatal():
    page = vg.postprocess(GOOD, KU, "base")
    no_quiz = vg._QUIZ_BLOCK.sub("", page)
    assert "quiz_missing" in vg.quality_check(no_quiz)["fatal"]
