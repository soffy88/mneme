"""AetherViz 知识点互动课（Layer 4 服务层）：给一个 KU 生成单文件 HTML 可视化课。

来源：vendored ``data/aetherviz/SKILL.md``（andyhuo520/aetherviz-master，MIT，见同目录
LICENSE/NOTICE）作系统提示词原样使用，**不改 vendored 文件**；Mneme 的约束（自托管库、
去掉上游署名页脚、年级适配、结构化小测验、postMessage 钩子）以「覆盖说明」追加在后。

- 输入：KU 名称/描述/年级/先修（cn-math-taxonomy 共享知识图）+ 可选诊断薄弱点。
- 单次 LLM 调用，走既有 ``services.providers.setup.get_optional_text_caller``（同 photo_ask）。
- 缓存：按 ``(ku_id, variant)`` 存 MinIO（既有对象存储，bucket ``aetherviz-lessons``），
  不新建表、不跑 migration。variant = ``base`` 或 ``w-<薄弱点 sha1 前 10 位>``。
- 输出 HTML 只引用 ``/v1/edu-assets/...`` 自托管库（three r134 UMD / KaTeX / D3），
  后处理改写残留 CDN、剔除 Tailwind CDN、注入 CSP 与 ``mnemeQuizAnswer`` postMessage 钩子。
- 小测验答案键只取自页面里的 ``<script id="mneme-quiz">`` JSON，服务端留存；学生作答回写
  掌握度**只**经 ``submit_viz_quiz_answer`` → gate pending → ``tool_submit_answer``
  （SubmitAnswer 唯一写路径，同先修诊断回写）。本模块从不直接写掌握度。
- 课是共享内容（不含学生信息），不涉未成年人 PII。
"""

from __future__ import annotations

import asyncio
import hashlib
import html as _html
import io
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

PROMPT_VERSION = "aetherviz-mneme/1"
ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = ROOT / "data" / "aetherviz" / "SKILL.md"
BUCKET = "aetherviz-lessons"
ASSET_PREFIX = "/v1/edu-assets/"

# 自托管库（services/assets/vendor/），生成页只允许引用这些
LIBS = {
    "three": "/v1/edu-assets/three-0.134.0/three.min.js",
    "orbit": "/v1/edu-assets/three-0.134.0/OrbitControls.js",
    "katex_css": "/v1/edu-assets/katex-0.16.8/katex.min.css",
    "katex_js": "/v1/edu-assets/katex-0.16.8/katex.min.js",
    "katex_auto": "/v1/edu-assets/katex-0.16.8/contrib/auto-render.min.js",
    "d3": "/v1/edu-assets/d3-7.9.0/d3.min.js",
}

UPSTREAM_FOOTER = "由 AetherViz Master 为你生成"

MAX_HTML_BYTES = 400_000


class VizError(RuntimeError):
    """生成失败（LLM 不可用 / 输出不合格）。"""


# --------------------------------------------------------------------------- prompt


def _skill_text() -> str:
    raw = SKILL_PATH.read_text(encoding="utf-8")
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            raw = raw[end + 4 :]
    return raw.strip()


