"""
enrich_ku_content.py — 批量为初高中 KU 生成"讲透"内容，写入 rich_content JSONB。

用法:
  python3 scripts/enrich_ku_content.py --subject math --limit 50   # 抽查50个
  python3 scripts/enrich_ku_content.py --subject math               # 数学全量
  python3 scripts/enrich_ku_content.py --subject physics            # 物理全量

特性:
  - 幂等: rich_content IS NOT NULL 的跳过
  - 断点续传: 每次写库后记录进度，重跑自动续
  - 并发: 8线程
  - 学段过滤: 只处理 G7-G12
  - 每50条打印一次进度
"""

import argparse
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2
import psycopg2.extras
from openai import OpenAI

# ── 连接配置 ──────────────────────────────────────────────────
DB_DSN = "host=localhost port=5433 dbname=mneme user=postgres password=postgres"
# LLM 端点可换：默认 DeepSeek；本地 Ollama 用
#   LLM_BASE_URL=http://localhost:11434/v1 LLM_MODEL=qwen3.5:9b LLM_API_KEY=ollama
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")
LLM_API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "") or "local"
WORKERS = int(os.environ.get("LLM_WORKERS", "8"))
GRADES_TARGET = ("G7", "G8", "G9", "G10", "G11", "G12")

client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)

# ── 系统提示 ──────────────────────────────────────────────────
SYSTEM = """你是一名经验丰富的中学数理学科教师，为学科知识单元生成结构化"讲透"内容。
要求：
1. 返回合法 JSON（无任何 Markdown 包裹），字段值为纯文本或字符串数组
2. 数学公式用 LaTeX：行内用 $...$，独立公式用 $$...$$
3. 语言简洁准确，每个字段控制在 60-150 字（数组每条 30-80 字）
4. 常见错误必须具体（说明错在哪里，不要泛泛而谈）
5. 仅返回 JSON，不加任何解释文字"""

# ── 各 ku_type 的 prompt 工厂 ──────────────────────────────────

def _base_info(ku: dict) -> str:
    return (f"知识点：{ku['name']}（{ku['grade']} {ku['subject']}）\n"
            f"当前描述：{(ku['description'] or '无').strip()[:200]}\n")


def prompt_math_concept(ku: dict) -> str:
    return _base_info(ku) + """
请返回如下 JSON（key 不可省略，value 不合适时用空字符串）：
{
  "intuition": "为什么需要这个概念？生活类比或本质是什么（1-2句）",
  "definition": "精确数学定义，标注关键限定条件",
  "key_points": ["⚠️ 最易误解的点1", "⚠️ 最易误解的点2", "⚠️ 第3点（可选）"],
  "examples": ["具体例子1，带简短说明", "具体例子2（可选）"],
  "counter_examples": "容易混淆的概念或反例，说清楚区别",
  "common_mistakes": ["学生常犯的具体错误1（说清楚错在哪）", "具体错误2", "具体错误3（可选）"],
  "connections": "与前后知识的联系，1-2句",
  "application": "典型考查方式，1-2种，各一句"
}"""


def prompt_math_formula(ku: dict) -> str:
    return _base_info(ku) + """
请返回如下 JSON：
{
  "formula": "完整公式及各量含义（含单位/取值范围）",
  "derivation": "推导思路（1-2句口诀式，帮助记忆）",
  "conditions": "适用条件及限制",
  "variants": ["常见变形1（说明用途）", "变形2（可选）", "变形3（可选）"],
  "typical_uses": ["典型解题场景1", "场景2", "场景3（可选）"],
  "common_mistakes": ["⚠️ 具体易错1（说清楚错在哪，正确做法）", "易错2", "易错3（可选）"]
}"""


def prompt_math_method(ku: dict) -> str:
    return _base_info(ku) + """
请返回如下 JSON：
{
  "when_to_use": "适用场景的一句话判断标准",
  "steps": ["第1步：...", "第2步：...", "第3步：...", "第4步（可选）"],
  "key_points": ["⚠️ 操作中易卡壳或出错的点1", "点2"],
  "example": "一个完整例子（题目+解题过程，150字以内）",
  "common_mistakes": ["⚠️ 具体错误1（说清楚错在哪）", "错误2（可选）"]
}"""


def prompt_physical_concept(ku: dict) -> str:
    return _base_info(ku) + """
请返回如下 JSON：
{
  "intuition": "为什么需要引入这个量？用生活场景引入（1-2句）",
  "definition": "物理定义 + 数学表达式（含各量含义/矢量或标量/单位）",
  "key_points": ["⚠️ 最反直觉或最易误解的点1", "⚠️ 点2", "⚠️ 点3（可选）"],
  "examples": ["具体情景1（含数值计算）", "情景2（可选）"],
  "counter_examples": "容易混淆的概念，一句话说清楚区别",
  "common_mistakes": ["⚠️ 具体错误1", "错误2", "错误3（可选）"],
  "connections": "与1-2个关联物理量的关系（一句话，不展开）"
}"""


