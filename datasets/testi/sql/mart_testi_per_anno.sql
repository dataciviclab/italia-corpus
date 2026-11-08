-- mart_testi_per_anno — volume del testo per anno di pubblicazione
-- (l'anno è il prefisso del filename: AAAA-MM-GG_CODICE_...)

SELECT
    regexp_extract(filename, '^(\d{4})', 1)    AS anno,
    COUNT(*)                                    AS n_testi,
    CAST(ROUND(AVG(length(testo))) AS INTEGER)  AS chars_medi,
    MAX(length(testo))                          AS chars_max,
    COUNT(*) FILTER (WHERE length(testo) = 0)   AS testi_vuoti
FROM clean_input
WHERE regexp_extract(filename, '^(\d{4})', 1) <> ''
GROUP BY 1
HAVING COUNT(*) >= 1
ORDER BY anno