MNEME_OVERRIDES = f"""

---

# Mneme（善学记）覆盖说明（优先级高于上文，冲突时以本节为准）

1. **依赖库**：上文的 CDN 地址一律不用。只能用下面这些自托管地址（原样照抄，相对路径），
   不得引用任何其他外部 URL（含 Google Fonts、图片、cdn.tailwindcss.com、扩展阅读外链——外链只写书名/关键词纯文本）：
   - `<script src="{LIBS['three']}"></script>`（Three.js r134，全局 THREE）
   - `<script src="{LIBS['orbit']}"></script>`（THREE.OrbitControls，**不要**再内联 OrbitControls）
   - `<link rel="stylesheet" href="{LIBS['katex_css']}">`
   - `<script src="{LIBS['katex_js']}"></script>` 与 `<script src="{LIBS['katex_auto']}"></script>`，
     页面加载后（以及动态更新含公式的元素后）调用
     `renderMathInElement(el, {{delimiters:[{{left:'$$',right:'$$',display:true}},{{left:'\\\\(',right:'\\\\)',display:false}},{{left:'$',right:'$',display:false}}]}})`。
     公式定界符一律半角：独立公式 `$$…$$`，行内 `\\(…\\)`；**绝不**用全角括号（如 `\\）`），每个定界符必须成对。
   - 可选 `<script src="{LIBS['d3']}"></script>`（D3 v7）
2. **不用 Tailwind**：所有样式写在一个内联 `<style>` 里（CSS 变量沿用上文配色）。字体只用系统字体栈。
3. **不要**输出「{UPSTREAM_FOOTER}」或任何 AetherViz 署名；结尾只写一句鼓励的话。
4. **受众**：中国义务教育学生（年级见用户消息），全中文，语言按该年级水平（不是高中-大学水平），
   概念严谨、贴合人教版教材表述；数学以 SVG 2D 为主，需要空间感时才用 Three.js。
5. **小测验**：恰好 3 道单选题，每题 4 个选项，紧扣本知识点（若给了薄弱点，至少 2 题针对薄弱点）。
   必须在页面中放一段机器可读的题目数据（答案用 0-3 的选项下标）：
   `<script type="application/json" id="mneme-quiz">{{"items":[{{"id":"q1","prompt":"…","choices":["…","…","…","…"],"answer":0,"explain":"…"}}]}}</script>`
   这段必须是合法 JSON：字符串里的每个反斜杠都要写成两个（如 `"\\\\(x^2\\\\)"`），否则 JSON.parse 会失败。
   测验面板的题目必须从这段 JSON 渲染；学生每选定一个选项时调用
   `if (window.mnemeQuizAnswer) window.mnemeQuizAnswer("q1", 选项下标);`（由宿主注入，勿自行定义），
   再在页面内给即时反馈。
6. **篇幅**：整页 HTML 控制在约 30KB 以内，代码精炼，不要冗长注释；不得使用 fetch/XMLHttpRequest/WebSocket/localStorage/表单提交。
7. 只输出完整 HTML（`<!DOCTYPE html>` 到 `</html>`），不要 markdown 代码块、不要任何解释。
"""


def build_messages(ku: dict[str, Any], weak_points: list[str] | None = None) -> tuple[str, str]:
    system = _skill_text() + MNEME_OVERRIDES
    lines = [
        f"教学主题：{ku.get('name')}",
        f"年级：{ku.get('grade')} 年级{ku.get('semester') or ''}（{ku.get('chapter') or ''}）",
        f"学科：数学（{ku.get('domain') or ''}）",
        f"知识点说明：{ku.get('description') or ''}",
    ]
    crit = ku.get("mastery_criteria") or []
    if crit:
        lines.append("掌握标准：" + "；".join(str(c) for c in crit))
    prereqs = ku.get("prerequisites") or []
    if prereqs:
        lines.append(
            "先修知识（可在讲解中简短回顾）："
            + "；".join(f"{p.get('name')}（{p.get('grade')}年级）" for p in prereqs[:6])
        )
    if weak_points:
        lines.append("该学生诊断出的薄弱点（重点讲透、测验针对）：" + "；".join(weak_points[:8]))
    lines.append("请生成这一课的互动可视化教学网页。")
    return system, "\n".join(lines)


def variant_of(weak_points: list[str] | None) -> str:
    wp = sorted({w.strip() for w in (weak_points or []) if w and w.strip()})
    if not wp:
        return "base"
    return "w-" + hashlib.sha1("\n".join(wp).encode("utf-8")).hexdigest()[:10]


# --------------------------------------------------------------------------- post-process

