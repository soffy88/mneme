SELECT 'textbooks' AS table_name, count(*) AS cnt FROM textbooks WHERE id LIKE 'ctsf-%'
UNION ALL
SELECT 'knowledge_units', count(*) FROM knowledge_units WHERE id LIKE 'ctsf-%'
UNION ALL
SELECT 'question_records', count(*) FROM question_records WHERE source = 'ctsf-v1.2.0'
UNION ALL
SELECT 'reading_passages', count(*) FROM reading_passages WHERE source_url LIKE 'ctsf%';

SELECT '--- Sample Textbooks ---' as sample;
SELECT id, book_name FROM textbooks WHERE id LIKE 'ctsf-%' LIMIT 2;

SELECT '--- Sample Knowledge Units ---' as sample;
SELECT id, name FROM knowledge_units WHERE id LIKE 'ctsf-%' LIMIT 2;

SELECT '--- Sample Question Records ---' as sample;
SELECT id, left(question_text, 40) FROM question_records WHERE source = 'ctsf-v1.2.0' LIMIT 2;

SELECT '--- Sample Reading Passages ---' as sample;
SELECT id, left(title, 40) FROM reading_passages WHERE source_url LIKE 'ctsf%' LIMIT 2;
