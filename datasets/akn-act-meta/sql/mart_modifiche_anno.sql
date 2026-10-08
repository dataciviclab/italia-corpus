-- mart_modifiche_anno — atti AKN con modifiche attive, per anno atto
-- fonte_file = <Collezione>/YYYY-MM-DD_... → anno dal basename

SELECT
    TRY_CAST(regexp_extract(fonte_file, '(\d{4})-\d{2}-\d{2}_', 1) AS INTEGER) AS anno_atto,
    COUNT(*) AS n_atti,
    SUM(CASE WHEN n_active_mods > 0 THEN 1 ELSE 0 END) AS n_con_modifiche,
    SUM(n_active_mods) AS tot_modifiche,
    SUM(CASE WHEN n_repeal_events > 0 THEN 1 ELSE 0 END) AS n_con_repeal,
    SUM(CASE WHEN has_workflow THEN 1 ELSE 0 END) AS n_con_workflow,
    ROUND(AVG(n_refs), 1) AS refs_medie
FROM clean_input
WHERE fonte_file IS NOT NULL
  AND regexp_extract(fonte_file, '(\d{4})-\d{2}-\d{2}_', 1) <> ''
GROUP BY 1
HAVING COUNT(*) >= 1
ORDER BY anno_atto
