-- mart_materia_stato — crociera materia × stato del corpus

SELECT
    COALESCE(materia, 'non-classificata') AS materia,
    stato,
    COUNT(*) AS n_atti,
    ROUND(AVG(qualita_score), 1) AS qualita_media,
    ROUND(AVG(sunsetting_score), 1) AS sunsetting_medio,
    SUM(CASE WHEN orfano THEN 1 ELSE 0 END) AS n_orfani,
    SUM(CASE WHEN n_citazioni > 0 THEN 1 ELSE 0 END) AS n_citati
FROM clean_input
GROUP BY 1, stato
HAVING COUNT(*) >= 1
