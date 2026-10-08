-- clean.sql — italia-corpus / riferimenti
--
-- Grain: un arco = una citazione rilevata (regex markdown ∪ AKN).
-- PK: fonte_source_path + bersaglio_source_path + origine
--   (basename-only non è univoco: ~117k su 136k — collassa fonti diverse)
--
-- Compatibilità legal-graph:
--   - fonte_filename  = valore engine (path relativo collezione per regex, basename per AKN)
--   - bersaglio_filename = basename (join LG diretto su normativa.filename)
--   - *_source_file   = basename canonico per nuovi consumer
--   - *_source_path   = path risolto per PK e join stabili
--
-- Drop documentati (denorm non letti da legal-graph; derivabili da join):
--   fonte_materia, bersaglio_materia, fonte_stato, bersaglio_stato,
--   fonte_tipo, bersaglio_tipo, fonte_collezione, bersaglio_collezione, bersaglio_path

WITH base AS (
    SELECT
        fonte_filename,
        fonte_collezione,
        fonte_anno,
        fonte_tipo,
        bersaglio_filename,
        bersaglio_path,
        bersaglio_anno,
        bersaglio_tipo,
        peso,
        risolto,
        origine,
        rel_type,
        CASE
            WHEN fonte_filename LIKE '%/%'
                THEN regexp_extract(fonte_filename, '/([^/]+)$', 1)
            ELSE fonte_filename
        END AS fonte_source_file,
        CASE
            WHEN bersaglio_filename LIKE '%/%'
                THEN regexp_extract(bersaglio_filename, '/([^/]+)$', 1)
            ELSE bersaglio_filename
        END AS bersaglio_source_file,
        CASE
            WHEN fonte_filename LIKE '%/%'
                THEN fonte_filename
            WHEN COALESCE(fonte_collezione, '') <> ''
                THEN fonte_collezione || '/' || fonte_filename
            ELSE fonte_filename
        END AS fonte_source_path,
        CASE
            WHEN COALESCE(bersaglio_path, '') <> ''
                THEN bersaglio_path
            WHEN bersaglio_filename LIKE '%/%'
                THEN bersaglio_filename
            WHEN COALESCE(fonte_collezione, '') <> ''
                THEN fonte_collezione || '/' || bersaglio_filename
            ELSE bersaglio_filename
        END AS bersaglio_source_path
    FROM raw_input
    WHERE fonte_filename IS NOT NULL
      AND bersaglio_filename IS NOT NULL
      AND normalize_string(origine) <> ''
)
SELECT
    fonte_source_path,
    bersaglio_source_path,
    fonte_source_file,
    bersaglio_source_file,
    fonte_filename,
    bersaglio_filename,
    TRY_CAST(fonte_anno AS INTEGER)   AS fonte_anno,
    TRY_CAST(bersaglio_anno AS INTEGER) AS bersaglio_anno,
    TRY_CAST(peso AS BIGINT)          AS peso,
    CAST(risolto AS BOOLEAN)          AS risolto,
    normalize_string(origine)         AS origine,
    normalize_string(rel_type)        AS rel_type
FROM base
