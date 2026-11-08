-- mart_riferimenti_urn — archi con URN canonica su entrambi i lati.
--
-- Grain: una riga per (fonte_urn, bersaglio_urn, rel_type).
-- È il contratto che usa legal-graph: join esatto su `nodes.id`, senza
-- normalizzazione URN nel compose. La regola di canonicalizzazione vive in
-- IC (grafo_riferimenti: corpus + atti_index), non nei consumer.
--
-- `MAX(peso)` conserva la semantica storica: legal-graph aggregava con MAX i
-- pesi delle espressioni (ORIGINALE/VIGENZA) dello stesso atto, non la somma.
SELECT
    fonte_urn,
    bersaglio_urn,
    rel_type,
    MAX(peso) AS peso,
    MAX(fonte_anno) AS fonte_anno,
    MAX(bersaglio_anno) AS bersaglio_anno,
    MIN(contesto) AS contesto,
    BOOL_OR(clausola_lettura) AS clausola_lettura,
    -- serve alla guardia temporale del compose: l'eccezione per gli edge
    -- regex deboli (peso < 5) non vale per le citation AKN
    BOOL_OR(origine = 'regex') AS da_regex
FROM clean_input
WHERE NULLIF(fonte_urn, '') IS NOT NULL
  AND NULLIF(bersaglio_urn, '') IS NOT NULL
GROUP BY 1, 2, 3
