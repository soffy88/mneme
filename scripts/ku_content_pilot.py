"""
试点脚本：用 DeepSeek-V3 为10个代表性KU生成"讲透"内容。
输出: scripts/ku_content_pilot_10.md
只跑一次，不入库，供人工评审。
"""

import os
import time
from openai import OpenAI

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com")

# ─────────────────────────────────────────────────────────────
# 10 个试点 KU（从DB核实，覆盖7种类型+3个学段）
# ─────────────────────────────────────────────────────────────
KUS = [
    {
        "id": "RENJIAO-G11-MATH-A-SBX1-ku-椭圆的几何性质-离心率",
        "name": "椭圆的几何性质：离心率",
        "ku_type": "math_concept",
        "grade": "G11 高中",
        "current_desc": "离心率e=c/a (0<e<1)，e越大椭圆越扁平，e越小越接近圆。",
        "difficulty": 0.5,
    },
    {
        "id": "renjiao-math-g10-a-ku-正弦函数单调性",
        "name": "正弦函数单调性",
        "ku_type": "math_concept",
        "grade": "G10 高中",
        "current_desc": "正弦函数在[-π/2+2kπ, π/2+2kπ]上递增，在[π/2+2kπ, 3π/2+2kπ]上递减。",
        "difficulty": 0.4,
    },
    {
        "id": "RENJIAO-G11-MATH-A-SBX2-ku-等差数列的通项公式",
        "name": "等差数列的通项公式",
        "ku_type": "math_formula",
        "grade": "G11 高中",
        "current_desc": "首项为a₁，公差为d的等差数列{aₙ}的通项公式为aₙ=a₁+(n-1)d。",
        "difficulty": 0.4,
    },
    {
        "id": "RENJIAO-G8-MATH-X-ku-待定系数法求一次函数解析式",
        "name": "待定系数法求一次函数解析式",
        "ku_type": "math_method",
        "grade": "G8 初中",
        "current_desc": "设一次函数解析式为y=kx+b，根据两个条件列出关于k,b的方程组，解出k,b，得到解析式。",
        "difficulty": 0.5,
    },
    {
        "id": "RENJIAO-G10-PHYSICS-BX1-ku-加速度",
        "name": "加速度",
        "ku_type": "physical_concept",
        "grade": "G10 高中",
        "current_desc": "描述物体速度变化快慢的物理量，等于速度的变化量与发生这一变化所用时间之比。",
        "difficulty": 0.4,
    },
    {
        "id": "RENJIAO-G11-PHYSICS-BX3-ku-电场强度",
        "name": "电场强度",
        "ku_type": "physical_concept",
        "grade": "G11 高中",
        "current_desc": "描述电场强弱和方向的物理量，定义为试探电荷所受静电力与电荷量之比，E=F/q，单位N/C，矢量。【适用条件】适用于任何电场，但定义式中的试探电荷需足够小。",
        "difficulty": 0.5,
    },
    {
        "id": "RENJIAO-G10-PHYSICS-BX1-ku-牛顿第二定律",
        "name": "牛顿第二定律",
        "ku_type": "physical_law",
        "grade": "G10 高中",
        "current_desc": "物体加速度的大小与所受合外力成正比，与质量成反比，方向与合外力方向相同，即F=ma。【适用条件】适用于惯性参考系，宏观低速运动。",
        "difficulty": 0.6,
    },
    {
        "id": "RENJIAO-G10-PHYSICS-BX1-ku-探究弹簧弹力与形变量的关系实验",
        "name": "探究弹簧弹力与形变量的关系实验",
        "ku_type": "experiment",
        "grade": "G10 高中",
        "current_desc": "通过悬挂不同质量钩码，测量弹簧弹力和伸长量，作出F-x图像，探究弹力与形变量的关系。原理：胡克定律F=kx；器材：铁架台、弹簧、刻度尺、钩码；步骤：记录弹簧原长→逐次加挂钩码→记录弹簧长度→计算伸长量和弹力→描点作图；数据处理：以F为纵轴、x为横轴作图，分析线性关系。",
        "difficulty": 0.5,
    },
    {
        "id": "RENJIAO-G10-PHYSICS-BX1-ku-质点模型",
        "name": "质点模型",
        "ku_type": "physical_model",
        "grade": "G10 高中",
        "current_desc": "忽略物体的大小和形状，将其简化为一个具有质量的点，用于描述物体整体运动。【适用条件】当物体的大小和形状对所研究问题的影响可忽略时，或物体上各点运动情况完全相同时适用。",
        "difficulty": 0.4,
    },
    {
        "id": "RENJIAO-G1-MATH-S-ku-加法-5以内",
        "name": "加法（5以内）",
        "ku_type": "math_concept",
        "grade": "G1 小学",
        "current_desc": "理解加法的含义，能计算5以内数的加法，认识加号。",
        "difficulty": 0.4,
    },
]

