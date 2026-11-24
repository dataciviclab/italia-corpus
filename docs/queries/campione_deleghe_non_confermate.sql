-- Campione riproducibile delle deleghe NON confermate dal preambolo.
--
-- Serve a decidere se declassare gli archi `attua_delega` che il preambolo non
-- conferma. L'ordinamento per md5 della coppia è deterministico e **non**
-- correlato all'età dell'atto (i primi 20 in ordine di URN erano tutti del
-- 1988-89: campione distorto).
--
-- Uso: duckdb su GCS (o sui parquet locali sostituendo i path).
--   duckdb -c ".read docs/queries/campione_deleghe_non_confermate.sql"

WITH delega AS (
    SELECT DISTINCT fonte_urn, bersaglio_urn
    FROM read_parquet(
        'https://storage.googleapis.com/dataciviclab-mart/italia-corpus/riferimenti/2026/mart_riferimenti_urn.parquet'
    )
    WHERE rel_type = 'delega' AND origine = 'preambolo'
),
edge AS (
    SELECT source_id, target_id
    FROM read_parquet(
        'https://storage.googleapis.com/dataciviclab-mart/legal-graph/legal_graph/2026/mart_legal_edges.parquet'
    )
    WHERE relation = 'attua_delega'
)
SELECT
    e.source_id AS attuativo,
    e.target_id AS delegante
FROM edge e
LEFT JOIN delega d
    ON d.fonte_urn = e.source_id AND d.bersaglio_urn = e.target_id
WHERE d.fonte_urn IS NULL
ORDER BY md5(e.source_id || e.target_id)
LIMIT 20;
