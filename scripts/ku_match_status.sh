#!/bin/bash
docker exec mneme-db-1 psql -U postgres -d mneme -c "
SELECT ku_match_meta->>'model' AS model, count(*) FROM wrong_questions WHERE ku_match_meta IS NOT NULL GROUP BY 1 ORDER BY 2 DESC;
SELECT count(*) FILTER (WHERE knowledge_points::text LIKE '%cmm-math-g7-%' AND ku_match_meta IS NULL) AS g7_pending,
       count(*) FILTER (WHERE knowledge_points::text LIKE '%cmm-math-g8-%' AND ku_match_meta IS NULL) AS g8_pending,
       count(*) FILTER (WHERE knowledge_points::text LIKE '%cmm-math-g9-%' AND ku_match_meta IS NULL) AS g9_pending
FROM wrong_questions;
SELECT count(*) FILTER (WHERE ku_match_meta->>'model'='qwen3-8b' AND knowledge_points::text LIKE '%RENJIAO%') AS matched_ok,
       count(*) FILTER (WHERE ku_match_meta->>'model'='qwen3-8b' AND knowledge_points::text LIKE '%cmm-math%') AS failed_keep_cmm
FROM wrong_questions;
"
pgrep -af 'match_questions_to_ku' || echo '(batch not running)'
