-- mart_top_bersagli — atti più citati in ingresso (hub del grafo)
-- PK = bersaglio_source_path (basename da solo non è univoco tra collezioni)

SELECT
    bersaglio_source_path,
    bersaglio_source_file,
    COUNT(*) AS n_citazioni,
    SUM(peso) AS peso_totale,
    SUM(CASE WHEN origine = 'regex' THEN 1 ELSE 0 END) AS da_regex,
    SUM(CASE WHEN origine = 'akn' THEN 1 ELSE 0 END) AS da_akn,
    -- rinvii di sola lettura ("al solo fine di facilitare la lettura"):
    -- non sono citazioni. `non_classificabili` = archi AKN senza contesto.
    SUM(CASE WHEN clausola_lettura THEN 1 ELSE 0 END) AS n_clausole_lettura,
    SUM(CASE WHEN clausola_lettura IS NULL THEN 1 ELSE 0 END) AS n_non_classificabili,
    SUM(CASE WHEN clausola_lettura IS NOT TRUE THEN 1 ELSE 0 END) AS n_citazioni_sostanziali,
    COUNT(DISTINCT fonte_source_file) AS n_fonti_distinte
FROM clean_input
WHERE risolto = true
GROUP BY 1, 2
HAVING COUNT(*) >= 20
ORDER BY n_citazioni DESC
LIMIT 200
