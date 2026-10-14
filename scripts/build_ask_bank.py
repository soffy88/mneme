"""生成拍照问题目“相似题”题库：services/ask_kernels/data/solved_bank.json。

来源：
1. tests/eval/ask_corpus/problems.jsonl 中被精确内核解出、且与期望答案一致的题（带内核分步解答）；
2. data/seed_questions.json 里带答案的种子题（只有答案，没有分步）。

用法：python scripts/build_ask_bank.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))


def main() -> None:
    from services.ask_kernels import solve_text
    sys.path.insert(0, str(ROOT / "tests" / "eval"))
    from run_ask_eval import match

    out = []
    corpus = ROOT / "tests/eval/ask_corpus/problems.jsonl"
    for line in corpus.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        p = json.loads(line)
        if p.get("answer_kind") == "abstain":
            continue
        sol = solve_text(p["text"], p.get("subject"))
        if sol is None or not match(sol, p):
            continue
        out.append({"text": p["text"], "answer": sol.answer, "steps": sol.steps[:8], "hint": sol.hint, "kernel": sol.kernel,
                    "subject": p.get("subject"), "source": "kernel_corpus"})
    seed = ROOT / "data/seed_questions.json"
    if seed.exists():
        data = json.loads(seed.read_text(encoding="utf-8"))
        for kc, items in (data.items() if isinstance(data, dict) else []):
            for q in items or []:
                if not isinstance(q, dict) or not q.get("question_text") or not q.get("correct_answer"):
                    continue
                ans = str(q["correct_answer"])
                opts = q.get("options") or []
                if len(ans) == 1 and ans in "ABCD" and opts:
                    hit = [o for o in opts if str(o).startswith(ans)]
                    ans = hit[0] if hit else ans
                text = q["question_text"] + ("  " + "  ".join(map(str, opts)) if opts else "")
                out.append({"text": text, "answer": ans, "steps": [], "hint": None, "kernel": None, "subject": "math",
                            "source": f"seed:{kc}"})
    dst = ROOT / "services/ask_kernels/data/solved_bank.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"wrote {len(out)} items to {dst}")


if __name__ == "__main__":
    main()
