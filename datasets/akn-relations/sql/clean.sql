-- clean.sql — italia-corpus / akn_relations
--
-- Relazioni tipizzate AKN. PK sintetico = edge_id (hash attributi),
-- perché alcune righe possono ripetersi su (fonte, target, tipo, origin, detail).

SELECT
    md5(
        COALESCE(fonte_urn, '') || '|' ||
        COALESCE(target_urn, '') || '|' ||
        COALESCE(rel_type, '') || '|' ||
        COALESCE(origin, '') || '|' ||
        COALESCE(detail, '')
    )                                                           AS edge_id,
    NULLIF(normalize_string(fonte_urn), '')                     AS fonte_urn,
    NULLIF(normalize_string(fonte_codice), '')                  AS fonte_codice,
    NULLIF(normalize_string(target_urn), '')                    AS target_urn,
    normalize_string(rel_type)                                  AS rel_type,
    normalize_string(origin)                                    AS origin,
    NULLIF(normalize_string(detail), '')                        AS detail,
    -- testo del paragrafo che contiene il <ref>: serve a distinguere una
    -- citazione da una clausola di lettura (contesto assente sui parquet
    -- prodotti prima del 2026-10-30 → NULL, non classificabile)
    NULLIF(LEFT(contesto, 240), '')                             AS contesto
FROM raw_input
WHERE fonte_urn IS NOT NULL
  AND rel_type IS NOT NULL