_CDN_REWRITES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"https?://[^\"'\s>]*three[^\"'\s>]*/OrbitControls(?:\.min)?\.js", re.I), LIBS["orbit"]),
    (re.compile(r"https?://[^\"'\s>]*three(?:\.js)?[^\"'\s>]*/three(?:\.min)?\.js", re.I), LIBS["three"]),
    (re.compile(r"https?://[^\"'\s>]*katex[^\"'\s>]*/auto-render(?:\.min)?\.js", re.I), LIBS["katex_auto"]),
    (re.compile(r"https?://[^\"'\s>]*katex[^\"'\s>]*/katex(?:\.min)?\.css", re.I), LIBS["katex_css"]),
    (re.compile(r"https?://[^\"'\s>]*katex[^\"'\s>]*/katex(?:\.min)?\.js", re.I), LIBS["katex_js"]),
    (re.compile(r"https?://[^\"'\s>]*d3(?:js\.org)?[^\"'\s>]*/d3(?:\.v7)?(?:\.min)?\.js", re.I), LIBS["d3"]),
]
_TAILWIND_TAG = re.compile(r"<script[^>]*cdn\.tailwindcss\.com[^>]*>\s*</script>", re.I)
_EXT_FONT_LINK = re.compile(r"<link[^>]*fonts\.(?:googleapis|gstatic)\.com[^>]*>", re.I)
_FOOTER_RE = re.compile(r"由\s*AetherViz\s*Master\s*为你生成\s*(?:❤️|❤)?", re.I)


def extract_html(raw: str) -> str:
    text = (raw or "").strip()
    m = re.search(r"```(?:html)?\s*(.*?)```", text, re.S | re.I)
    if m and "<html" in m.group(1).lower():
        text = m.group(1).strip()
    start = re.search(r"<!DOCTYPE html|<html", text, re.I)
    if not start:
        raise VizError("LLM 输出不含 HTML")
    text = text[start.start() :]
    end = text.lower().rfind("</html>")
    if end == -1:
        raise VizError("HTML 被截断（无 </html>）")
    return text[: end + len("</html>")]


def _hook_script(ku_id: str, variant: str) -> str:
    payload = json.dumps({"ku_id": ku_id, "variant": variant}, ensure_ascii=False)
    return (
        "<script>(function(){var m=" + payload + ";"
        "window.mnemeQuizAnswer=function(id,choice){try{parent.postMessage("
        "{source:'mneme-viz',type:'quiz-answer',ku_id:m.ku_id,variant:m.variant,"
        "quiz_id:String(id),choice:Number(choice)},'*');}catch(e){}};})();</script>"
    )


CSP = (
    "default-src 'none'; script-src 'unsafe-inline' 'self' https: http:; "
    "style-src 'unsafe-inline' 'self' https: http:; font-src 'self' https: http: data:; "
    "img-src data: blob:; connect-src 'none'; form-action 'none'; base-uri 'none'"
)


def postprocess(html_text: str, ku_id: str, variant: str) -> str:
    out = html_text
    for pat, repl in _CDN_REWRITES:
        out = pat.sub(repl, out)
    out = _TAILWIND_TAG.sub("", out)
    out = _EXT_FONT_LINK.sub("", out)
    out = _FOOTER_RE.sub("", out)
    out = normalize_quiz_block(out)
    inject = f'<meta http-equiv="Content-Security-Policy" content="{CSP}">' + _hook_script(ku_id, variant)
    m = re.search(r"<head[^>]*>", out, re.I)
    if m:
        out = out[: m.end()] + inject + out[m.end() :]
    else:
        out = re.sub(r"(<html[^>]*>)", r"\1<head>" + inject.replace("\\", "\\\\") + "</head>", out, 1, flags=re.I)
    return out


_QUIZ_BLOCK = re.compile(r"(<script[^>]*id=[\"']mneme-quiz[\"'][^>]*>)(.*?)(</script>)", re.S | re.I)
_JSON_ESC = re.compile(r'\\(\\|"|/|u[0-9a-fA-F]{4})|\\')


def _repair_json(raw: str) -> str:
    """LLM 常把 TeX 原样写进 JSON 字符串（\\( \\frac \\times）：除合法的 \\\\ \\" \\/ \\uXXXX 外，单反斜杠一律按字面量转义。"""
    return _JSON_ESC.sub(lambda m: m.group(0) if m.group(1) else "\\\\", raw)


