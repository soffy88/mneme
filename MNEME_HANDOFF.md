# Mneme（学鉴）前端移交文档

> **版本** 1.0 ｜ **日期** 2026-06 ｜ **状态** 后端完工，前端开发启动
> 后端 94 个测试全绿，所有接口已就绪。

---

## 1. 快速启动

```bash
# 启动全栈（PostgreSQL + Redis + MinIO + API + Celery）
cd ~/projects/mneme
docker compose up -d

# 确认健康
curl http://localhost:8001/health
# → {"status": "ok", "version": "1.3.0"}
```

| 服务 | 地址 |
|------|------|
| API | http://localhost:8001 |
| MinIO 控制台 | http://localhost:9002 |
| PostgreSQL | localhost:5433 |
| Redis | localhost:6380 |

**dev 环境验证码固定为 `123456`**（无需真实短信）。

---

## 2. 鉴权

所有接口（除 `/health` 和 `/v1/auth/*`）需要：

```
Authorization: Bearer <jwt_token>
```

获取 token 流程：
```
POST /v1/auth/send-code   {phone: "13800138000"}
POST /v1/auth/login       {phone: "13800138000", code: "123456"}
→ {token: "eyJ...", user: {...}}
```

---

## 3. 完整 API 列表

### 3.1 认证 `/v1/auth`

| Method | Path | 鉴权 | 说明 |
|--------|------|------|------|
| POST | `/v1/auth/send-code` | 无 | 发送验证码（dev 固定 123456） |
| POST | `/v1/auth/register/student` | 无 | 学生注册（<14岁需监护人信息） |
| POST | `/v1/auth/register/parent` | 无 | 家长注册（需学生邀请码） |
| POST | `/v1/auth/login` | 无 | 登录，返回 JWT token |
| GET | `/v1/auth/me` | ✅ | 当前用户信息 |
| POST | `/v1/auth/bind-child` | ✅ | 家长绑定孩子（需邀请码） |

**注册/学生 Request：**
```json
{
  "phone": "13800138000",
  "code": "123456",
  "name": "小明",
  "birth_date": "2008-01-01",
  "grade": "高三",
  "guardian_phone": "13900139000",   // <14岁必填
  "guardian_consent": true            // <14岁必填
}
```

### 3.2 试卷 `/v1/papers`

| Method | Path | 说明 |
|--------|------|------|
| POST | `/v1/papers/upload` | 上传试卷（multipart）|
| GET | `/v1/papers/{paper_id}` | 查询处理状态和结果 |
| GET | `/v1/papers` | 历史试卷列表 |

**上传 Request（multipart/form-data）：**
```
images[]: File[]      // 试卷图片（支持多张）
exam_name: string     // 考试名称（可选）
grade: string         // 年级（可选）
```

**上传 Response（立即返回，后台异步处理）：**
```json
{
  "paper_id": "uuid",
  "status": "processing"
}
```

**轮询 GET /v1/papers/{paper_id} 直到 status 变化：**
```json
{
  "paper_id": "uuid",
  "status": "done",          // processing | done | failed
  "wrong_questions": [...],
  "common_breakpoint": {
    "has_breakpoint": true,
    "description": "列方程时反复漏掉隐含条件",
    "entry_question_no": "3"
  }
}
```

### 3.3 认知状态 `/v1`

| Method | Path | 说明 |
|--------|------|------|
| POST | `/v1/interaction` | 上报一次答题事件 |
| GET | `/v1/mastery/{student_id}` | 掌握度总览（按薄弱排序）|
| GET | `/v1/mastery/curve/{student_id}/{kc_id}` | 成长曲线 🆕 |
| GET | `/v1/review-queue/{student_id}` | 今日复习队列 |
| GET | `/v1/kc` | KC 字典摘要 |
| GET | `/v1/kc/{kc_id}` | 单个 KC 详情 |

**POST /v1/interaction Request：**
```json
{
  "kc_id": "GDMATH-CONIC-01",
  "is_correct": true,
  "used_answer": false,
  "struggled": false,
  "effortless": false,
  "source": "paper",           // paper | quick | review | socratic
  "question_id": "uuid",       // 可选
  "is_interleaved": false
}
```

