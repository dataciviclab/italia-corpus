-- mart_frontiera_epoca — la frontiera nel tempo.
--
-- Grain: una riga per (decennio_bersaglio, esito).
--
-- Il decennio è quello dell'atto **citato** (`bersaglio_anno`), non della
-- fonte: dice dove si concentra il diritto che il corpus chiama in causa.
-- Serve a leggere la copertura come dipendenza storica: se il non identificato
-- si addensa in un'epoca, il buco è lì (atti di autorità anni '90, normativa
-- pre-unitaria, direttive UE), non distribuito.
--
-- Esclusi gli archi senza anno del bersaglio (0/NULL): non sono collocabili.

SELECT
    (TRY_CAST(bersaglio_anno AS INTEGER) // 10) * 10 AS decennio_bersaglio,
    COALESCE(NULLIF(esito, ''), 'non_classificato') AS esito,
    COUNT(*)                                        AS n_archi,
    COUNT(DISTINCT NULLIF(bersaglio_urn, ''))       AS n_bersagli
FROM clean_input
WHERE TRY_CAST(bersaglio_anno AS INTEGER) > 0
GROUP BY 1, 2
ORDER BY 1, 3 DESC
