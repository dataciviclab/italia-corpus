-- mart_debt_legale — archi risolti da fonte vigente verso target non-vigenti
-- Interpretazione: segna-lavoro editoriali (debt ≠ sempre errore; può essere
-- catena di sostituzione/abrogazione o citazione storica).

SELECT
    r.fonte_stato,
    r.bersaglio_stato,
    r.origine,
    COUNT(*) AS n_archi,
    ROUND(AVG(r.peso), 2) AS peso_medio,
    SUM(r.peso) AS peso_totale,
    COUNT(DISTINCT r.fonte_source_file) AS n_fonti,
    COUNT(DISTINCT r.bersaglio_source_file) AS n_bersagli
FROM clean_input r
WHERE r.risolto = true
  AND r.fonte_stato = 'vigente'
  AND r.bersaglio_stato IN ('abrogato', 'decaduto')
GROUP BY 1, 2, 3
HAVING COUNT(*) >= 1
ORDER BY n_archi DESC