def prompt_physical_law(ku: dict) -> str:
    return _base_info(ku) + """
请返回如下 JSON：
{
  "physical_picture": "这条规律描述的物理场景，用直观形象说清楚（1-2句）",
  "statement": "完整规律表述 + 数学表达式（含各量含义和方向性）",
  "conditions": "成立条件和限制，⚠️ 不满足时会出什么问题",
  "typical_uses": ["典型解题场景1（一句话思路）", "场景2", "场景3（可选）"],
  "common_mistakes": ["⚠️ 具体错误1（说清楚错在哪，正确做法）", "错误2", "错误3（可选）"],
  "corollaries": "重要推论或派生公式（1-2条）",
  "connections": "与相关规律/概念的关系（1句话）"
}"""


def prompt_experiment(ku: dict) -> str:
    return _base_info(ku) + """
请返回如下 JSON（在已有实验基本信息基础上补充以下内容，不重复已有描述）：
{
  "design_rationale": "关键器材和步骤的设计理由（物理逻辑是什么，100字以内）",
  "common_mistakes": ["⚠️ 易错操作1（错误操作→后果→正确做法）", "易错操作2", "易错操作3", "易错操作4（可选）"],
  "data_processing": "数据处理要点（误差控制/图像异常判断/有效数字，80字以内）",
  "exam_hotspots": ["考查热点1", "热点2", "热点3", "热点4（可选）"]
}"""


def prompt_physical_model(ku: dict) -> str:
    return _base_info(ku) + """
请返回如下 JSON：
{
  "motivation": "引入这个模型的动机（简化了什么，1-2句）",
  "assumptions": ["简化假设1", "假设2", "假设3（可选）"],
  "conditions": "适用条件 + ⚠️ 不可用时的判断标准（1-2句）",
  "typical_scenarios": ["典型使用场景1", "场景2", "场景3（可选）"],
  "limitations": "与实际的差异（什么时候模型会出问题，1句话）"
}"""


TYPE_TO_PROMPT = {
    "concept":          prompt_math_concept,
    "formula":          prompt_math_formula,
    "method":           prompt_math_method,
    "physical_concept": prompt_physical_concept,
    "physical_law":     prompt_physical_law,
    "experiment":       prompt_experiment,
    "physical_model":   prompt_physical_model,
}

# ── 核心生成函数 ───────────────────────────────────────────────

def generate_rich_content(ku: dict) -> dict | None:
    """调用 DeepSeek，返回 parsed dict 或 None（失败）。"""
    prompt_fn = TYPE_TO_PROMPT.get(ku["ku_type"])
    if prompt_fn is None:
        return {"_skipped": f"no template for ku_type={ku['ku_type']}"}

    prompt = prompt_fn(ku)
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.2,
                max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "900")),
            )
            raw = (resp.choices[0].message.content or "").strip()
            # 去掉可能的 ```json ... ``` 包裹
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            return _parse_json_lenient(raw)
        except json.JSONDecodeError as e:
            if attempt == 2:
                return {"_raw": raw, "_error": f"JSON parse failed: {e}"}
            time.sleep(1)
        except Exception as e:
            if attempt == 2:
                return {"_error": str(e)}
            time.sleep(2 ** attempt)
    return None


# ── 数据库工具 ────────────────────────────────────────────────

