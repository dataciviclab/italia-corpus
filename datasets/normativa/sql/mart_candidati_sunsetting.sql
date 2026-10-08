-- mart_candidati_sunsetting — atti vigenti con sunsetting_score alto, per materia
-- (segnale di deperimento/candidati a revisione, NON policy giuridica)

SELECT
    COALESCE(materia, 'non-classificata') AS materia,
    COUNT(*) AS n_candidati,
    ROUND(AVG(sunsetting_score), 1) AS sunsetting_medio,
    ROUND(AVG(eta_anni), 1) AS eta_media,
    ROUND(AVG(n_citazioni), 1) AS citazioni_medie,
    ROUND(AVG(lunghezza_parole), 1) AS parole_medie
FROM clean_input
WHERE stato = 'vigente'
  AND sunsetting_score IS NOT NULL
  AND sunsetting_score >= 50
GROUP BY 1
HAVING COUNT(*) >= 1
ORDER BY n_candidati DESC
