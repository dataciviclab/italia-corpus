-- clean.sql — italia-corpus / atti_index
--
-- Contratto pubblico: una riga per atto del catalogo Normattiva.
--   PK = (codice_redazionale, data_gu) — il codice è riciclato, la data
--   disambigua; `stato` viene dalla classe ufficiale (3 = lista abrogati),
--   `in_corpus` dice se l'atto è nel corpus MD, `urn` è quella del corpus o
--   quella appresa (urn_fonte = corpus|appresa) — NULL quando l'identità non
--   è determinabile: nessuna URN inventata.
--
-- Solo typing + normalizzazione. Nessun drop di colonne contract.

SELECT
    normalize_string(codice_redazionale)                         AS codice_redazionale,
    TRY_CAST(data_gu AS DATE)                                    AS data_gu,
    normalize_string(classe)                                     AS classe,
    normalize_string(stato)                                      AS stato,
    NULLIF(normalize_string(denominazione), '')                  AS denominazione,
    TRY_CAST(anno AS INTEGER)                                    AS anno,
    NULLIF(normalize_string(numero), '')                         AS numero,
    TRY_CAST(data_emanazione AS DATE)                            AS data_emanazione,
    NULLIF(normalize_string(numero_gu), '')                      AS numero_gu,
    NULLIF(normalize_string(titolo), '')                         AS titolo,
    NULLIF(normalize_string(descrizione), '')                    AS descrizione,
    CAST(in_corpus AS BOOLEAN)                                   AS in_corpus,
    NULLIF(normalize_string(corpus_urn), '')                     AS corpus_urn,
    NULLIF(normalize_string(corpus_filename), '')                AS corpus_filename,
    NULLIF(normalize_string(tipo_slug), '')                      AS tipo_slug,
    NULLIF(normalize_string(emittente), '')                      AS emittente,
    NULLIF(normalize_string(urn), '')                            AS urn,
    NULLIF(normalize_string(urn_fonte), '')                      AS urn_fonte,
    TRY_CAST(fetched_at AS TIMESTAMP)                            AS fetched_at
FROM raw_input
WHERE NULLIF(normalize_string(codice_redazionale), '') IS NOT NULL
  AND NULLIF(normalize_string(data_gu), '') IS NOT NULL
