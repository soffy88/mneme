#!/usr/bin/env python3
"""下载并构建「拍照问题目」确定性答题用的离线词典/诗词/成语库（不进 git，构建成 SQLite）。

数据源（全部宽松许可，固定 commit，逐文件 sha256 校验，清单见 data/ask_providers/MANIFEST.json）：
- ECDICT            skywind3000/ECDICT           MIT   英汉词典（音标、释义、词形变化、考试标签）
- chinese-poetry    chinese-poetry/chinese-poetry MIT   全唐诗/全宋诗/宋词/元曲/诗经/楚辞/曹操诗集 + 热度 rank
- chinese-xinhua    pwxcoo/chinese-xinhua        MIT   成语（idiom.json）

用法（宿主机或任意 python3.12 容器里，需要能访问 raw.githubusercontent.com）：

    python3 scripts/ask_data/fetch_and_build.py              # 下载(带缓存)+校验+构建
    python3 scripts/ask_data/fetch_and_build.py --pin        # 维护者：按固定 commit 重新生成 MANIFEST
    MNEME_ASK_DATA_DIR=/path python3 ...                     # 输出目录（默认 data/external/ask_providers）

繁转简需要 opencc-python-reimplemented（Apache-2.0，仅构建期用）：
    pip install opencc-python-reimplemented==0.1.7
输出：ecdict.sqlite / poetry.sqlite / idiom.sqlite（运行时只读打开）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data" / "ask_providers" / "MANIFEST.json"
SOURCES = {
    "ecdict": {"repo": "skywind3000/ECDICT", "commit": "bc015ed2e24a7abef49fc6dbbb7fe32c1dadaf8b", "license": "MIT"},
    "poetry": {"repo": "chinese-poetry/chinese-poetry", "commit": "b8594f81a89752241442f2ce267d6f66f96704ee", "license": "MIT"},
    "xinhua": {"repo": "pwxcoo/chinese-xinhua", "commit": "fe6d6c2e8baa82187f4c96bbe042e43f96c05666", "license": "MIT"},
}
_POETRY_PAT = re.compile(
    r"^(全唐诗/poet\.(tang|song)\.\d+\.json|全唐诗/唐诗三百首\.json|宋词/ci\.song\.\d+\.json|宋词/宋词三百首\.json"
    r"|元曲/yuanqu\.json|诗经/shijing\.json|楚辞/chuci\.json|曹操诗集/caocao\.json|五代诗词/.+\.json"
    r"|rank/(poet|ci)/(poet|ci)\.(tang|song)\.rank\.\d+\.json|LICENSE)$"
)


def out_dir() -> Path:
    d = Path(os.environ.get("MNEME_ASK_DATA_DIR") or (ROOT / "data" / "external" / "ask_providers"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def raw_url(src: str, path: str) -> str:
    s = SOURCES[src]
    return f"https://raw.githubusercontent.com/{s['repo']}/{s['commit']}/" + urllib.parse.quote(path)


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "mneme-ask-data/1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def pin() -> None:
    files: list[dict] = []
    for p in ("ecdict.csv", "LICENSE"):
        files.append({"src": "ecdict", "path": p})
    for p in ("data/idiom.json", "LICENSE"):
        files.append({"src": "xinhua", "path": p})
    s = SOURCES["poetry"]
    tree = json.loads(fetch(f"https://api.github.com/repos/{s['repo']}/git/trees/{s['commit']}?recursive=1"))["tree"]
    for e in tree:
        if e["type"] == "blob" and _POETRY_PAT.match(e["path"]):
            files.append({"src": "poetry", "path": e["path"]})
    cache = out_dir() / "_cache"
    for f in files:
        data = get_cached(cache, f["src"], f["path"], expect=None)
        f["sha256"] = hashlib.sha256(data).hexdigest()
        f["bytes"] = len(data)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({"sources": SOURCES, "files": files}, ensure_ascii=False, indent=1) + "\n")
    print(f"pinned {len(files)} files → {MANIFEST}")


def get_cached(cache: Path, src: str, path: str, expect: str | None) -> bytes:
    local = cache / src / path
    if local.exists():
        data = local.read_bytes()
        if expect is None or hashlib.sha256(data).hexdigest() == expect:
            return data
    data = fetch(raw_url(src, path))
    if expect is not None and hashlib.sha256(data).hexdigest() != expect:
        raise SystemExit(f"checksum mismatch: {src}/{path}")
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_bytes(data)
    return data


# ── ECDICT ──────────────────────────────────────────────────────────────────


def build_ecdict(csv_bytes: bytes, dst: Path) -> int:
    import csv
    import io

    tmp = dst.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(
        """
        CREATE TABLE words(word TEXT PRIMARY KEY COLLATE NOCASE, phonetic TEXT, translation TEXT, pos TEXT,
                           tag TEXT, exchange TEXT, frq INTEGER, bnc INTEGER, collins INTEGER, oxford INTEGER);
        CREATE TABLE forms(form TEXT COLLATE NOCASE, lemma TEXT, kind TEXT);
        """
    )
    n = 0
    word_re = re.compile(r"^[A-Za-z][A-Za-z'\- ]{0,40}$")
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    for row in reader:
        w = (row.get("word") or "").strip()
        tr = (row.get("translation") or "").strip()
        if not w or not tr or not word_re.match(w):
            continue

        def num(k: str) -> int:
            try:
                return int(row.get(k) or 0)
            except ValueError:
                return 0

        frq, bnc, collins, oxford = num("frq"), num("bnc"), num("collins"), num("oxford")
        tag = (row.get("tag") or "").strip()
        common = tag or collins > 0 or oxford or (0 < bnc <= 60000) or (0 < frq <= 60000)
        if not common and (" " in w or len(w) > 18):
            continue
        if not common and not (row.get("exchange") or "").strip():
            continue
        ex = (row.get("exchange") or "").strip()
        try:
            db.execute(
                "INSERT INTO words VALUES (?,?,?,?,?,?,?,?,?,?)",
                (w, (row.get("phonetic") or "").strip(), tr.replace("\\n", "\n"), (row.get("pos") or "").strip(),
                 tag, ex, frq, bnc, collins, oxford),
            )
        except sqlite3.IntegrityError:
            continue
        n += 1
        for part in ex.split("/"):
            if ":" not in part:
                continue
            k, v = part.split(":", 1)
            if k in {"p", "d", "i", "3", "r", "t", "s"} and v and v.lower() != w.lower():
                db.execute("INSERT INTO forms VALUES (?,?,?)", (v, w, k))
    db.execute("CREATE INDEX forms_form ON forms(form)")
    db.commit()
    db.execute("VACUUM")
    db.close()
    tmp.replace(dst)
    return n


# ── 诗词 ─────────────────────────────────────────────────────────────────────

_CLAUSE_SPLIT = re.compile(r"[，。？！；：、,.?!;:]")


# opencc t2s 不处理的异体字（诗词正文里常见；只作用于正文，不动作者/标题里的姓氏「沈」）
_VARIANTS = str.maketrans({"隣": "邻", "峯": "峰", "鴈": "雁", "牀": "床", "簷": "檐", "汙": "污", "衹": "只",
                           "祇": "只", "秖": "只", "箇": "个", "崑": "昆", "絃": "弦", "缾": "瓶", "鞦": "秋",
                           "韆": "千", "甦": "苏", "迴": "回", "沈": "沉", "閒": "闲", "啣": "衔", "牕": "窗", "窻": "窗"})


def fix_variants(s: str) -> str:
    return s.translate(_VARIANTS)


def norm_clause(s: str) -> str:
    return re.sub(r"[^\u3400-\u9fff\U00020000-\U0002ffff]", "", s)


def build_poetry(files: dict[str, bytes], dst: Path) -> int:
    try:
        from opencc import OpenCC  # opencc-python-reimplemented
    except ImportError:
        raise SystemExit("need: pip install opencc-python-reimplemented==0.1.7")
    cc = OpenCC("t2s")
    rank: dict[tuple[str, str], float] = {}
    for path, data in files.items():
        if not path.startswith("rank/"):
            continue
        for r in json.loads(data):
            hits = sum(float(r.get(k) or 0) for k in ("baidu", "so360", "bing", "google"))
            key = (cc.convert(str(r.get("author") or "")), cc.convert(str(r.get("title") or r.get("rhythmic") or "")))
            rank[key] = max(rank.get(key, 0.0), math.log10(1 + hits))
    famous: set[tuple[str, str]] = set()
    for path in ("全唐诗/唐诗三百首.json", "宋词/宋词三百首.json"):
        for p in json.loads(files.get(path, b"[]")):
            famous.add((cc.convert(str(p.get("author") or "")), cc.convert(str(p.get("title") or p.get("rhythmic") or ""))))

    tmp = dst.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(
        """
        CREATE TABLE poems(id INTEGER PRIMARY KEY, title TEXT, author TEXT, dynasty TEXT, collection TEXT,
                           body TEXT, rank REAL);
        CREATE TABLE clauses(norm TEXT, poem_id INTEGER, idx INTEGER, head TEXT, tail TEXT, len INTEGER);
        """
    )
    pid = 0
    seen: set[tuple[str, str]] = set()

    def add(title: str, author: str, dynasty: str, coll: str, paras: list[str], boost: float = 0.0) -> None:
        nonlocal pid
        paras = [fix_variants(cc.convert(str(p)).strip()) for p in paras if str(p).strip()]
        if not paras:
            return
        title, author = cc.convert(title or "").strip(), cc.convert(author or "").strip()
        body = "\n".join(paras)
        key = (author, norm_clause(body)[:40])
        if key in seen:
            return
        seen.add(key)
        pid += 1
        r = rank.get((author, title), 0.0) + (3.0 if (author, title) in famous else 0.0) + boost
        db.execute("INSERT INTO poems VALUES (?,?,?,?,?,?,?)", (pid, title, author, dynasty, coll, body, r))
        idx = 0
        for para in paras:
            for c in _CLAUSE_SPLIT.split(para):
                n = norm_clause(c)
                if len(n) < 2:
                    continue
                db.execute("INSERT INTO clauses VALUES (?,?,?,?,?,?)", (n, pid, idx, n[:2], n[-2:], len(n)))
                idx += 1

    # 课本常考、但 chinese-poetry 未收的先秦/魏晋作品（公有领域原文，人工校对），置顶排序
    sup = ROOT / "data" / "ask_providers" / "supplement_poems.json"
    if sup.exists():
        for it in json.loads(sup.read_text()):
            add(it["title"], it["author"], it["dynasty"], "课本补充", it["paragraphs"], boost=8.0)
    order = sorted(files)
    for path in order:
        data = files[path]
        if path.startswith("rank/") or path.endswith("LICENSE") or "三百首" in path:
            continue
        items = json.loads(data)
        if isinstance(items, dict):
            items = [items]
        if path.startswith("全唐诗/poet.tang"):
            dyn, coll = "唐", "全唐诗"
        elif path.startswith("全唐诗/poet.song"):
            dyn, coll = "宋", "全宋诗"
        elif path.startswith("宋词/"):
            dyn, coll = "宋", "宋词"
        elif path.startswith("元曲/"):
            dyn, coll = "元", "元曲"
        elif path.startswith("诗经/"):
            dyn, coll = "先秦", "诗经"
        elif path.startswith("楚辞/"):
            dyn, coll = "先秦", "楚辞"
        elif path.startswith("曹操诗集/"):
            dyn, coll = "东汉", "曹操诗集"
        else:
            dyn, coll = "五代", "五代诗词"
        for it in items:
            if not isinstance(it, dict):
                continue
            paras = it.get("paragraphs") or it.get("content") or []
            title = str(it.get("title") or it.get("rhythmic") or "")
            author = str(it.get("author") or ("曹操" if coll == "曹操诗集" else ("佚名" if coll == "诗经" else "")))
            if coll == "诗经" and it.get("chapter"):
                title = f"{title}（{it.get('chapter')}·{it.get('section') or ''}）".replace("·）", "）")
            add(title, author, str(it.get("dynasty") or dyn) if coll == "元曲" else dyn, coll, list(paras))
    db.execute("CREATE INDEX clauses_norm ON clauses(norm)")
    db.execute("CREATE INDEX clauses_head ON clauses(head, len)")
    db.execute("CREATE INDEX clauses_tail ON clauses(tail, len)")
    db.execute("CREATE INDEX clauses_pid ON clauses(poem_id, idx)")
    db.commit()
    db.execute("VACUUM")
    db.close()
    tmp.replace(dst)
    return pid


# ── 成语 ─────────────────────────────────────────────────────────────────────


def build_idiom(data: bytes, dst: Path) -> int:
    tmp = dst.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.execute(
        "CREATE TABLE idioms(word TEXT PRIMARY KEY, pinyin TEXT, explanation TEXT, derivation TEXT, example TEXT)"
    )
    n = 0
    for it in json.loads(data):
        w = str(it.get("word") or "").strip()
        if not w:
            continue
        clean = lambda v: re.sub(r"\s+", " ", str(v or "")).strip().strip("“”")  # noqa: E731
        try:
            db.execute(
                "INSERT INTO idioms VALUES (?,?,?,?,?)",
                (w, clean(it.get("pinyin")), clean(it.get("explanation")), clean(it.get("derivation")),
                 clean(it.get("example"))),
            )
            n += 1
        except sqlite3.IntegrityError:
            continue
    db.commit()
    db.execute("VACUUM")
    db.close()
    tmp.replace(dst)
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", action="store_true", help="re-pin MANIFEST from the fixed commits")
    ap.add_argument("--only", choices=["ecdict", "poetry", "idiom"], default=None)
    args = ap.parse_args()
    if args.pin:
        pin()
    man = json.loads(MANIFEST.read_text())
    d = out_dir()
    cache = d / "_cache"
    by_src: dict[str, dict[str, bytes]] = {"ecdict": {}, "poetry": {}, "xinhua": {}}
    want = {"ecdict": "ecdict", "poetry": "poetry", "idiom": "xinhua"}
    for f in man["files"]:
        if args.only and f["src"] != want[args.only]:
            continue
        by_src[f["src"]][f["path"]] = get_cached(cache, f["src"], f["path"], f["sha256"])
    if not args.only or args.only == "ecdict":
        print("ecdict words:", build_ecdict(by_src["ecdict"]["ecdict.csv"], d / "ecdict.sqlite"))
    if not args.only or args.only == "poetry":
        print("poems:", build_poetry(by_src["poetry"], d / "poetry.sqlite"))
    if not args.only or args.only == "idiom":
        print("idioms:", build_idiom(by_src["xinhua"]["data/idiom.json"], d / "idiom.sqlite"))
    (d / "BUILD.json").write_text(json.dumps({"manifest_sources": man["sources"]}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
