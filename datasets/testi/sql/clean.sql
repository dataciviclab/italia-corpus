-- clean.sql — italia-corpus / testi
--
-- Una riga per espressione (`filename`, stessa chiave di `normativa`).
-- Il testo è il body del markdown: document-level, non articolo/comma
-- (quello sarà `articoli`, dal XML AKN).

SELECT
    normalize_string(filename)         AS filename,
    NULLIF(normalize_string(urn), '')  AS urn,
    testo
FROM raw_input
WHERE NULLIF(normalize_string(filename), '') IS NOT NULL
  AND testo IS NOT NULL