def _parse_quiz_json(raw: str) -> Any:
    raw = _html.unescape(raw.strip())
    for cand in (raw, _repair_json(raw)):
        try:
            return json.loads(cand)
        except (ValueError, TypeError):
            continue
    return None


def normalize_quiz_block(html_text: str) -> str:
    """把测验 JSON 规范化（修反斜杠），保证页内 JSON.parse 与服务端答案键一致。"""

    def fix(m: re.Match[str]) -> str:
        data = _parse_quiz_json(m.group(2))
        if data is None:
            return m.group(0)
        body = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
        return m.group(1) + body + m.group(3)

    return _QUIZ_BLOCK.sub(fix, html_text, count=1)


def extract_quiz(html_text: str) -> list[dict[str, Any]]:
    m = _QUIZ_BLOCK.search(html_text)
    if not m:
        return []
    data = _parse_quiz_json(m.group(2))
    if data is None:
        return []
    items = data.get("items") if isinstance(data, dict) else data
    out: list[dict[str, Any]] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        choices = it.get("choices")
        ans = it.get("answer")
        if (
            isinstance(choices, list)
            and 2 <= len(choices) <= 6
            and isinstance(ans, int)
            and not isinstance(ans, bool)
            and 0 <= ans < len(choices)
            and str(it.get("id") or "").strip()
        ):
            out.append(
                {
                    "id": str(it["id"])[:16],
                    "prompt": str(it.get("prompt") or "")[:500],
                    "choices": [str(c)[:200] for c in choices],
                    "answer": ans,
                }
            )
    return out[:6]


# --------------------------------------------------------------------------- quality


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: set[str] = set()
        self.urls: list[str] = []
        self.in_script = False
        self.scripts: list[str] = []
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        self.tags.add(tag)
        for k, v in attrs:
            if k in ("src", "href", "action", "data", "poster") and v:
                self.urls.append(v.strip())
        if tag == "script":
            self.in_script = True
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.in_script:
            self.in_script = False
            self.scripts.append("".join(self._buf))

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self._buf.append(data)


_URL_IN_TEXT = re.compile(r"(?:https?:)?//([a-z0-9.-]+\.[a-z]{2,})(?::\d+)?/", re.I)
_ALLOWED_TEXT_HOSTS = {"www.w3.org"}  # SVG/XHTML 命名空间 URI（不是网络请求）
_TEX_RE = re.compile(r"\$\$(.+?)\$\$|\\\((.+?)\\\)", re.S)
_SCRIPT_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)


def _tex_ok(expr: str) -> bool:
    depth = 0
    for ch in expr.replace("\\{", "").replace("\\}", ""):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and bool(expr.strip())


