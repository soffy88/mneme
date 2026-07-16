"""FC-5 subprocess runner —— 独立 agent 进程，**零 DB**。经 HTTP 驱动 pilot 到 complete。

由 harness 以剥离 DB 凭据的 env（+ PGAPPNAME=mneme-agent 标记）spawn。本进程无任何 DB
import——只 build_tutor_loop（oservi + mneme_core 纯库）+ 复用 e2e 的 scripted caller。
argv: <student_id> <api_base> <kc_ids_csv>；exit 0 iff session status=="completed"。
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mneme_agent.assembly.tutor_loop import build_tutor_loop  # noqa: E402
import test_tutor_loop_e2e as T  # noqa: E402  复用 scripted caller / verifier（零 DB）


def main() -> None:
    student_id, api_base, kcs_csv = sys.argv[1], sys.argv[2], sys.argv[3]
    kc_ids = kcs_csv.split(",")
    loop = build_tutor_loop(
        api_base=api_base,
        student_id=student_id,
        kc_ids=kc_ids,
        llm_caller=T._make_caller(),
        verifier_llm=T._make_verifier_llm(),
        max_iterations=150,
    )
    r = asyncio.run(loop.session(task="帮我把这三条 KC 学到过门"))
    print(json.dumps({"status": r.get("status"), "iterations": r.get("iterations")}))
    sys.exit(0 if r.get("status") == "completed" else 1)


if __name__ == "__main__":
    main()