# ─────────────────────────────────────────────────────────────
# 各类型 prompt 模板
# ─────────────────────────────────────────────────────────────

SYSTEM = """你是一名经验丰富的中学/小学数理学科教师，擅长把抽象知识讲得让学生"有回响"——不只是记住定义，而是真正理解和会用。
请用简洁、准确、有温度的语言，为以下知识单元（KU）生成"讲透内容"。
输出纯Markdown，不要加```代码块包裹，不要重复我给你的KU基础信息。
数学公式用LaTeX行内格式 $...$，避免HTML标签。"""


def make_prompt_math_concept(ku: dict) -> str:
    grade_hint = "（请注意：这是小学生，语言要极简、直观，多用实物类比，避免抽象术语）" if "小学" in ku["grade"] else ""
    return f"""知识单元：{ku["name"]}（{ku["grade"]}数学）{grade_hint}
现有简短描述：{ku["current_desc"]}

请生成以下8个维度的内容，每个维度50-120字，总体控制在600字以内：

## 直观理解
（为什么需要这个概念？生活中有什么类比？本质是什么？）

## 精确定义
（数学上的完整定义，标注关键限定条件）

## 关键点
（2-3个学生最容易忽略或误解的细节，加"⚠️"标注）

## 正例
（1-2个具体例子，展示怎么用这个概念）

## 反例 / 易混概念
（容易混淆的情况或相近概念的区别）

## 常见错误
（学生实际会犯的错误，说具体，不要泛泛而谈）

## 知识联系
（这个概念跟哪些已学/将学的知识有联系？）

## 典型题型
（1-2种典型的考查方式，各一句话说清楚考什么）"""


def make_prompt_math_formula(ku: dict) -> str:
    return f"""知识单元：{ku["name"]}（{ku["grade"]}数学）
现有描述：{ku["current_desc"]}

请生成以下6个维度，总体控制在500字以内：

## 公式
（写出完整公式，标注各量含义和单位）

## 推导思路
（用1-3句话说清楚这个公式是怎么来的，帮助记忆）

## 适用条件
（什么情况下能用？有什么限制？）

## 常见变形
（考试中常用的等价变形形式，各加一句说明用途）

## 典型用法
（2-3种典型解题场景，各一句话）

## 易错点
（⚠️ 2-3个具体易错点，要说清楚错在哪、正确做法是什么）"""


def make_prompt_math_method(ku: dict) -> str:
    return f"""知识单元：{ku["name"]}（{ku["grade"]}数学）
现有描述：{ku["current_desc"]}

请生成以下5个维度，总体控制在500字以内：

## 适用场景
（什么题型/条件下用这个方法？一句话判断标准）

## 步骤
（清晰的操作步骤，编号列出，步骤名称加粗）

## 关键点
（⚠️ 操作时容易卡壳或出错的地方，2-3条）

## 完整例子
（1个完整例子，展示全部步骤）

## 易错
（⚠️ 学生最常犯的具体错误）"""


def make_prompt_physical_concept(ku: dict) -> str:
    return f"""知识单元：{ku["name"]}（{ku["grade"]}物理）
现有描述：{ku["current_desc"]}

请生成以下7个维度，总体控制在600字以内：

## 直觉来源
（为什么物理学需要引入这个量？它解决了什么问题？用生活场景引入）

## 定义
（物理定义+数学表达式，标注各量含义、矢量/标量、单位）

## 关键点
（⚠️ 2-3个最易误解的点，例如"大不代表变化快"这类反直觉）

## 正例
（1-2个具体情景，展示如何应用这个概念）

## 易混概念
（与哪些概念容易混淆？一句话说出区别）

## 常见错误
（学生做题时的具体错误，不要泛泛而谈）

## 与其他物理量的联系
（这个量如何与其他物理量关联？有什么规律用到它？）"""


def make_prompt_physical_law(ku: dict) -> str:
    return f"""知识单元：{ku["name"]}（{ku["grade"]}物理）
现有描述：{ku["current_desc"]}

请生成以下7个维度，总体控制在600字以内：

## 物理图景
（这条规律描述的是什么物理场景？用一个直观形象说清楚）

## 规律表述
（完整文字表述+数学表达式，标注各量含义和方向性）

## 成立条件
（这条规律在什么条件下成立？有什么限制？⚠️ 不符合条件时会出什么问题？）

## 典型应用
（2-3种典型解题场景，各一句话说明思路）

## 常见错误
（⚠️ 2-3个学生最常犯的具体错误，写清楚错在哪）

## 推论
（这条规律的重要推论，或者由此派生的公式）

## 与其他规律的联系
（与牛顿三定律/能量等的关系，体现物理体系的整体性）"""