def fetch_pending(conn, subject: str, limit: int | None, retry_failed: bool = False,
                  all_grades: bool = False, grades: list[str] | None = None) -> list[dict]:
    """查出待处理的 KU。
    retry_failed=False → rich_content IS NULL（未生成）；True → 含 _error/_raw（破损）。
    年级过滤：grades 指定 → 用之；否则 all_grades=True → 不限；默认 → G7-G12。
    """
    if grades:
        glist: list[str] | None = grades
    elif all_grades:
        glist = None
    else:
        glist = list(GRADES_TARGET)
    grade_clause = ""
    if glist is not None:
        grade_clause = "AND t.grade IN (%s)" % ",".join("'%s'" % g for g in glist)
    where_content = (
        "(jsonb_exists(ku.rich_content, '_error') OR jsonb_exists(ku.rich_content, '_raw'))"
        if retry_failed else "ku.rich_content IS NULL"
    )
    sql = f"""
        SELECT ku.id, ku.name, ku.ku_type, ku.description,
               t.grade, t.subject
        FROM knowledge_units ku
        JOIN textbooks t ON ku.textbook_id = t.id
        WHERE {where_content}
          AND t.subject = %s
          {grade_clause}
        ORDER BY t.grade, ku.id
        {f'LIMIT {limit}' if limit else ''}
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, (subject,))
        return [dict(r) for r in cur.fetchall()]


def save_rich_content(conn, ku_id: str, content: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE knowledge_units SET rich_content = %s WHERE id = %s",
            (json.dumps(content, ensure_ascii=False), ku_id),
        )
    conn.commit()


def count_total(conn, subject: str) -> tuple[int, int]:
    """返回 (pending数, 已完成数)。"""
    grade_placeholders = ",".join([f"'{g}'" for g in GRADES_TARGET])
    sql = f"""
        SELECT
          count(*) FILTER (WHERE ku.rich_content IS NULL) AS pending,
          count(*) FILTER (WHERE ku.rich_content IS NOT NULL) AS done
        FROM knowledge_units ku
        JOIN textbooks t ON ku.textbook_id = t.id
        WHERE t.subject = %s AND t.grade IN ({grade_placeholders})
    """
    with conn.cursor() as cur:
        cur.execute(sql, (subject,))
        row = cur.fetchone()
        return row[0], row[1]


# ── 并发处理 ──────────────────────────────────────────────────

import re as _re
# 匹配"非法 JSON 转义"的反斜杠（后面不是合法转义字符）——本地模型常把 LaTeX 写成单反斜杠
_BAD_ESC = _re.compile(r'\\(?!["\\/bfnrtu])')

def _parse_json_lenient(raw: str) -> dict:
    """容错解析：直接 → 修反斜杠转义 → 截取{…} → 截取后修转义。
    解决本地模型把 $\\vec{a}$ 写成单反斜杠导致 JSON 非法的问题。"""
    cands = [raw]
    i, j = raw.find("{"), raw.rfind("}")
    if i != -1 and j > i:
        cands.append(raw[i:j + 1])
    for cand in cands:
        for variant in (cand, _BAD_ESC.sub(r'\\\\', cand)):
            try:
                return json.loads(variant)
            except json.JSONDecodeError:
                continue
    raise json.JSONDecodeError("lenient parse failed", raw, 0)


def process_one(ku: dict) -> tuple[str, dict | None, float]:
    t0 = time.time()
    result = generate_rich_content(ku)
    return ku["id"], result, time.time() - t0


def run(subject: str, limit: int | None, retry_failed: bool = False,
        all_grades: bool = False, grades: list[str] | None = None):
    conn = psycopg2.connect(DB_DSN)
    kus = fetch_pending(conn, subject, limit, retry_failed=retry_failed,
                        all_grades=all_grades, grades=grades)
    conn.close()  # 每个线程用独立连接
    effective = len(kus)

    grade_label = ",".join(grades) if grades else ("全部" if all_grades else "G7-G12")
    print(f"\n{'='*60}")
    print(f"科目: {subject}  |  模式: {'重试失败(_error/_raw)' if retry_failed else '正常(IS NULL)'}"
          f"  |  年级: {grade_label}")
    print(f"本次处理: {effective}  |  并发: {WORKERS}线程")
    print("="*60)

    if effective == 0:
        print("✅ 无待处理KU，退出。")
        return

    ok = err = skip = 0
    start = time.time()

    def worker(ku: dict):
        thread_conn = psycopg2.connect(DB_DSN)
        try:
            ku_id, result, elapsed = process_one(ku)
            # 失败（None / 含 _error / 含 _raw）不落库——避免把破损内容当"完成"持久化
            if result is None or "_error" in result or "_raw" in result:
                msg = (result or {}).get("_error", "no result") if result else "no result"
                return ku_id, f"error:{msg[:60]}", elapsed
            save_rich_content(thread_conn, ku_id, result)
            status = "skip" if "_skipped" in result else "ok"
            return ku_id, status, elapsed
        except Exception as e:
            return ku["id"], f"error:{e}", 0.0
        finally:
            thread_conn.close()

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(worker, ku): ku for ku in kus}
        for i, fut in enumerate(as_completed(futures), 1):
            ku = futures[fut]
            try:
                ku_id, status, elapsed = fut.result()
            except Exception as e:
                status = f"error:{e}"
                elapsed = 0.0
                ku_id = ku["id"]

            if status == "ok":
                ok += 1
            elif status == "skip":
                skip += 1
            else:
                err += 1
                print(f"\n  ❌ {ku['name']}: {status}")

            if i % 50 == 0 or i == effective:
                elapsed_total = time.time() - start
                rate = i / elapsed_total if elapsed_total > 0 else 0
                eta = (effective - i) / rate if rate > 0 else 0
                print(f"[{i:4d}/{effective}] ✅{ok} ❌{err} ⏭{skip} "
                      f"| {rate:.1f}个/s | ETA {eta/60:.1f}min "
                      f"| 最新: {ku['name'][:20]}")

    total_time = time.time() - start
    print(f"\n{'='*60}")
    print(f"完成！✅{ok}  ❌{err}  ⏭{skip}")
    print(f"耗时: {total_time/60:.1f}分钟  |  均速: {ok/(total_time or 1):.1f}个/s")
    print("="*60)


# ── 入口 ──────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", choices=["math", "physics"], required=True)
    parser.add_argument("--limit",   type=int, default=None, help="只处理N条（抽查用）")
    parser.add_argument("--retry-failed", action="store_true",
                        help="重试 rich_content 含 _error/_raw 的失败项（质检发现的破损）")
    parser.add_argument("--all-grades", action="store_true",
                        help="不限年级（含 G1-G6/高一 等，默认仅 G7-G12）")
    parser.add_argument("--grades", type=str, default=None,
                        help="只处理指定年级（逗号分隔，如 '高一' 或 'G1,G2'）")
    args = parser.parse_args()
    _grades = [g.strip() for g in args.grades.split(",")] if args.grades else None
    run(args.subject, args.limit, retry_failed=args.retry_failed,
        all_grades=args.all_grades, grades=_grades)
