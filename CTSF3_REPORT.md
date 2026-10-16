# CTSF3 导入报告 (Tag: CTSF3)

## 1. 备份路径
- 备份文件: `/data/soffy/backups/mneme-pre-ctsf3-20261016_100246.sql.gz`
- 大小: ~192 MB (>100MB 确认)

## 2. 每表标记方式 (Queryable Source Marker: 'ctsf-v1.2.0')
- **textbooks**: 使用 `id` 前缀 `ctsf-`（如 `ctsf-math-62c5fae15149`）。
- **knowledge_units**: 使用 `provenance` JSON 字段中的 `{"source": "ctsf-v1.2.0"}` 及 `id` 前缀 `ctsf-`。
- **question_records**: 使用 `source` 列值为 `'ctsf-v1.2.0'`。
- **reading_passages**: 使用 `source_url` 列值为 `'ctsf-v1.2.0'` 或 `'ctsf-v1.2.0-story'`。

## 3. verify_ctsf.out 原文
```
    table_name    |  cnt  
------------------+-------
 textbooks        |    44
 reading_passages |  1063
 question_records | 14307
 knowledge_units  |  1028
(4 rows)

          sample          
--------------------------
 --- Sample Textbooks ---
(1 row)

           id           | book_name  
------------------------+------------
 ctsf-math-62c5fae15149 | 二年级下册
 ctsf-math-7ad61b07869e | 一年级下册
(2 rows)

             sample             
--------------------------------
 --- Sample Knowledge Units ---
(1 row)

              id               |       name       
-------------------------------+------------------
 ctsf-math-f5e5a4933667-u9-kp2 | 几何图形组合复习
 ctsf-math-62c5fae15149-u1-kp1 | 收集数据的方法
(2 rows)

             sample              
---------------------------------
 --- Sample Question Records ---
(1 row)

                  id                  |                      left                      
--------------------------------------+------------------------------------------------
 948d4fd1-d4e9-54ac-b8f3-04f2308fee05 | $25 + 137 + 75 = 137 + (25 + 75)$ 只运用了加法
 f51aef72-b19e-54df-af61-b81b75b89619 | $a \times (b + c) = a \times b + a \time
(2 rows)

             sample              
---------------------------------
 --- Sample Reading Passages ---
(1 row)

         id         |   left   
--------------------+----------
 ctsf-p-6b1dfdfa-12 | 开国大典
 ctsf-p-6b1dfdfa-13 | 灯光
(2 rows)
```

## 4. 删除/清理脚本用法
执行以下命令可按 `ctsf` 标记清理所有导入数据：
```bash
python3 scripts/remove_ctsf.py
```

## 5. 遗留问题
- 无。四科教材（44册）、题目（14,307道）、课文与故事（1,063篇）、知识点（1,028个）均已完整幂等导入并通过校验门。

CTSF3 DONE
