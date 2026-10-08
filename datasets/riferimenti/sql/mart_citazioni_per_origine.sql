-- mart_citazioni_per_origine — copertura grafo regex vs AKN
-- (union engine: regex copre corpus pieno; AKN aggiunge tipi e recall)

SELECT
    origine,
    COUNT(*) AS n_archi,
    COUNT(DISTINCT fonte_source_file) AS n_fonti,
    COUNT(DISTINCT bersaglio_source_file) AS n_bersagli,
    ROUND(AVG(peso), 2) AS peso_medio,
    SUM(CASE WHEN risolto THEN 1 ELSE 0 END) AS n_risolti
FROM clean_input
GROUP BY origine
HAVING COUNT(*) >= 1
ORDER BY n_archi DESC
