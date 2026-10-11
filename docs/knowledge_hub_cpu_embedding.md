# Knowledge Hub 语义检索：CPU embedding 侧车（2026-10-11）

## 背景
- RTX 3080（ubuntu26）Xid 154 掉卡，Ollama qwen3-embedding（4096 维）不可用；生产 LLM 走 Veya 网关，网关无 `/embeddings`。
- 检索（`services/knowledge_hub_search.py`）因此一直落在词面兜底。

## 方案
| 部件 | 说明 |
|---|---|
| `docker/embedder/` | CPU-only 侧车：python:3.12-slim + CPU 版 torch 2.5.1 + transformers 4.46.3，FastAPI `POST /v1/embeddings`（OpenAI 形状，扩展字段 `input_type=query|passage`），`GET /health`。CLS 池化 + L2 归一化。推理串行（一把锁）。 |
| compose 服务 `embedder` | 镜像 `mneme-embedder:cpu`，`restart: unless-stopped`，`cpus: 4`、`EMBED_THREADS=4`、`mem_limit: 2g`，只在 compose default 网络（`http://embedder:8080`），不映射宿主端口。权重只读挂载 `/data/soffy/appdata/models/bge-small-zh-v1.5`（ModelScope `BAAI/bge-small-zh-v1.5`，92 MB）。`CUDA_VISIBLE_DEVICES=""`。 |
| `services/text_embedder.py` | 后端选择：`MNEME_EMBED_BACKEND=cpu|legacy|off`（代码默认 legacy；compose 默认 cpu），`MNEME_EMBED_URL`，`MNEME_EMBED_MODEL`（=新表 `model` 列）。 |
| 迁移 `kce1a2b3c4d5` | 新表 `textbook_chunk_embeddings(chunk_id, model)`，`real[]` 向量 + dim。旧 `textbook_chunks.embedding`（4096 维）原样保留，CPU 后端不读也不写它。 |
| `knowledge_hub_search` | query embedding 走所选后端（原 10s 超时 + 60s 冷却熔断 + 词面兜底不变）；向量矩阵按 model 缓存；阈值按“打分模型 × 用途”取（`min_score_for`）。 |
| 回填 | `scripts/knowledge_hub_backfill.py embed|match --backend cpu`（insert-only；match 只给没有任何挂接的 KU 插 top-3，`verified=false`，`method=embedding_cosine_bge-small-zh-v1.5`）。 |

重启：`docker compose up -d --no-deps embedder`（模型 ~5s 加载，healthcheck `/health`）。回退：`.env` 设 `MNEME_EMBED_BACKEND=legacy`（旧 Ollama 路径）或 `off`（只用词面），再 `docker compose up -d --no-deps api worker`。

## 选型（实测，ubuntu26 常态负载 load avg ~30/20 线程）
标注集：26 条 query（数学/物理/英语/语文/历史/生物/化学，含 2 条英→中跨语言），正例 = 目标学科内含关键词的 chunk（各抽 6 条），负例 = 400 条随机 chunk。

| 模型 | MRR | R@3 | ms/chunk | ms/query |
|---|---|---|---|---|
| bge-small-zh-v1.5（512 维，query 加检索指令） | **0.842** | 0.88 | **132** | **57** |
| bge-m3（1024 维） | 0.825 | 0.88 | 1669 | 576 |
| multilingual-e5-small（384 维） | 0.78 | 0.84 | 217 | 18 |

bge-m3 质量相当，但本机负载下要 ~7 小时才能嵌完 16k chunk，且 query 延迟超出 300 ms 目标；e5-small 分数压缩在 0.79–0.93，无法设阈值。bge-small 唯一明显短板：英文 query 找中文正文（"Pythagorean theorem" → 勾股定理）不行。

## 阈值标定（bge-small-zh-v1.5）
旧 qwen3：Book R1 0.60 / tutor 0.58。新模型（`MIN_SCORE_PROFILES["bge-small-zh-v1.5"]`）：

**chat = 0.55**（tutor SearchKnowledgeBase 回落素材下限）。真实 `search_knowledge_base` 路径，30 条标注 query + 12 条语料外 query（红烧肉/股票/天气/电影…）：

| 阈值 | 标注 query top-1 相关且保留 | 语料外 query top-1 被放过 |
|---|---|---|
| 0.50 | 29/30 | 10/12 |
| 0.52 | 28/30 | 6/12 |
| **0.55** | **28/30** | **4/12** |
| 0.58 | 26/30 | 4/12 |
| 0.60 | 26/30 | 3/12 |
| 0.62 | 23/30 | 1/12 |

0.55 之上放过的语料外 query：股票投资技巧 0.62（高中数学概率）、量子计算机原理 0.62（物理选必三，量子章节，算半相关）、how to cook pasta 0.61（英语选必三）、怎么学开车 0.58。off-topic 分离度是这个小模型的弱项——这层过滤只是呈现层素材下限，不是正确性保证。

**book = 0.65**（Book Engine R1，对 KU 挂接逐行按 method 取档；数学旧 qwen3 行仍用 0.60）。新挂接的 rank-1 人工抽检 60 条（语文 45 / 物理 12 / 历史 1 …）：≥0.70 约 85% 正确，0.65–0.70 约 70%，0.60–0.65 约 58%，<0.60 约 50%；≥0.65 合计约 81%（A3 旧挂接 ~85%）。新挂接 rank-1 分数 ≥0.65 的约占 58%。语文 KU 里大量是字词注音/释义类（“燔·fán”“局促不安”），最容易挂错——它们通常落在同一课的注释页附近，但不一定是那一页。

覆盖阈值：`KNOWLEDGE_HUB_MIN_SCORE_BGE_SMALL_ZH_V1_5_CHAT` / `..._BOOK`（以及 `KNOWLEDGE_HUB_MIN_SCORE_LEGACY_*`）。

## 已知缺口
- 新入库 chunk 不会自动得到 CPU 向量（入库仍走 `textbook_qa_service` → `oprim.embed_chunks` 旧路径）：入库后需再跑一次 `knowledge_hub_backfill.py embed --backend cpu`（insert-only，只补缺的）。
- 跨语言（英文 query → 中文正文）召回差。
- 新挂接全部 `verified=false`，走既有人工校订（export/apply_ku_chunk_review.py）。
