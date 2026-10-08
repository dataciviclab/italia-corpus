-- mart_atti_per_tipo — distribuzione atti per tipo e stato (tombstone corpus)

SELECT
    tipo,
    stato,
    COUNT(*) AS n_atti,
    ROUND(AVG(lunghezza_parole), 1) AS parole_medie,
    ROUND(AVG(qualita_score), 1) AS qualita_media,
    SUM(CASE WHEN orfano THEN 1 ELSE 0 END) AS n_orfani,
    SUM(CASE WHEN duplicato THEN 1 ELSE 0 END) AS n_duplicati,
    SUM(CASE WHEN ingresso_in_vigore IS NOT NULL THEN 1 ELSE 0 END) AS n_con_eiv
FROM clean_input
WHERE tipo IS NOT NULL
  AND stato IS NOT NULL
GROUP BY tipo, stato
HAVING COUNT(*) >= 1