**POST /v1/interaction Response（新增字段）：**
```json
{
  "p_mastery": 0.7234,
  "long_term_mastery": 0.6891,
  "effective_mastery": 0.6543,
  "error_type": null,          // careless | dontknow | null
  "rating": "Good",
  "next_review_due": "2026-06-20T00:00:00Z",
  "n_attempts": 5,
  "feedback": {                 // 🆕 爽点反馈
    "text": "这个考点基本拿下了 💪",
    "type": "milestone"        // milestone | encouragement | social | null
  },
  "step_verified": null,       // 🆕 步骤校验结果（苏格拉底场景）
  "step_feedback": null        // 🆕 步骤校验提示语
}
```

**GET /v1/mastery/{student_id} Response（每条新增 peer_percentile）：**
```json
{
  "student_id": "uuid",
  "knowledge_points": [
    {
      "kc_id": "GDMATH-CONIC-04",
      "kc_name": "圆锥曲线综合（压轴）",
      "long_term_mastery": 0.12,
      "effective_mastery": 0.09,   // 含遗忘衰减，最薄弱排最前
      "n_attempts": 2,
      "peer_percentile": 0.34      // 🆕 超过34%同学，<5人时为null
    }
  ],
  "count": 29
}
```

**GET /v1/mastery/curve/{student_id}/{kc_id} Response 🆕：**
```json
{
  "kc_id": "GDMATH-CONIC-01",
  "kc_name": "椭圆",
  "points": [
    {"month": "2026-01", "mastery": 0.25},
    {"month": "2026-03", "mastery": 0.41},
    {"month": "2026-06", "mastery": 0.68}
  ]
}
```
- 按时间升序，最多 24 个月
- 无数据时 `points: []`

### 3.4 苏格拉底对话 `/v1/socratic`

| Method | Path | 说明 |
|--------|------|------|
| POST | `/v1/socratic/start` | 开启会话 |
| POST | `/v1/socratic/{session_id}/message` | 发送消息（**SSE 流式**）|
| POST | `/v1/socratic/{session_id}/escape` | 逃生出口（看答案大纲）|
| POST | `/v1/socratic/{session_id}/end` | 结束会话并回写内核 |

**POST /v1/socratic/start Request：**
```json
{"question_id": "uuid"}
```
**Response：**
```json
{
  "session_id": "uuid",
  "mode": "deep",              // deep | mixed | sprint
  "first_question": "这道题在问什么？用自己的话说说。"
}
```

**POST /v1/socratic/{id}/message — SSE 流式：**

```javascript
// 前端 EventSource 用法
const source = new EventSource(
  `/v1/socratic/${sessionId}/message`,
  { headers: { Authorization: `Bearer ${token}` } }
);

// 或用 fetch + ReadableStream（推荐，支持自定义 header）
const res = await fetch(`/v1/socratic/${sessionId}/message`, {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${token}`,
    "Content-Type": "application/json"
  },
  body: JSON.stringify({ text: userInput })
});

