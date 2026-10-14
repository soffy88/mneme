"""拍照问题目确定性内核的端到端评测（无 LLM）。

文本模式：tests/eval/ask_corpus/problems.jsonl 里每道题 → services.ask_kernels.solve_text → 与期望答案比对。
图片模式（--images）：tests/eval/ask_corpus/images/manifest.jsonl 里的渲染图 → OCR 侧车（MNEME_OCR_URL）
→ photo_ask_service.clean_ocr_text / guess_subject → solve_text → 比对。

指标（按题型）：
- coverage = 作答数 / 题数（内核给出了已验证的解）
- accuracy = 答对数 / 作答数
- confident_wrong = 作答但答错的题（目标 0）

用法（在 api 镜像里，挂载工作树，接 compose 网络才能访问 OCR）：
    docker run --rm --network mneme_default -v $PWD:/app -w /app -e PYTHONPATH=/app:/app/vendor \
        --entrypoint python mneme-api:latest tests/eval/run_ask_eval.py [--images] [--out reports/ask_eval]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))

CORPUS = ROOT / "tests/eval/ask_corpus/problems.jsonl"
MANIFEST = ROOT / "tests/eval/ask_corpus/images/manifest.jsonl"

_UNIT_FACTORS = {
    "kg/m^3": ("density", 1), "kg/m³": ("density", 1), "g/cm^3": ("density", 1000), "g/cm³": ("density", 1000),
    "m/s": ("speed", 1), "km/h": ("speed", 5 / 18), "m": ("length", 1), "km": ("length", 1000), "cm": ("length", 0.01),
    "J": ("energy", 1), "kJ": ("energy", 1000), "MJ": ("energy", 1e6), "kW·h": ("energy", 3.6e6), "kWh": ("energy", 3.6e6), "kW*h": ("energy", 3.6e6),
    "W": ("power", 1), "kW": ("power", 1000), "Pa": ("pressure", 1), "kPa": ("pressure", 1000), "N": ("force", 1),
    "s": ("time", 1), "min": ("time", 60), "h": ("time", 3600), "g": ("mass", 0.001), "kg": ("mass", 1), "t": ("mass", 1000),
    "m^3": ("volume", 1), "m³": ("volume", 1), "cm^3": ("volume", 1e-6), "cm³": ("volume", 1e-6), "mL": ("volume", 1e-6), "L": ("volume", 1e-3),
    "A": ("current", 1), "mA": ("current", 1e-3), "V": ("voltage", 1), "Ω": ("resistance", 1),
}


def _val(s: str) -> Any:
    from services.ask_kernels.sym import parse

    t = str(s).strip().replace("**", "^").replace(" ", "")
    t = re.sub(r"^[a-z]\s*=\s*", "", t)
    if t.endswith("%"):
        t = t[:-1]
    return parse(t)


def _close(a: Any, b: Any, rel: float = 2e-3) -> bool:
    try:
        fa, fb = complex(a), complex(b)
    except (TypeError, ValueError):
        return False
    return abs(fa - fb) <= max(1e-9, rel * max(1.0, abs(fb)))


def _conv(v: Any, from_u: str, to_u: str) -> Any:
    fu, tu = (from_u or "").strip(), (to_u or "").strip()
    if not fu or not tu or fu == tu or fu not in _UNIT_FACTORS or tu not in _UNIT_FACTORS:
        return v
    d1, f1 = _UNIT_FACTORS[fu]
    d2, f2 = _UNIT_FACTORS[tu]
    if d1 != d2:
        return v
    return complex(v) * f1 / f2


def match(sol: Any, exp: dict) -> bool:
    import sympy as sp

    from services.ask_kernels.variants import _ineq_tuple, grade_answer

    kind = exp["answer_kind"]
    ans = exp["answer"]
    if kind == "text":
        return bool(grade_answer(sol.answer + " " + sol.answer_value, str(ans), "text"))
    if kind == "ineq":
        if str(ans) in ("无解",):
            return "无解" in sol.answer_value or "无解" in sol.answer
        return _ineq_tuple(sol.answer_value) == _ineq_tuple(str(ans)) and _ineq_tuple(str(ans)) is not None
    if kind == "expr":
        try:
            got = _val(sol.answer_value)
            want = _val(str(ans))
        except ValueError:
            return False
        return sp.simplify(sp.expand(got - want)) == 0
    want = ans if isinstance(ans, list) else [ans]
    try:
        wv = [_val(w) for w in want]
    except ValueError:
        return False
    parts = [p for p in re.split(r",\s*", sol.answer_value) if p.strip()]
    try:
        gv = [_val(p) for p in parts]
    except ValueError:
        return False
    units = [u.strip() for u in (sol.unit or "").split(",")]
    eu = exp.get("unit") or ""
    if eu and units and units[0] and len(gv) == 1:
        gv = [_conv(gv[0], units[0], eu)]
    if eu == "%" and units and units[0] == "%":
        pass
    if len(wv) == 1:
        return len(gv) >= 1 and any(_close(g, wv[0]) for g in gv[:1]) or (len(gv) == 1 and _close(gv[0], wv[0]))
    if len(gv) != len(wv):
        return False
    rest = list(wv)
    for g in gv:
        hit = next((i for i, e in enumerate(rest) if _close(g, e)), None)
        if hit is None:
            return False
        rest.pop(hit)
    return True


def _ocr(image: bytes) -> str:
    import httpx

    url = os.environ.get("MNEME_OCR_URL", "http://ocr:8100").rstrip("/") + "/ocr"
    last: Exception | None = None
    for _ in range(3):
        try:
            r = httpx.post(url, content=image, headers={"Content-Type": "application/octet-stream"}, timeout=90)
            r.raise_for_status()
            return str(r.json().get("text") or "")
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2)
    print("OCR failed:", type(last).__name__, file=sys.stderr)
    return ""


def run(images: bool, out_dir: Optional[Path]) -> dict:
    from services.ask_kernels import solve_text

    probs = {}
    for line in CORPUS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            p = json.loads(line)
            probs[p["id"]] = p
    items: list[tuple[dict, str, Optional[str], Optional[str]]] = []
    if images:
        from services.photo_ask_service import clean_ocr_text, guess_subject

        for line in MANIFEST.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            m = json.loads(line)
            p = probs[m["problem_id"]]
            data = (MANIFEST.parent / m["file"]).read_bytes()
            t0 = time.monotonic()
            raw = _ocr(data)
            ocr_ms = int((time.monotonic() - t0) * 1000)
            subj = guess_subject(raw)
            text = clean_ocr_text(raw, subj)
            items.append((dict(p, image=m["file"], ocr_ms=ocr_ms), text, subj, raw))
    else:
        items = [(p, p["text"], p.get("subject"), None) for p in probs.values()]
    per = defaultdict(lambda: {"n": 0, "answered": 0, "correct": 0})
    wrong, missed, rows = [], [], []
    lat = []
    for p, text, subj, raw in items:
        t0 = time.monotonic()
        try:
            sol = solve_text(text, subj if not images else subj)
        except Exception as exc:  # noqa: BLE001
            sol = None
            print("EXC", p["id"], type(exc).__name__, exc, file=sys.stderr)
        ms = (time.monotonic() - t0) * 1000
        lat.append(ms)
        st = per[p["type"]]
        st["n"] += 1
        row = {"id": p["id"], "type": p["type"], "ms": round(ms, 1), "kernel": sol.kernel if sol else None,
               "answer": sol.answer if sol else None, "answer_value": sol.answer_value if sol else None,
               "expected": p["answer"], "unit": p.get("unit")}
        if images:
            row.update({"image": p["image"], "ocr_text": raw, "ocr_ms": p["ocr_ms"]})
        if p.get("answer_kind") == "abstain":
            # 题目条件不足/矛盾：正确行为是不作答
            st["n"] -= 1
            if sol is None:
                row["result"] = "abstained_ok"
            else:
                wrong.append(row)
                row["result"] = "wrong"
                st["answered"] += 1
                st["n"] += 1
        elif sol is None:
            missed.append(row)
            row["result"] = "unanswered"
        else:
            st["answered"] += 1
            ok = False
            try:
                ok = match(sol, p)
            except Exception as exc:  # noqa: BLE001
                print("MATCHEXC", p["id"], exc, file=sys.stderr)
            if ok:
                st["correct"] += 1
                row["result"] = "correct"
            else:
                wrong.append(row)
                row["result"] = "wrong"
        rows.append(row)
    tot = {"n": sum(v["n"] for v in per.values()), "answered": sum(v["answered"] for v in per.values()),
           "correct": sum(v["correct"] for v in per.values())}
    report = {
        "mode": "images" if images else "text",
        "total": {**tot, "coverage": round(tot["answered"] / max(1, tot["n"]), 4),
                  "accuracy": round(tot["correct"] / max(1, tot["answered"]), 4), "confident_wrong": len(wrong),
                  "p50_ms": round(sorted(lat)[len(lat) // 2], 1) if lat else None,
                  "p95_ms": round(sorted(lat)[int(len(lat) * 0.95) - 1], 1) if lat else None},
        "per_type": {k: {**v, "coverage": round(v["answered"] / max(1, v["n"]), 3),
                         "accuracy": round(v["correct"] / max(1, v["answered"]), 3) if v["answered"] else None}
                     for k, v in sorted(per.items())},
        "wrong": wrong,
        "unanswered": [{"id": r["id"], "type": r["type"]} for r in missed],
    }
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"ask_eval_{report['mode']}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        (out_dir / f"ask_eval_{report['mode']}_rows.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", action="store_true")
    ap.add_argument("--out", default="reports/ask_eval")
    args = ap.parse_args()
    rep = run(args.images, Path(args.out))
    t = rep["total"]
    print(f"[{rep['mode']}] n={t['n']} answered={t['answered']} correct={t['correct']} coverage={t['coverage']:.1%} "
          f"accuracy={t['accuracy']:.1%} confident_wrong={t['confident_wrong']} p50={t['p50_ms']}ms p95={t['p95_ms']}ms")
    for k, v in rep["per_type"].items():
        print(f"  {k:16s} n={v['n']:3d} ans={v['answered']:3d} ok={v['correct']:3d} cov={v['coverage']:.0%} acc={v['accuracy'] if v['accuracy'] is None else format(v['accuracy'], '.0%')}")
    for w in rep["wrong"]:
        print("  WRONG", w["id"], "got", w["answer_value"], w.get("answer"), "expected", w["expected"], w.get("unit") or "")


if __name__ == "__main__":
    main()
