-- mart_atti_api_materia — atti fuori collezione per materia e stato

SELECT
    materia,
    stato,
    COUNT(*) AS n_atti,
    MIN(anno) AS anno_min,
    MAX(anno) AS anno_max,
    SUM(CASE WHEN vigenza_inizio IS NOT NULL THEN 1 ELSE 0 END) AS n_con_vigenza
FROM clean_input
GROUP BY materia, stato
HAVING COUNT(*) >= 1