def quality_check(html_text: str) -> dict[str, Any]:
    """基础质检：可解析、只引用白名单库、无外部主机、KaTeX 就绪且公式定界/括号配平、测验可用。"""
    issues: list[str] = []
    p = _Collector()
    try:
        p.feed(html_text)
        p.close()
    except Exception as e:  # noqa: BLE001
        issues.append(f"parse_error:{type(e).__name__}")
    for t in ("html", "head", "body"):
        if t not in p.tags:
            issues.append(f"missing_<{t}>")
    allowed = set(LIBS.values())
    for u in p.urls:
        if u.startswith("#") or u.startswith("data:") or u.startswith("javascript:void"):
            continue
        if u not in allowed:
            if re.match(r"^(?:[a-z]+:)?//", u, re.I) or u.startswith("/"):
                issues.append(f"non_whitelisted_url:{u[:120]}")
    hosts = {h.lower() for h in _URL_IN_TEXT.findall(html_text)} - _ALLOWED_TEXT_HOSTS
    for h in sorted(hosts):
        issues.append(f"external_host:{h}")
    if re.search(r"\b(fetch|XMLHttpRequest|WebSocket|sendBeacon)\s*\(", " ".join(p.scripts)):
        issues.append("network_api_in_script")
    if _FOOTER_RE.search(html_text):
        issues.append("upstream_footer_present")
    body_text = _SCRIPT_STYLE.sub(" ", html_text)
    tex = [a or b for a, b in _TEX_RE.findall(body_text)]
    if body_text.count("\\(") != body_text.count("\\)") or body_text.count("$$") % 2 or "\\）" in body_text:
        issues.append("tex_delims_unbalanced")
    katex_ready = all(LIBS[k] in html_text for k in ("katex_js", "katex_auto", "katex_css")) and (
        "renderMathInElement" in html_text or "katex.render" in html_text
    )
    if tex and not katex_ready:
        issues.append("katex_not_wired")
    bad_tex = [t for t in tex if not _tex_ok(t)]
    if bad_tex:
        issues.append(f"tex_unbalanced:{len(bad_tex)}")
    quiz = extract_quiz(html_text)
    if any(sum(c.count("$") for c in [q["prompt"], *q["choices"]]) % 2 for q in quiz):
        issues.append("quiz_tex_unbalanced")
    if len(quiz) < 1:
        issues.append("quiz_missing")
    if "mnemeQuizAnswer" not in html_text:
        issues.append("quiz_hook_missing")
    if len(html_text.encode("utf-8")) > MAX_HTML_BYTES:
        issues.append("too_large")
    fatal = [
        i
        for i in issues
        if i.startswith(("parse_error", "missing_", "non_whitelisted_url", "external_host", "network_api", "upstream_footer", "too_large", "tex_delims", "quiz_missing"))
    ]
    return {
        "ok": not fatal,
        "issues": issues,
        "fatal": fatal,
        "tex_count": len(tex),
        "quiz_count": len(quiz),
        "bytes": len(html_text.encode("utf-8")),
    }


# --------------------------------------------------------------------------- cache (MinIO)


