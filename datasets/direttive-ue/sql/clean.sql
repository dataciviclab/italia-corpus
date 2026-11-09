-- clean.sql — italia-corpus / direttive_ue
--
-- Una riga per direttiva, chiave CELEX (`3YYYYLNNNN`). Le due grafie URN di
-- Normattiva (`direttivaue` e `direttiva.ue`) sono in `urn_varianti`,
-- separate da `|` (le URN contengono `;`, quindi `;` non è un separatore
-- sicuro): legal-graph le mappa sullo stesso nodo.
--
-- `stato`: `risolto` (identità e metadati presenti in Cellar) o
-- `non_risolto`. `ritardo_recepimento_giorni` = prima misura italiana −
-- scadenza; `ritardo_plausibile` esclude i ritardi > 3 anni (dove spesso
-- manca la prima misura nell'elenco NIM di Cellar).

SELECT
    normalize_string(celex)                                 AS celex,
    normalize_string(urn_varianti)                          AS urn_varianti,
    TRY_CAST(n_citazioni AS INTEGER)                        AS n_citazioni,
    normalize_string(stato)                                 AS stato,
    NULLIF(normalize_string(motivo), '')                    AS motivo,
    NULLIF(normalize_string(work_uri), '')                  AS work_uri,
    NULLIF(normalize_string(titolo_ita), '')                AS titolo_ita,
    NULLIF(normalize_string(titolo_eng), '')                AS titolo_eng,
    NULLIF(normalize_string(titolo), '')                    AS titolo,
    TRY_CAST("data" AS DATE)                                AS data,
    NULLIF(normalize_string(scadenze), '')                  AS scadenze,
    TRY_CAST(scadenza_recepimento AS DATE)                  AS scadenza_recepimento,
    TRY_CAST(n_scadenze AS INTEGER)                         AS n_scadenze,
    TRY_CAST(in_vigore AS BOOLEAN)                          AS in_vigore,
    TRY_CAST(n_misure_ita AS INTEGER)                       AS n_misure_ita,
    TRY_CAST(prima_notifica_ita AS DATE)                    AS prima_notifica_ita,
    TRY_CAST(prima_misura_ita_data AS DATE)                 AS prima_misura_ita_data,
    TRY_CAST(ritardo_recepimento_giorni AS INTEGER)         AS ritardo_recepimento_giorni,
    TRY_CAST(ritardo_plausibile AS BOOLEAN)                 AS ritardo_plausibile,
    NULLIF(normalize_string(misura_ita_titolo), '')         AS misura_ita_titolo,
    NULLIF(normalize_string(eurlex_url), '')                AS eurlex_url,
    NULLIF(normalize_string(eli_url), '')                   AS eli_url
FROM raw_input
WHERE NULLIF(normalize_string(celex), '') IS NOT NULL
