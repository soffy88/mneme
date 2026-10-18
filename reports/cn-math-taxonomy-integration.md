# `cn-math-taxonomy` 集成进 `mneme` 报告

## 一、 改了什么 (What was changed)
1. **集成目标**：将 `cn-math-taxonomy`（xiaoyang111222/cn-math-taxonomy，基于 2022 年版数学新课标与 2024 人教版教材构建的初中数学知识图谱，包含 333 个知识点、616 条先修依赖边及 1407 道结构化习题）引入 mneme 后端，作为初中数学知识体系基线。
2. **新增导入脚本**：
   - 创建了 `services/cn_math_importer.py`。
   - 将 `topics.json` 的知识点映射至 mneme 的 `KnowledgeUnit` 结构：
     - 保留 `cnm_` 编号作为 `rich_content.cnm_id`（外部 ID）。
     - 提取 `grade`、`semester`、`chapter`、`domain`、`type`、`mastery_criteria`、`standards`。
   - 将 `dependencies.json` 的有向先修关系映射为 `prerequisites`（hard）与 `soft_prerequisites`（soft）。
   - 将 `questions.json` 题库打包进 `rich_content.questions`。
   - 统一标记溯源字段：`source=cn-math-taxonomy`、`license=CC BY-NC 4.0`、`needs_teacher_review=True`。
3. **新增测试用例**：
   - 编写了 `tests/test_cn_math_taxonomy.py` 与 `tests/test_cn_math_importer_unit.py`，完整覆盖导入逻辑、新建与更新分支，并且所有现有测试均保持通过。

## 二、 怎么运行导入 (How to run import)
可在 Python 环境中通过异步调用 `import_cn_math_taxonomy`（传入 SQLAlchemy `AsyncSession`）将数据写入 `knowledge_units` 表：
```python
from services.cn_math_importer import import_cn_math_taxonomy
# 在异步上下文中：
await import_cn_math_taxonomy(db_session)
```

## 三、 测试结果 (Test Results)
- 新增单元测试顺利通过。
- 现有核心数学测试（如 `tests/test_math_grade.py`）运行正常，未对现有高中数学知识体系或内核造成任何破坏。

## 四、 遗留问题与后续建议 (Remaining Issues & Recommendations)
1. **CC BY-NC 4.0 合规边界**：该图谱及题库遵循知识共享署名-非商业性使用 4.0 国际许可协议。未来如需发布商业版（Commercial Build），需自动过滤或替换带有 `cn-math-taxonomy` 来源的数据。
2. **教研抽样校准**：图谱内容为 AI 生成初稿，建议组织一线初中数学教师对九年级下册和关键先修边进行二次人工校审。
