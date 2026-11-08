-- clean.sql — italia-corpus / atti_api
--
-- Contratto: una riga per atto fetchato singolarmente via
-- `dettaglio-atto-urn` (leggi ordinarie fuori dalle collezioni ZIP).
-- PK = urn.
--
-- Il testo **non** è nel contratto: l'endpoint restituisce un solo articolo
-- (art. 1) e resta nel raw. Il contratto testi sarà `articoli`.
-- I nomi colonna restano quelli del raw (`tipo_descrizione`, `titolo`, ...):
-- legal-graph li legge così, e questo dataset nasce per sostituire il
-- `path: data/derived/atti_api.parquet` con `slug: atti_api, layer: clean`.

SELECT
    normalize_string(urn)                          AS urn,
    NULLIF(normalize_string(titolo), '')           AS titolo,
    NULLIF(normalize_string(sotto_titolo), '')     AS sotto_titolo,
    NULLIF(normalize_string(tipo_codice), '')      AS tipo_codice,
    NULLIF(normalize_string(tipo_descrizione), '') AS tipo_descrizione,
    TRY_CAST(numero AS BIGINT)                     AS numero,
    TRY_CAST(anno AS INTEGER)                      AS anno,
    TRY_CAST(anno_gu AS INTEGER)                   AS anno_gu,
    NULLIF(normalize_string(numero_gu), '')        AS numero_gu,
    TRY_CAST(vigenza_inizio AS DATE)               AS vigenza_inizio,
    TRY_CAST(vigenza_fine AS DATE)                 AS vigenza_fine,
    normalize_string(stato)                        AS stato,
    COALESCE(NULLIF(normalize_string(materia), ''), 'altro') AS materia,
    TRY_CAST(n_articoli AS INTEGER)                AS n_articoli,
    normalize_string(source)                       AS source,
    TRY_CAST(fetched_at AS TIMESTAMP)              AS fetched_at
FROM raw_input
WHERE NULLIF(normalize_string(urn), '') IS NOT NULL
