-- mart_frontiera — dove vive il bersaglio di ogni arco.
--
-- Grain: una riga per (dominio_bersaglio, esito).
--
-- Risponde alla domanda di copertura del grafo: quanto del diritto citato è
-- nel corpus, quanto è noto ma fuori (catalogo Normattiva, direttive UE),
-- quanto è fuori da ogni perimetro conosciuto. Prima del 2026-11 il dato non
-- esisteva: `risolto` era binario e misurava solo la presenza nel corpus
-- (~10% del catalogo), facendo sembrare "rotto" ciò che era solo esterno.
--
-- `dominio_bersaglio` vuoto = bersaglio con identità non-URN (es. articolo
-- della Costituzione, che usa `bersaglio_id`): non è un atto, non ha dominio.
-- `n_con_celex` conta gli archi UE agganciabili a un nodo CELEX.

SELECT
    COALESCE(NULLIF(dominio_bersaglio, ''), 'non_urn') AS dominio_bersaglio,
    COALESCE(NULLIF(esito, ''), 'non_classificato')    AS esito,
    COUNT(*)                                           AS n_archi,
    COUNT(DISTINCT NULLIF(bersaglio_urn, ''))          AS n_bersagli,
    COUNT(DISTINCT NULLIF(fonte_urn, ''))              AS n_fonti,
    SUM(peso)                                          AS peso_totale,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_archi,
    SUM(CASE WHEN bersaglio_celex IS NOT NULL THEN 1 ELSE 0 END) AS n_con_celex
FROM clean_input
GROUP BY 1, 2
ORDER BY n_archi DESC
