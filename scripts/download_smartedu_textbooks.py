#!/usr/bin/env python3
"""
国家中小学智慧教育平台 (basic.smartedu.cn) 教材批量下载脚本。

用法：
  python scripts/download_smartedu_textbooks.py [--subjects 物理 语文 英语 历史] [--out ./curriculum_standards]

原理：
  1. 拉取目录版本清单（无需登录）
  2. 下载所有 part_NNN.json 目录文件，过滤目标学科
  3. 每本书拉取 detail.json → 提取 65/document/{id_b}/pdf.pdf 链接（无需登录）
  4. 下载 PDF 到 --out 目录，文件名格式: {学段}_{科目}_{标题}.pdf

注意：65/document 路径目前无需 token；若平台收紧权限导致 403，
      需在浏览器登录后从 localStorage 提取 access_token，
      以 --token <access_token> 参数传入。
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("缺少依赖：pip install requests")

# ── 常量 ──────────────────────────────────────────────────────
MANIFEST_URL = (
    "https://s-file-2.ykt.cbern.com.cn"
    "/zxx/ndrs/resources/tch_material/version/data_version.json"
)
DETAIL_TMPL  = (
    "https://s-file-{n}.ykt.cbern.com.cn"
    "/zxx/ndrs/resources/tch_material/details/{book_id}.json"
)
DETAIL_V2_TMPL = (
    "https://s-file-{n}.ykt.cbern.com.cn"
    "/zxx/ndrv2/resources/tch_material/details/{book_id}.json"
)
PDF_TMPL     = "https://r{n}-ndr.ykt.cbern.com.cn/edu_product/65/document/{id_b}/pdf.pdf"

HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer":         "https://basic.smartedu.cn/",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate",   # 不加 br 避免需要 brotli 依赖
}

# 学科 tag_dimension_id
SUBJECT_DIM  = "zxxxk"
STAGE_DIM    = "zxxxd"   # 学段：小学/初中/高中

# 学段简写映射（用于文件名前缀）
STAGE_PREFIX = {
    "小学": "E",   # Elementary
    "初中": "M",   # Middle
    "高中": "H",   # High
}

# 默认出版社白名单（None = 不过滤）
# 广东使用人教版/统编版为主；历史科目 publisher 标签为空（实际是统编版）
DEFAULT_PUBLISHERS = {
    "人教版",
    "统编版",
    "人教版（PEP）（主编：吴欣）",   # 小学英语主流
    "人教版（精通）（主编：苗兴伟）",
    "人教版（精通）（主编：郝建平）",
    "人教版（一年级起点）（主编：吴欣）",
    "人教A版",
}
PUBLISHER_DIM = "zxxbb"  # 出版社维度


def get(session: requests.Session, url: str, token: str | None = None,
        stream: bool = False, retry: int = 3) -> requests.Response:
    """带重试的 GET，自动附加 token（query param 方式）。"""
    params = {"accessToken": token} if token else {}
    last_exc: Exception | None = None
    last_r: requests.Response | None = None
    for i in range(retry):
        try:
            r = session.get(url, headers=HEADERS, params=params,
                            stream=stream, timeout=60)
            last_r = r
            if r.status_code == 200:
                return r
            if r.status_code == 403 and not token:
                print(f"  [403] {url[:80]}… 可能需要 --token，跳过")
                return r
            print(f"  [HTTP {r.status_code}] {url[:80]}… 重试 {i+1}/{retry}")
        except Exception as e:
            last_exc = e
            print(f"  [ERR] {e}  重试 {i+1}/{retry}")
        time.sleep(2 ** i)
    if last_r is not None:
        return last_r
    raise RuntimeError(f"请求失败：{url}") from last_exc


def fetch_catalog(session: requests.Session) -> list[dict]:
    """下载全部目录 part_*.json，返回合并列表。"""
    print("→ 获取目录清单…")
    manifest = get(session, MANIFEST_URL).json()
    raw_urls = manifest["urls"]
    # urls 字段是逗号分隔字符串（而非列表）
    if isinstance(raw_urls, str):
        urls: list[str] = [u.strip() for u in raw_urls.split(",") if u.strip()]
    else:
        urls = list(raw_urls)
    print(f"  {len(urls)} 个分片文件")
    all_books: list[dict] = []
    for i, url in enumerate(urls, 1):
        print(f"  [{i}/{len(urls)}] {url.split('/')[-1]}", end=" … ", flush=True)
        part = get(session, url).json()
        print(f"{len(part)} 条")
        all_books.extend(part)
    print(f"  总计 {len(all_books)} 条目录")
    return all_books


def tag_value(book: dict, dim_id: str) -> str:
    """提取 tag_list 中指定维度的 tag_name（首个匹配）。"""
    for t in book.get("tag_list", []):
        if t.get("tag_dimension_id") == dim_id:
            return t.get("tag_name", "")
    return ""


def filter_books(all_books: list[dict], subjects: list[str],
                 publishers: set[str] | None = None) -> list[dict]:
    """过滤：目标学科 + 电子教材标签 + 出版社（可选）。"""
    history_variants = {"历史", "中国历史", "世界历史"}
    subject_set: set[str] = set()
    for s in subjects:
        subject_set.add(s)
        if s == "历史":
            subject_set |= history_variants

    result = []
    for b in all_books:
        subj = tag_value(b, SUBJECT_DIM)
        if subj not in subject_set:
            continue
        tags = {t.get("tag_name", "") for t in b.get("tag_list", [])}
        if "电子教材" not in tags and "教材" not in tags:
            continue
        # 出版社过滤（历史科目 publisher 标签常为空，默认放行）
        if publishers is not None:
            pub = tag_value(b, PUBLISHER_DIM)
            is_history = subj in history_variants or subj == "历史"
            if pub and not is_history and pub not in publishers:
                continue
        result.append(b)
    return result


def _extract_id_b_from_detail(detail: dict) -> str | None:
    """从 detail dict 提取 id_b（32 位 hex），仅老格式（65/document 路径）。"""
    thumbs = (detail.get("custom_properties") or {}).get("thumbnails", [])
    for thumb in thumbs:
        m = re.search(r"/document/([0-9a-f]{32})/", thumb)
        if m:
            return m.group(1)
    for item in (detail.get("ti_items") or []):
        for storage in (item.get("ti_storages") or []):
            m = re.search(r"/65/document/([0-9a-f]{32})/", storage)
            if m:
                return m.group(1)
    return None


def _extract_pdf_url_from_detail(detail: dict) -> str | None:
    """从 ndrv2 detail 提取私有 CDN 的完整 PDF URL。"""
    for item in (detail.get("ti_items") or []):
        if item.get("ti_format") != "pdf":
            continue
        for storage in (item.get("ti_storages") or []):
            if storage.endswith(".pdf"):
                return storage
    return None


def get_download_info(session: requests.Session, book_id: str) -> dict | None:
    """返回 {'mode': 'public'|'token', 'url': ...} 或 None。"""
    # 先尝试 ndrs（老格式，有 65/document id_b → 公开访问）
    for mirror in (2, 1, 3):
        url = DETAIL_TMPL.format(n=mirror, book_id=book_id)
        r = get(session, url, retry=2)
        if r.status_code != 200:
            continue
        try:
            detail = r.json()
        except Exception:
            continue
        id_b = _extract_id_b_from_detail(detail)
        if id_b:
            pdf_url = PDF_TMPL.format(n=1, id_b=id_b)
            return {"mode": "public", "url": pdf_url, "id_b": id_b}
        # ndrs 能取到 detail 但是新格式，尝试 ndrv2 找私有 URL
        pdf_url = _extract_pdf_url_from_detail(detail)
        if pdf_url:
            return {"mode": "token", "url": pdf_url}

    # ndrs 失败，尝试 ndrv2
    for mirror in (2, 1, 3):
        url = DETAIL_V2_TMPL.format(n=mirror, book_id=book_id)
        r = get(session, url, retry=2)
        if r.status_code != 200:
            continue
        try:
            detail = r.json()
        except Exception:
            continue
        id_b = _extract_id_b_from_detail(detail)
        if id_b:
            pdf_url = PDF_TMPL.format(n=1, id_b=id_b)
            return {"mode": "public", "url": pdf_url}
        pdf_url = _extract_pdf_url_from_detail(detail)
        if pdf_url:
            return {"mode": "token", "url": pdf_url}

    return None


def safe_filename(title: str, stage: str, subject: str) -> str:
    """生成安全文件名：{学段前缀}_{科目}_{标题}.pdf"""
    prefix = STAGE_PREFIX.get(stage, stage or "K")
    # 替换不安全字符
    clean_title = re.sub(r'[\\/:*?"<>|]', "_", title)
    clean_title = clean_title.strip().replace(" ", "")
    return f"{prefix}_{subject}_{clean_title}.pdf"


def _try_download_url(session: requests.Session, pdf_url: str,
                      out_path: Path, token: str | None) -> bool:
    """尝试从单个 URL 下载到 out_path。成功返回 True。"""
    url_with_token = pdf_url + (f"?accessToken={token}" if token else "")
    try:
        r = session.get(url_with_token, headers=HEADERS, stream=True, timeout=180)
        if r.status_code != 200:
            print(f"[HTTP {r.status_code}]", end=" ", flush=True)
            return False
        total = 0
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
                total += len(chunk)
        size_mb = total / 1_048_576
        if total < 10_000:  # 小于 10KB 大概率是错误页
            out_path.unlink(missing_ok=True)
            print(f"[TINY {total}B]", end=" ", flush=True)
            return False
        print(f"OK ({size_mb:.1f} MB)")
        return True
    except Exception as e:
        print(f"[ERR: {e}]", end=" ", flush=True)
        out_path.unlink(missing_ok=True)
        return False


def download_book(session: requests.Session, book: dict, out_dir: Path,
                  token: str | None, dry_run: bool) -> bool:
    """下载单本教材。返回是否成功。"""
    book_id = book["id"]
    title   = book.get("title", book_id)
    stage   = tag_value(book, STAGE_DIM)
    subject = tag_value(book, SUBJECT_DIM)

    filename = safe_filename(title, stage, subject)
    out_path = out_dir / filename

    if out_path.exists():
        print(f"  [已存在] {filename}")
        return True

    print(f"  ↓ {title}", end=" … ", flush=True)

    info = get_download_info(session, book_id)
    if not info:
        print("[SKIP] 无法获取下载信息")
        return False

    if info["mode"] == "token" and not token:
        print("[SKIP] 需要 --token（新版书，私有CDN）")
        return False

    if dry_run:
        print(f"[DRY-RUN] mode={info['mode']}")
        return True

    pdf_url = info["url"]

    # 对公开 65/document 路径，尝试 r1→r2→r3 镜像
    if info["mode"] == "public":
        id_b = info.get("id_b", "")
        for mirror in (1, 2, 3):
            url = PDF_TMPL.format(n=mirror, id_b=id_b) if id_b else pdf_url
            if _try_download_url(session, url, out_path, None):
                return True
        print("[FAILED]")
        return False

    # 对私有 CDN 路径：必须用 private CDN + token（r*-ndr-private，accessToken 参数）
    # r*-ndr（无 private）即使带 token 也 403
    private_url = pdf_url  # detail 里已是 r*-ndr-private URL
    if "-ndr-private." not in private_url:
        private_url = pdf_url.replace("-ndr.", "-ndr-private.")
    # 尝试 r1→r2→r3 private 镜像
    for n in (1, 2, 3):
        mirror_url = re.sub(r"r\d-ndr-private", f"r{n}-ndr-private", private_url)
        if _try_download_url(session, mirror_url, out_path, token):
            return True
    print("[FAILED]")
    out_path.unlink(missing_ok=True)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="下载国家智慧教育平台教材PDF")
    parser.add_argument("--subjects", nargs="+",
                        default=["物理", "语文", "英语", "历史"],
                        help="要下载的学科（默认：物理 语文 英语 历史）")
    parser.add_argument("--out", default="./curriculum_standards",
                        help="输出目录（默认：./curriculum_standards）")
    parser.add_argument("--token", default=None,
                        help="smartedu.cn access_token（若遇 403 时使用）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只列出待下载列表，不实际下载")
    parser.add_argument("--delay", type=float, default=0.5,
                        help="每本书下载间隔秒数（默认 0.5）")
    parser.add_argument("--all-publishers", action="store_true",
                        help="下载所有出版社版本（默认只下人教版/统编版）")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()

    # 1. 获取目录
    all_books = fetch_catalog(session)

    # 2. 过滤目标学科 + 出版社
    publishers = None if args.all_publishers else DEFAULT_PUBLISHERS
    books = filter_books(all_books, args.subjects, publishers)
    pub_note = "（所有出版社）" if args.all_publishers else f"（人教版/统编版，--all-publishers 可获取全部 {len(filter_books(all_books, args.subjects))} 本）"
    print(f"\n→ 目标学科 {args.subjects}，共 {len(books)} 本教材 {pub_note}")

    # 按学科打印分布
    from collections import Counter
    dist = Counter(tag_value(b, SUBJECT_DIM) for b in books)
    for subj, cnt in sorted(dist.items()):
        print(f"   {subj}: {cnt} 本")

    if args.dry_run:
        print("\n[DRY-RUN 模式] 列出书单：")
        for b in books:
            stage   = tag_value(b, STAGE_DIM)
            subject = tag_value(b, SUBJECT_DIM)
            fname   = safe_filename(b.get("title", b["id"]), stage, subject)
            print(f"  {fname}")
        return

    # 3. 逐本下载
    print()
    success, skip, fail = 0, 0, 0
    for i, book in enumerate(books, 1):
        stage   = tag_value(book, STAGE_DIM)
        subject = tag_value(book, SUBJECT_DIM)
        filename = safe_filename(book.get("title", book["id"]), stage, subject)
        already  = (out_dir / filename).exists()

        print(f"[{i:03d}/{len(books)}]", end=" ")
        ok = download_book(session, book, out_dir, args.token, args.dry_run)

        if already:
            skip += 1
        elif ok:
            success += 1
        else:
            fail += 1

        if not already and args.delay > 0:
            time.sleep(args.delay)

    print(f"\n完成：成功 {success}，已跳过 {skip}，失败 {fail}（共 {len(books)} 本）")
    print(f"文件保存到：{out_dir.resolve()}")


if __name__ == "__main__":
    main()
