"""mneme —— 善学记命令行客户端（W5 Part C，轻量版）。

红线：本 CLI 只是既有 HTTP 面（/v1/auth/*、/mcp/*）的瘦客户端，跟人类用户走
同一套接口、同一套 JWT 鉴权、同一套 guard/门控（_ensure_student_self/
_ensure_student_access、SubmitAnswer 的 verdict_guard 等）——不直连 DB、不导入
任何 oprim/oskill/omodul，结构上不可能绕过服务层已有的红线。

不引入新依赖（argparse + 已有的 httpx），token 落本地
`~/.config/mneme/token`（明文，仅供本机开发/测试使用；生产多用户场景应改用
更安全的凭据存储，这是后续工作）。
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

import httpx

DEFAULT_API_BASE = os.environ.get("MNEME_API_BASE", "http://localhost:8000")
_TOKEN_PATH = Path.home() / ".config" / "mneme" / "token"


def _load_token() -> Optional[str]:
    if _TOKEN_PATH.exists():
        return _TOKEN_PATH.read_text(encoding="utf-8").strip() or None
    return None


def _save_token(token: str) -> None:
    _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_PATH.write_text(token, encoding="utf-8")
    _TOKEN_PATH.chmod(0o600)


class MnemeClient:
    """/v1/auth/* + /mcp/* 的瘦 HTTP 封装——不做任何业务判断，纯转发。"""

    def __init__(
        self,
        base_url: str = DEFAULT_API_BASE,
        token: Optional[str] = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token or _load_token()
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    def _request(
        self, method: str, path: str, *, timeout: float = 20.0, **kwargs: Any
    ) -> dict:
        with httpx.Client(
            base_url=self.base_url, timeout=timeout, transport=self.transport
        ) as client:
            resp = client.request(method, path, headers=self._headers(), **kwargs)
        if resp.status_code >= 400:
            raise RuntimeError(f"{method} {path} -> {resp.status_code}: {resp.text}")
        return resp.json()

    def send_email_code(self, email: str) -> dict:
        return self._request("POST", "/v1/auth/send-email-code", json={"email": email})

    def login_email(self, email: str, code: str) -> dict:
        return self._request(
            "POST", "/v1/auth/login-email", json={"email": email, "code": code}
        )

    def whoami(self) -> dict:
        return self._request("GET", "/v1/auth/me")

    def mcp(self, tool_name: str, payload: dict) -> dict:
        return self._request("POST", f"/mcp/{tool_name}", json=payload)

    def book_compile(self, textbook_id: str) -> dict:
        return self._request("POST", "/v1/books/compile", json={"textbook_id": textbook_id})

    def book_status(self, book_id: str) -> dict:
        return self._request("GET", f"/v1/books/{book_id}/status")

    def book_textbooks(self) -> dict:
        return self._request("GET", "/v1/books/compile/textbooks")

    def research(self, question: str, persona_slug: Optional[str] = None) -> dict:
        payload: dict[str, Any] = {"question": question}
        if persona_slug:
            payload["persona_slug"] = persona_slug
        # 同步生成：检索 + 一次 LLM 调用，推理模型回退时可能要一两分钟
        return self._request("POST", "/v1/research", json=payload, timeout=240.0)

    def research_get(self, research_id: str) -> dict:
        return self._request("GET", f"/v1/research/{research_id}")

    def research_list(self, limit: int = 20) -> dict:
        return self._request("GET", "/v1/research", params={"limit": limit})


def _print(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_login(args: argparse.Namespace) -> None:
    client = MnemeClient(base_url=args.api_base)
    sent = client.send_email_code(args.email)
    _print(sent)
    code = args.code or getpass.getpass("验证码: ")
    result = client.login_email(args.email, code)
    _save_token(result["token"])
    print(f"登录成功，token 已保存到 {_TOKEN_PATH}")
    _print(result["user"])


def cmd_whoami(args: argparse.Namespace) -> None:
    client = MnemeClient(base_url=args.api_base)
    _print(client.whoami())


def cmd_review_queue(args: argparse.Namespace) -> None:
    client = MnemeClient(base_url=args.api_base)
    _print(
        client.mcp(
            "GetReviewQueue",
            {"student_id": args.student_id, "kc_ids": args.kc},
        )
    )


def cmd_request_question(args: argparse.Namespace) -> None:
    client = MnemeClient(base_url=args.api_base)
    _print(
        client.mcp("RequestQuestion", {"student_id": args.student_id, "kc_id": args.kc})
    )


def cmd_submit_answer(args: argparse.Namespace) -> None:
    client = MnemeClient(base_url=args.api_base)
    payload: dict[str, Any] = {
        "student_id": args.student_id,
        "question_id": args.question_id,
        "answer": args.answer,
    }
    if args.time_spent is not None:
        payload["time_spent_seconds"] = args.time_spent
    _print(client.mcp("SubmitAnswer", payload))


def cmd_bind_partner(args: argparse.Namespace) -> None:
    client = MnemeClient(base_url=args.api_base)
    _print(
        client.mcp(
            "BindPartnerChannel",
            {
                "student_id": args.student_id,
                "channel": args.channel,
                "target": args.target,
            },
        )
    )


def cmd_grant(args: argparse.Namespace) -> None:
    client = MnemeClient(base_url=args.api_base)
    payload: dict[str, Any] = {"student_id": args.student_id}
    if args.tools is not None:
        payload["enabled_tools"] = args.tools.split(",") if args.tools else []
    if args.models is not None:
        payload["allowed_models"] = args.models.split(",") if args.models else []
    _print(client.mcp("SetUserGrant", payload))


def cmd_audit_log(args: argparse.Namespace) -> None:
    client = MnemeClient(base_url=args.api_base)
    _print(
        client.mcp("GetAuditLog", {"student_id": args.student_id, "limit": args.limit})
    )


_BOOK_DONE = ("ready", "partial", "error")


def cmd_book_compile(args: argparse.Namespace) -> None:
    client = MnemeClient(base_url=args.api_base)
    if args.list:
        _print(client.book_textbooks())
        return
    if not args.textbook_id:
        raise RuntimeError("需要 --textbook-id（或用 --list 查看可编译的教材）")
    job = client.book_compile(args.textbook_id)
    _print(job)
    if args.wait:
        _wait_book(client, job["book_id"], args.interval)


def _wait_book(client: MnemeClient, book_id: str, interval: float) -> None:
    import time

    while True:
        st = client.book_status(book_id)
        if st.get("status") in _BOOK_DONE:
            _print(st)
            return
        print(f"[{st.get('status')}] {book_id} …", file=sys.stderr)
        time.sleep(interval)


def cmd_book_status(args: argparse.Namespace) -> None:
    client = MnemeClient(base_url=args.api_base)
    if args.wait:
        _wait_book(client, args.book_id, args.interval)
    else:
        _print(client.book_status(args.book_id))


def _format_research(rep: dict) -> str:
    """把研究报告排成终端可读的文本：每条论断后面跟 [书 p.页]。"""
    r = rep.get("report") or {}
    lines = [f"# {r.get('title') or '研究报告'}  ({rep.get('status')})", ""]

    def cite(p: dict) -> str:
        cs = p.get("citations") or []
        return " ".join(
            f"[{c.get('source_id')} 《{c.get('book_name') or '教材'}》 p.{c.get('page_number')}]"
            for c in cs
        )

    if r.get("summary"):
        lines += [f"{r['summary']['text']} {cite(r['summary'])}", ""]
    for sec in r.get("sections") or []:
        lines.append(f"## {sec.get('heading')}")
        for p in sec.get("points") or []:
            lines.append(f"- {p.get('text')} {cite(p)}")
        lines.append("")
    for u in r.get("unsupported") or []:
        lines.append(f"- （{u.get('note')}）{u.get('text')}")
    for g in r.get("gaps") or []:
        lines.append(f"* {g}")
    srcs = rep.get("sources") or []
    if srcs:
        lines += ["", "来源："]
        for s in srcs:
            lines.append(
                f"  {s.get('id')} 《{s.get('book_name')}》 p.{s.get('page_number')} chunk={s.get('chunk_id')}"
            )
    return "\n".join(lines)


def cmd_research(args: argparse.Namespace) -> None:
    client = MnemeClient(base_url=args.api_base)
    if args.list:
        _print(client.research_list(args.limit))
        return
    if args.id:
        rep = client.research_get(args.id)
    elif args.question:
        rep = client.research(args.question, args.persona)
    else:
        raise RuntimeError("需要一个问题（或 --id / --list）")
    print(json.dumps(rep, ensure_ascii=False, indent=2) if args.json else _format_research(rep))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mneme", description="善学记命令行客户端")
    parser.add_argument(
        "--api-base", default=DEFAULT_API_BASE, help="后端地址（默认读 MNEME_API_BASE）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="邮箱验证码登录")
    p_login.add_argument("--email", required=True)
    p_login.add_argument("--code", help="不传则交互式输入")
    p_login.set_defaults(func=cmd_login)

    p_whoami = sub.add_parser("whoami", help="查看当前登录用户")
    p_whoami.set_defaults(func=cmd_whoami)

    p_rq = sub.add_parser("review-queue", help="查询待复习队列")
    p_rq.add_argument("--student-id", required=True)
    p_rq.add_argument("--kc", action="append", required=True, help="可重复传多个 KC")
    p_rq.set_defaults(func=cmd_review_queue)

    p_req = sub.add_parser("request-question", help="为某 KC 出下一题")
    p_req.add_argument("--student-id", required=True)
    p_req.add_argument("--kc", required=True)
    p_req.set_defaults(func=cmd_request_question)

    p_sub = sub.add_parser("submit-answer", help="提交一次作答")
    p_sub.add_argument("--student-id", required=True)
    p_sub.add_argument("--question-id", required=True)
    p_sub.add_argument("--answer", required=True)
    p_sub.add_argument("--time-spent", type=int, default=None)
    p_sub.set_defaults(func=cmd_submit_answer)

    p_bind = sub.add_parser("bind-partner", help="绑定 Partner 推送渠道")
    p_bind.add_argument("--student-id", required=True)
    p_bind.add_argument("--channel", required=True, choices=["wecom", "feishu"])
    p_bind.add_argument("--target", required=True, help="群 webhook URL")
    p_bind.set_defaults(func=cmd_bind_partner)

    p_grant = sub.add_parser("grant", help="（admin）设置某学生的工具/模型授权")
    p_grant.add_argument("--student-id", required=True)
    p_grant.add_argument("--tools", help="逗号分隔工具名，如 BindPartnerChannel")
    p_grant.add_argument("--models", help="逗号分隔模型名")
    p_grant.set_defaults(func=cmd_grant)

    p_audit = sub.add_parser("audit-log", help="查看某学生的操作审计")
    p_audit.add_argument("--student-id", required=True)
    p_audit.add_argument("--limit", type=int, default=100)
    p_audit.set_defaults(func=cmd_audit_log)

    p_bc = sub.add_parser("book-compile", help="生成一本活书（约 $0.5/本，每人每天有限额）")
    p_bc.add_argument("--textbook-id", help="教材 id，如 RENJIAO-G1-MATH-S")
    p_bc.add_argument("--list", action="store_true", help="列出可编译的教材")
    p_bc.add_argument("--wait", action="store_true", help="提交后轮询直到完成")
    p_bc.add_argument("--interval", type=float, default=10.0, help="轮询间隔秒数")
    p_bc.set_defaults(func=cmd_book_compile)

    p_bs = sub.add_parser("book-status", help="查询活书编译状态")
    p_bs.add_argument("book_id")
    p_bs.add_argument("--wait", action="store_true", help="轮询直到完成")
    p_bs.add_argument("--interval", type=float, default=10.0)
    p_bs.set_defaults(func=cmd_book_status)

    p_rs = sub.add_parser("research", help="基于本地教材库的研究报告（每条论断带出处）")
    p_rs.add_argument("question", nargs="?", help="要研究的问题，如 勾股定理的证明方法")
    p_rs.add_argument("--persona", help="人格 slug（只影响语气）")
    p_rs.add_argument("--id", help="查看一份已有报告")
    p_rs.add_argument("--list", action="store_true", help="列出我的研究记录")
    p_rs.add_argument("--limit", type=int, default=20)
    p_rs.add_argument("--json", action="store_true", help="输出原始 JSON")
    p_rs.set_defaults(func=cmd_research)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except RuntimeError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