const reader = res.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  const chunk = decoder.decode(value);
  // chunk 格式：
  // data: {"delta": "这一步"}
  // data: {"delta": "有些问题"}
  // data: {"done": true, "emotion": null, "outcome": null}
}
```

**SSE 事件格式：**
```
data: {"delta": "这一步"}           // 流式文字片段
data: {"delta": "有些问题，再想想"}
data: {                              // 最后一条
  "done": true,
  "emotion": "anxious",             // null | anxious | crisis | angry
  "outcome": null                   // success | partial | failed | abandoned
}
```

**⚠️ 苏格拉底系统会自动拦截答案泄露**，即使 LLM 违规，API 层也会过滤。

**POST /v1/socratic/{id}/escape Response：**
```json
{
  "answer_outline": "思路提示：先找焦距，再用定义...",
  "used_escape_hatch": true
}
```

### 3.5 今日目标 `/v1/missions`

| Method | Path | 说明 |
|--------|------|------|
| GET | `/v1/missions/today/{student_id}` | 获取今日目标 |
| POST | `/v1/missions/{mission_id}/complete` | 标记完成 |

**GET /v1/missions/today/{student_id} Response：**
```json
{
  "mission": {
    "id": "uuid",
    "mission_type": "review",    // review | socratic | upload | knowledge_focus | rest
    "content": {
      "description": "回顾上周错的2道椭圆题",
      "kc_id": "GDMATH-CONIC-01",
      "kc_name": "椭圆"
    },
    "estimated_minutes": 10,
    "completed": false,
    "interleaved": false,
    "requires_active_recall": true
  },
  "streak": {
    "current_streak": 12,
    "longest_streak": 23
  }
}
```

`mission_type = "rest"` 时（23:00 后）：`estimated_minutes = 0`，前端展示"今天做得够多了，休息吧"。

**POST /v1/missions/{id}/complete Response：**
```json
{
  "streak": {
    "current_streak": 13,
    "longest_streak": 23
  },
  "next_preview": "明天：解析几何专项练习"
}
```

### 3.6 变式题（活题库）🆕

| Method | Path | 说明 |
|--------|------|------|
| POST | `/v1/practice/generate` | 按薄弱 KC 生成变式题 |

**Request：**
```json
{
  "kc_id": "GDMATH-CONIC-01",
  "count": 3,
  "difficulty": 0.5
}
```

**Response：**
```json
{
  "items": [
    {
      "question_latex": "已知椭圆 \\frac{x^2}{16}+\\frac{y^2}{9}=1，求焦距。",
      "answer": "2\\sqrt{7}",
      "solution_steps": [
        {"step_no": 1, "latex": "c=\\sqrt{16-9}", "description": "焦距公式"},
        {"step_no": 2, "latex": "c=\\sqrt{7}", "description": "计算"},
        {"step_no": 3, "latex": "2c=2\\sqrt{7}", "description": "焦距"}
      ],
      "kernel_verified": true,     // 答案由 sympy 内核验证，非 LLM 直接给出
      "plot_data": {...},           // 可为 null
      "difficulty": 0.5
    }
  ],
  "all_kernel_verified": true,
  "kc_name": "椭圆"
}
```

### 3.7 讲解页（可视化）🆕

| Method | Path | 说明 |
|--------|------|------|
| GET | `/v1/lesson/{question_id}` | 获取题目讲解 + 图示数据 |

**Response：**
```json
{
  "question_id": "uuid",
  "question_text": "已知椭圆...",
  "answer": "2\\sqrt{5}",
  "solution_steps": [...],
  "plot_data": {
    "kc_type": "conic",
    "traces": [
      {
        "type": "ellipse",
        "params": {"a": 3, "b": 2, "cx": 0, "cy": 0}
      },
      {
        "type": "point",
        "params": {"x": 2.236, "y": 0, "label": "F₁"}
      }
    ],
    "annotations": [
      {"type": "label", "x": 3, "y": 0, "text": "a=3"}
    ],
    "x_range": [-5, 5],
    "y_range": [-4, 4]
  },
  "self_check_passed": true,   // 图示数值与答案一致
  "kc_id": "GDMATH-CONIC-01"
}
```

**`plot_data` 前端渲染指南（Mafs）：**

```jsx
import { Mafs, Coordinates, Ellipse, Point, Text } from "mafs";

