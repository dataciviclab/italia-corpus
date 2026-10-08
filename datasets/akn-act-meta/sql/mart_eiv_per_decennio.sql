-- mart_eiv_per_decennio — ingresso in vigore (EIV AKN) per decennio
-- (copertura parziale dove AKN ha authorialNote; non è vigenza live)

SELECT
    (CAST(EXTRACT(YEAR FROM eiv) AS INTEGER) / 10) * 10 AS decennio,
    COUNT(*) AS n_con_eiv,
    COUNT(DISTINCT fonte_file) AS n_atti,
    SUM(CASE WHEN n_active_mods > 0 THEN 1 ELSE 0 END) AS n_con_modifiche,
    SUM(CASE WHEN has_workflow THEN 1 ELSE 0 END) AS n_con_workflow
FROM clean_input
WHERE eiv IS NOT NULL
GROUP BY 1
HAVING COUNT(*) >= 1
ORDER BY decennio