def make_prompt_experiment(ku: dict) -> str:
    return f"""知识单元：{ku["name"]}（{ku["grade"]}物理实验）
现有描述：{ku["current_desc"]}

在上述已有的实验基本信息基础上，补充以下4个维度（不要重复已有内容），总体控制在500字以内：

## 设计思路
（为什么这么设计？每个关键器材/步骤背后的物理逻辑是什么？）

## 易错操作
（⚠️ 3-4个实际操作中学生容易犯的具体错误，每条说清楚：错误操作→导致的后果→正确做法）

## 数据处理要点
（处理数据时的注意事项：如何减小误差？图像异常如何判断？有效数字如何取？）

## 考查热点
（这个实验在考试中最常考哪几个点？各一句话）"""


def make_prompt_physical_model(ku: dict) -> str:
    return f"""知识单元：{ku["name"]}（{ku["grade"]}物理模型）
现有描述：{ku["current_desc"]}

请生成以下5个维度，总体控制在500字以内：

## 建模动机
（为什么要引入这个模型？它简化了什么？）

## 简化假设
（这个模型做了哪些简化？明确列出忽略了什么）

## 适用条件
（什么情况下可以用这个模型？⚠️ 什么情况下不能用？判断标准是什么？）

## 典型情景
（2-3个典型的使用场景，各一句话）

## 与实际的差异
（模型与真实物体的差异，以及这种差异什么时候会造成问题）"""


TYPE_TO_PROMPT = {
    "math_concept":   make_prompt_math_concept,
    "math_formula":   make_prompt_math_formula,
    "math_method":    make_prompt_math_method,
    "physical_concept": make_prompt_physical_concept,
    "physical_law":   make_prompt_physical_law,
    "experiment":     make_prompt_experiment,
    "physical_model": make_prompt_physical_model,
}

TYPE_LABEL = {
    "math_concept":     "数学·概念",
    "math_formula":     "数学·公式",
    "math_method":      "数学·方法",
    "physical_concept": "物理·概念",
    "physical_law":     "物理·规律",
    "experiment":       "物理·实验",
    "physical_model":   "物理·模型",
}


def call_deepseek(prompt: str) -> str:
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.3,
        max_tokens=1200,
    )
    return resp.choices[0].message.content.strip()


def main():
    out_path = os.path.join(os.path.dirname(__file__), "ku_content_pilot_10.md")
    lines = [
        "# KU 讲透内容试点（10个）",
        "",
        "**目的**：验证各 ku_type 的规格是否合适，评估 DeepSeek-V3 生成质量。",
        "**评审维度**：内容有没有回响 / 规格是否匹配 / 篇幅是否合适 / 准不准确",
        "",
        "---",
        "",
    ]

    for i, ku in enumerate(KUS, 1):
        ku_type   = ku["ku_type"]
        type_label = TYPE_LABEL.get(ku_type, ku_type)
        print(f"[{i}/10] 生成 {ku['name']} ({ku['grade']}, {type_label})...")

        prompt_fn = TYPE_TO_PROMPT.get(ku_type)
        if not prompt_fn:
            print(f"  ⚠️ 未找到 {ku_type} 的 prompt 模板，跳过")
            continue

        prompt = prompt_fn(ku)
        try:
            content = call_deepseek(prompt)
            status = "✅"
        except Exception as e:
            content = f"⚠️ 生成失败：{e}"
            status = "❌"
        print(f"  {status} 完成（{len(content)} 字符）")

        lines += [
            f"## {i}. {ku['name']}",
            "",
            "| 字段 | 值 |",
            "|------|----|",
            f"| ku_type | `{ku_type}` ({type_label}) |",
            f"| 学段/年级 | {ku['grade']} |",
            f"| 难度 | {ku['difficulty']} |",
            f"| 原有描述 | {ku['current_desc'][:80]}{'...' if len(ku['current_desc'])>80 else ''} |",
            "",
            "### 生成内容",
            "",
            content,
            "",
            "---",
            "",
        ]

        if i < len(KUS):
            time.sleep(1)   # 轻微限速

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"\n✅ 输出: {out_path}")


if __name__ == "__main__":
    main()
