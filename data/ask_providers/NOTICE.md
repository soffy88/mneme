# 拍照问题目 · 离线答题数据的来源与许可

这些数据**不进 git**：`scripts/ask_data/fetch_and_build.py` 按本目录 `MANIFEST.json`（固定 commit + 逐文件 sha256）
下载，并构建成 SQLite 放到 `MNEME_ASK_DATA_DIR`（默认 `data/external/ask_providers/`）。

| 数据 | 上游 | 固定 commit | 许可 |
|---|---|---|---|
| 英汉词典 ECDICT（`ecdict.csv`） | https://github.com/skywind3000/ECDICT | bc015ed2e24a7abef49fc6dbbb7fe32c1dadaf8b | MIT, Copyright (c) 2017 Linwei |
| 古诗词 chinese-poetry（全唐诗/全宋诗/宋词/元曲/诗经/楚辞/曹操诗集/五代诗词 + rank） | https://github.com/chinese-poetry/chinese-poetry | b8594f81a89752241442f2ce267d6f66f96704ee | MIT, Copyright (c) 2016 JackeyGao |
| 成语 chinese-xinhua（`data/idiom.json`） | https://github.com/pwxcoo/chinese-xinhua | fe6d6c2e8baa82187f4c96bbe042e43f96c05666 | MIT, Copyright (c) 2018 pwxcoo |

运行时依赖：pypinyin（MIT, https://github.com/mozillazg/python-pinyin）。
构建期依赖：opencc-python-reimplemented（Apache-2.0）仅用于繁转简，不进运行镜像。
上游 LICENSE 原文随 MANIFEST 一起下载到 `_cache/<src>/LICENSE` 并校验。

说明：chinese-xinhua 的仓库许可为 MIT；其成语释义整理自公开辞书，若后续发现上游许可变化，删除 idiom.sqlite 即可，
成语功能会静默关闭（其余功能不受影响）。
