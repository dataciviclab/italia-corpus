-- mart_citazioni_costituzionali — proiezione consumer delle citazioni
-- all Costituzione (origine='costituzione').
--
-- Una riga per (atto, articolo citato): è il dato che serve a
-- costituzione-italiana (dashboard "Citazioni": KPI, top articoli, trend per
-- anno, per tipo di fonte) senza scaricare il clean completo (13 MB): qui
-- ~200 KB.
--
-- `peso` = numero di occorrenze della citazione nello stesso atto (già
-- deduplicato in `riferimenti`).

SELECT
    fonte_source_path AS fonte_filename,
    TRY_CAST(fonte_anno AS INTEGER) AS fonte_anno,
    fonte_tipo,
    TRY_CAST(regexp_extract(bersaglio_id, 'art:([0-9]+)$', 1) AS INTEGER) AS articolo,
    TRY_CAST(peso AS BIGINT) AS peso
FROM clean_input
WHERE origine = 'costituzione'
  AND bersaglio_id IS NOT NULL
ORDER BY fonte_anno, articolo