function LessonViz({ plotData }) {
  if (!plotData) return null;

  return (
    <Mafs
      viewBox={{ x: plotData.x_range, y: plotData.y_range }}
    >
      <Coordinates.Cartesian />
      {plotData.traces.map((trace, i) => {
        if (trace.type === "ellipse") {
          return (
            <Ellipse
              key={i}
              center={[trace.params.cx, trace.params.cy]}
              radius={[trace.params.a, trace.params.b]}
            />
          );
        }
        if (trace.type === "point") {
          return <Point key={i} x={trace.params.x} y={trace.params.y} />;
        }
        if (trace.type === "fn") {
          // 函数图象
          return (
            <Plot.OfX key={i} y={(x) => eval(trace.params.expr)} />
          );
        }
      })}
    </Mafs>
  );
}
```

### 3.8 家长端 `/v1/parent`

| Method | Path | 说明 |
|--------|------|------|
| GET | `/v1/parent/children` | 已绑定孩子列表 |
| GET | `/v1/parent/overview/{student_id}` | 成长摘要（无绝对分数）|
| GET | `/v1/parent/alerts/{student_id}` | 风险预警列表 |
| GET | `/v1/parent/export/{student_id}` | 导出全部档案（合规）|
| POST | `/v1/parent/delete-request/{student_id}` | 申请删除数据（合规）|

**GET /v1/parent/overview/{student_id} Response：**
```json
{
  "weak_kc_count": 4,
  "weak_kc_trend": -2,           // 负数=进步（减少了2个薄弱点）
  "streak": 12,
  "emotion": "stable",           // stable | anxious | low | crisis
  "top_improved_kc": "等差数列与等比数列",
  "study_minutes_today": 40
}
```

**GET /v1/parent/alerts/{student_id} Response：**
```json
{
  "alerts": [
    {
      "id": "uuid",
      "alert_type": "task_missing",   // emotion|score_drop|task_missing|time_drop|late_night
      "alert_level": "notice",         // notice | attention | important
      "content": "小明本周有3天未完成今日目标",
      "is_read": false,
      "created_at": "2026-06-10T09:00:00Z"
    }
  ]
}
```

---

## 4. 前端需要实现的页面

### 学生端

| 页面 | 核心接口 | 关键展示 |
|------|---------|---------|
| **首屏（今日目标）** | `GET /v1/missions/today` | 唯一目标 + 预计时长 + Streak 天数 |
| **掌握度地图** | `GET /v1/mastery` | KC 列表按薄弱排序 + 进度条 + peer_percentile |
| **成长曲线** | `GET /v1/mastery/curve` | 折线图，纵轴掌握度，横轴月份 |
| **试卷上传** | `POST /v1/papers/upload` + 轮询 | 上传→处理中→结果（共同断点+错题列表）|
| **讲解页** | `GET /v1/lesson` | 题目 + 分步解析 + **Mafs 可视化图示** |
| **苏格拉底对话** | SSE `/v1/socratic` | 流式对话 + 情绪感知 + 逃生出口 |
| **变式练习** | `POST /v1/practice/generate` | 一组 3 道变式题 + 答案（内核保证正确）|

### 家长端

| 页面 | 核心接口 | 关键展示 |
|------|---------|---------|
| **成长摘要** | `GET /v1/parent/overview` | 薄弱点趋势 + Streak + 情绪 + 学习时长 |
| **风险预警** | `GET /v1/parent/alerts` | 预警列表（不含题目细节）|
| **多孩子切换** | `GET /v1/parent/children` | Tab 切换，数据随孩子切换 |

---

## 5. 重要设计约定

### 反馈文案（feedback 字段）

`POST /v1/interaction` 的响应里含 `feedback`，前端在答题后展示：

| type | 触发条件 | 示例文案 |
|------|---------|---------|
| `milestone` | 掌握度突破 0.5 | "这个知识点你已经掌握一半了！" |
| `milestone` | 掌握度突破 0.8 | "这个考点基本拿下了 💪" |
| `social` | peer_percentile > 0.8 | "已超过 82% 的同学！" |
| `encouragement` | 交错练习答对 | "混合练习中答对！这才是真正的掌握。" |
| `null` | 无特殊情况 | 不展示 |

### 今日目标降级

`mission_type = "rest"` 时（23:00 后自动触发）：

```
今天做得够多了
明天继续 🌙
```

不展示"开始"按钮，只显示明日预告。

### 同源可视化保证

`plot_data` 中的数值（a、b、c 等）与 `answer` 字段的 LaTeX 数值一致，
由后端确定性内核保证，前端无需再次计算。

`self_check_passed = false` 时，`plot_data` 仍会返回，
但建议前端展示提示："图示仅供参考"。

---

## 6. 错误码

| HTTP 状态码 | 含义 |
|-------------|------|
| 401 | 未登录或 token 过期 |
| 403 | 无权限（如家长查看非绑定孩子）|
| 404 | 资源不存在 |
| 422 | 参数校验失败（如未成年人未提供监护人信息）|
| 500 | 服务器内部错误 |

所有错误统一格式：
```json
{"detail": "错误描述"}
```

---

## 7. 环境变量（`.env.example` 关键项）

```env
# 数据库（dev 非标准端口避免冲突）
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/mneme
REDIS_URL=redis://localhost:6380/0

# MinIO（对象存储）
MINIO_ENDPOINT=localhost:9002
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_HOT_BUCKET=papers-hot

# JWT
JWT_SECRET=your-secret-key-here
JWT_EXPIRE_HOURS=720

# Anthropic（LLM）
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6

# 环境
ENV=dev    # dev 模式：验证码固定 123456，日志详细
```

---

**Mneme 后端 v1.0 · 94 测试全绿 · 前端组接手**
