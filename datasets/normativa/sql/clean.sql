-- clean.sql — italia-corpus / normativa
--
-- Contratto pubblico (backward-compatible legal-graph + IC MCP):
--   - PK = filename (basename univoco del file corpus)
--   - urn può ripetersi: non è PK; per analisi si usa come atto_id secondario
--   - stato = tombstone Normattiva (NON vigenza live) — colonna rinominata solo in doc
--   - materia / qualita_score / sunsetting_score: contratto consumer (LG + MCP)
--   - vigente: derivato da stato; tenuto per compat MCP
--   - akn_*: presenti sul corpus pieno; EIV in ingresso_in_vigore
--
-- Solo typing + normalizzazione. Nessun drop di colonne contract.

SELECT
    normalize_string(filename)                                   AS filename,
    normalize_string(collezione)                                 AS collezione,
    normalize_string(tipo)                                       AS tipo,
    TRY_CAST(data AS DATE)                                       AS data,
    normalize_string(numero)                                     AS numero,
    normalize_string(oggetto)                                    AS oggetto,
    NULLIF(normalize_string(celex), '')                          AS celex,
    TRY_CAST(anno_atto AS INTEGER)                               AS anno_atto,
    TRY_CAST(anno_dir AS INTEGER)                                AS anno_dir,
    CAST(ritardo AS DOUBLE)                                      AS ritardo,
    NULLIF(normalize_string(urn), '')                            AS urn,
    NULLIF(normalize_string(codice_redazionale), '')             AS codice_redazionale,
    normalize_string(stato)                                      AS stato,
    CAST(vigente AS BOOLEAN)                                     AS vigente,
    TRY_CAST(lunghezza_caratteri AS BIGINT)                      AS lunghezza_caratteri,
    TRY_CAST(lunghezza_parole AS BIGINT)                         AS lunghezza_parole,
    TRY_CAST(riferimenti_interni AS BIGINT)                      AS riferimenti_interni,
    CAST(duplicato AS BOOLEAN)                                   AS duplicato,
    TRY_CAST(n_citazioni AS BIGINT)                              AS n_citazioni,
    CAST(orfano AS BOOLEAN)                                      AS orfano,
    TRY_CAST(qualita_score AS BIGINT)                            AS qualita_score,
    NULLIF(normalize_string(materia), '')                        AS materia,
    TRY_CAST(sunsetting_score AS BIGINT)                         AS sunsetting_score,
    TRY_CAST(eta_anni AS BIGINT)                                 AS eta_anni,
    TRY_CAST(anni_senza_citazioni AS BIGINT)                     AS anni_senza_citazioni,
    TRY_CAST(ingresso_in_vigore AS DATE)                         AS ingresso_in_vigore,
    TRY_CAST(akn_n_refs AS BIGINT)                               AS akn_n_refs,
    TRY_CAST(akn_n_active_mods AS BIGINT)                        AS akn_n_active_mods,
    TRY_CAST(akn_n_passive_ref AS BIGINT)                        AS akn_n_passive_ref,
    TRY_CAST(akn_n_repeal_events AS BIGINT)                      AS akn_n_repeal_events,
    NULLIF(normalize_string(akn_mod_types), '')                  AS akn_mod_types,
    CAST(akn_has_workflow AS BOOLEAN)                            AS akn_has_workflow,
    NULLIF(normalize_string(akn_meta_source), '')                AS akn_meta_source,
    TRY_CAST(n_articoli_cost AS BIGINT)                          AS n_articoli_cost,
    NULLIF(normalize_string(articoli_cost), '')                  AS articoli_cost,
    NULLIF(normalize_string(abrogato_da), '')                    AS abrogato_da,
    TRY_CAST(n_abrogazioni AS BIGINT)                            AS n_abrogazioni,
    -- atto_id analitico: urn se presente, altrimenti fallback file
    COALESCE(NULLIF(normalize_string(urn), ''), 'file:' || normalize_string(filename)) AS atto_id
FROM raw_input
WHERE filename IS NOT NULL
  AND normalize_string(filename) <> ''
