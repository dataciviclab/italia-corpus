-- mart_catalogo_copertura — quanto del catalogo ufficiale è nel corpus
--
-- Unico denominatore onesto della copertura IC: catalogo Normattiva per
-- anno × denominazione × classe. `copertura_pct` = atti nel corpus / atti
-- del catalogo. Serve alle analisi ("quali leggi mancano") e al
-- monitoraggio: se un anno recente scende, il fetch ha un buco.

SELECT
    anno,
    CAST(FLOOR(anno / 10.0) * 10 AS INTEGER)                     AS decade,
    denominazione,
    classe,
    COUNT(*)                                                      AS n_atti,
    COUNT(*) FILTER (WHERE in_corpus)                             AS n_in_corpus,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE in_corpus) / COUNT(*), 1
    )                                                             AS copertura_pct
FROM clean_input
WHERE anno IS NOT NULL
GROUP BY 1, 2, 3, 4
ORDER BY anno DESC, n_atti DESC
