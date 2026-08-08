# 交互式康奈尔笔记 · 课题内容包

权威契约见 `MNEME_MASTER_DESIGN.md` 附录「交互式康奈尔笔记（Phase B）」。

## 目录约定

```
cornell_topics/
├── README.md
└── {topicId}/
    └── content.json      # 课题大纲（线索 / 模块 / 总结）
```

## content.json 最小字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `topicId` | string | 稳定 ID，与路径目录名一致 |
| `version` | int | 内容版本；进度 localStorage key 含此版本 |
| `subject` | string | 如 `math` |
| `title` | string | 课题名 |
| `cues` | array | 线索问题，每项 `id` / `mod` / `text` / `hint?` |
| `modules` | array | 笔记模块，每项 `id` / `title` / `body` / `tags?` / `table?` |
| `summary` | string | 总结栏 |
| `oneLiner` | string | 一句话记忆 |

可选：`grade`, `subjectLabel`, `kuIds`, `kcIds`, `dateLabel`。

## 进度 key

```
cornell_{topicId}_v{version}
```

## 红线

自报「已掌握」只写进度 JSON，**不得**写入 `kc_mastery` / 调用 `process_interaction`。

前端播放器在 `mneme-web`：`/subjects/math/cornell`。