def _obj_key(ku_id: str, variant: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", ku_id)
    return f"{safe}/{variant}"


class _MinioStore:
    def _c(self):
        from services.storage import _client

        c = _client()
        if not c.bucket_exists(BUCKET):
            c.make_bucket(BUCKET)
        return c

    def get(self, key: str) -> Optional[dict[str, Any]]:
        from minio.error import S3Error

        try:
            resp = self._c().get_object(BUCKET, key + ".json")
            try:
                return json.loads(resp.read().decode("utf-8"))
            finally:
                resp.close()
                resp.release_conn()
        except S3Error as e:
            if e.code in ("NoSuchKey", "NoSuchBucket"):
                return None
            raise

    def put(self, key: str, doc: dict[str, Any]) -> None:
        data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        self._c().put_object(
            BUCKET, key + ".json", io.BytesIO(data), length=len(data), content_type="application/json"
        )


_store: Any = _MinioStore()


async def cache_get(ku_id: str, variant: str) -> Optional[dict[str, Any]]:
    try:
        return await asyncio.to_thread(_store.get, _obj_key(ku_id, variant))
    except Exception as e:  # noqa: BLE001 — 缓存不可用当未命中
        logger.warning("viz cache get failed: %s", type(e).__name__)
        return None


async def cache_put(ku_id: str, variant: str, doc: dict[str, Any]) -> None:
    await asyncio.to_thread(_store.put, _obj_key(ku_id, variant), doc)


# --------------------------------------------------------------------------- generate


def load_ku(ku_id: str) -> dict[str, Any]:
    from services import prereq_diagnosis_service as pds

    try:
        ku = pds.get_topic(ku_id)
    except Exception as e:  # noqa: BLE001
        raise VizError(f"未知知识点：{ku_id}") from e
    if ku.get("deprecated"):
        raise VizError(f"知识点已废弃：{ku_id}")
    return ku


def _caller():
    from services.providers.setup import get_optional_text_caller

    return get_optional_text_caller()


def _timeout() -> float:
    try:
        return max(30.0, min(float(os.environ.get("MNEME_VIZ_TIMEOUT_SECONDS", "240")), 600.0))
    except ValueError:
        return 240.0


async def generate(ku_id: str, weak_points: list[str] | None = None) -> dict[str, Any]:
    """真正调 LLM 生成一份课（不读缓存）；质检不过最多重试 1 次。"""
    ku = load_ku(ku_id)
    canonical = str(ku.get("ku_id") or ku_id)
    variant = variant_of(weak_points)
    caller = _caller()
    if caller is None:
        raise VizError("LLM 不可用")
    system, user = build_messages(ku, weak_points)
    last_err = "unknown"
    for attempt in range(2):
        t0 = time.monotonic()
        try:
            out = await asyncio.wait_for(
                caller(messages=[{"role": "user", "content": user}], system=system, max_tokens=16000),
                timeout=_timeout(),
            )
        except Exception as e:  # noqa: BLE001
            last_err = f"llm:{type(e).__name__}"
            logger.warning("viz LLM call failed (%s): %s", canonical, e)
            continue
        content = out.get("content") if isinstance(out, dict) else None
        try:
            page = postprocess(extract_html(str(content or "")), canonical, variant)
        except VizError as e:
            last_err = str(e)
            continue
        qc = quality_check(page)
        if not qc["ok"]:
            last_err = "quality:" + ",".join(qc["fatal"])[:300]
            logger.warning("viz quality failed (%s): %s", canonical, qc["fatal"])
            continue
        inner = getattr(caller, "caller", caller)
        return {
            "ku_id": canonical,
            "variant": variant,
            "weak_points": sorted({w.strip() for w in (weak_points or []) if w and w.strip()}),
            "html": page,
            "quiz_key": extract_quiz(page),
            "quality": qc,
            "model": str(getattr(inner, "last_good_model", None) or getattr(inner, "model", "unknown")),
            "usage": (out.get("usage") if isinstance(out, dict) else None) or {},
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "attempt": attempt + 1,
            "prompt_version": PROMPT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    raise VizError(f"生成失败：{last_err}")


_inflight: dict[tuple[str, str], asyncio.Task] = {}
_last_error: dict[tuple[str, str], str] = {}


def public_view(doc: dict[str, Any], *, cached: bool) -> dict[str, Any]:
    """对外：HTML（资源前缀可按 MNEME_VIZ_ASSET_BASE 改绝对地址）+ 不含答案的题目。"""
    page = doc["html"]
    base = os.environ.get("MNEME_VIZ_ASSET_BASE", "").rstrip("/")
    if base:
        page = re.sub(r"([\"'])" + re.escape(ASSET_PREFIX), lambda m: m.group(1) + base + ASSET_PREFIX, page)
    return {
        "status": "ready",
        "ku_id": doc["ku_id"],
        "variant": doc["variant"],
        "cached": cached,
        "html": page,
        "quiz": [{k: q[k] for k in ("id", "prompt", "choices")} for q in doc.get("quiz_key") or []],
        "model": doc.get("model"),
        "created_at": doc.get("created_at"),
        "quality": {k: doc.get("quality", {}).get(k) for k in ("ok", "issues", "tex_count", "quiz_count", "bytes")},
    }


async def _run(ku_id: str, weak_points: list[str] | None, key: tuple[str, str]) -> dict[str, Any]:
    try:
        doc = await generate(ku_id, weak_points)
        await cache_put(doc["ku_id"], doc["variant"], doc)
        _last_error.pop(key, None)
        return doc
    except Exception as e:
        _last_error[key] = str(e)[:300]
        raise
    finally:
        _inflight.pop(key, None)


async def get_or_generate(
    ku_id: str,
    weak_points: list[str] | None = None,
    *,
    force: bool = False,
    wait_seconds: float = 25.0,
) -> dict[str, Any]:
    """读缓存；未命中则后台生成（同 key 只跑一个），最多等 wait_seconds，超时返回 pending 让客户端轮询。"""
    ku = load_ku(ku_id)
    canonical = str(ku.get("ku_id") or ku_id)
    variant = variant_of(weak_points)
    key = (canonical, variant)
    if not force:
        doc = await cache_get(canonical, variant)
        if doc and doc.get("html"):
            return public_view(doc, cached=True)
    task = _inflight.get(key)
    if task is None:
        if key in _last_error and not force:
            err = _last_error.pop(key)
            return {"status": "failed", "ku_id": canonical, "variant": variant, "error": err}
        task = asyncio.create_task(_run(canonical, weak_points, key))
        _inflight[key] = task
    try:
        doc = await asyncio.wait_for(asyncio.shield(task), timeout=max(0.0, wait_seconds))
    except asyncio.TimeoutError:
        return {"status": "pending", "ku_id": canonical, "variant": variant, "retry_after": 5}
    except Exception as e:  # noqa: BLE001
        _last_error.pop(key, None)
        return {"status": "failed", "ku_id": canonical, "variant": variant, "error": str(e)[:300]}
    return public_view(doc, cached=False)


# --------------------------------------------------------------------------- quiz → SubmitAnswer


def _letter(i: int) -> str:
    return "ABCDEF"[i]


def _quiz_qid(ku_id: str, variant: str, quiz_id: str, created_at: str) -> str:
    h = hashlib.sha1(f"{ku_id}|{variant}|{created_at}|{quiz_id}".encode("utf-8")).hexdigest()[:24]
    return f"viz:{h}"


async def submit_viz_quiz_answer(
    db: Any,
    current_user: Any,
    *,
    ku_id: str,
    variant: str,
    quiz_id: str,
    choice: int,
) -> dict[str, Any]:
    """学生本人在可视化课里答一道小测验 → gate pending → tool_submit_answer（唯一写路径）。

    答案键取服务端缓存（生成时从页面 JSON 提取），客户端只报选项下标。同一份课的同一题
    每个学生只回写一次。非学生（家长/admin）不写任何档案。
    """
    from sqlalchemy import select

    from services import gate_store
    from services.mcp_router import tool_submit_answer
    from services.models import QuestionRecord
    from services.tool_grants import _is_student

    if not _is_student(current_user):
        return {"written": False, "reason": "not_student"}
    doc = await cache_get(ku_id, variant)
    if not doc:
        return {"written": False, "reason": "lesson_not_found"}
    item = next((q for q in doc.get("quiz_key") or [] if q["id"] == str(quiz_id)), None)
    if item is None:
        return {"written": False, "reason": "unknown_question"}
    if not isinstance(choice, int) or isinstance(choice, bool) or not 0 <= choice < len(item["choices"]):
        return {"written": False, "reason": "invalid_choice"}
    if item.get("verified") is not True:
        # LLM 答案键未经 sympy 核验（或核验不了）：题目照常在页内展示，但不回写 BKT，
        # 免得错误答案键污染掌握度（cnm_148 Q2 双正确项事故）。
        logger.info("viz quiz answer not written (unverified key): %s/%s/%s", doc.get("ku_id"), doc.get("variant"), item["id"])
        return {"ok": True, "written": False, "reason": "unverified_quiz"}
    student_id = current_user.id
    qid = _quiz_qid(doc["ku_id"], doc["variant"], item["id"], str(doc.get("created_at")))
    dup = (
        await db.execute(
            select(QuestionRecord.id)
            .where(QuestionRecord.student_id == student_id, QuestionRecord.question_ref == qid)
            .limit(1)
        )
    ).first()
    if dup is not None or await gate_store.get_pending(db, student_id=student_id, question_id=qid):
        return {"written": False, "reason": "duplicate", "question_id": qid}
    try:
        async with db.begin_nested():
            await gate_store.pose_question(
                db,
                question_id=qid,
                student_id=student_id,
                kc_id=doc["ku_id"],
                prompt=item["prompt"],
                expected=_letter(item["answer"]),
                qtype="choice",
            )
            r = await tool_submit_answer(db, student_id=student_id, question_id=qid, answer=_letter(choice))
        await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("viz quiz writeback failed: %s", e)
        await db.rollback()
        return {"written": False, "reason": "error", "question_id": qid}
    if not r.get("graded"):
        return {"written": False, "reason": str(r.get("error") or "not_graded"), "question_id": qid}
    return {
        "written": True,
        "question_id": qid,
        "kc_id": r.get("kc_id"),
        "is_correct": r.get("is_correct"),
        "verdict_source": r.get("verdict_source"),
    }
