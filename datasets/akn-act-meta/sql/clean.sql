-- clean.sql — italia-corpus / akn_act_meta
--
-- Meta AKN per atto. EIV tipizzata come DATE (da authorialNote).
-- fonte_file è univoco sul corpus fetchato (PK).

SELECT
    normalize_string(fonte_file)                                 AS fonte_file,
    NULLIF(normalize_string(fonte_urn), '')                      AS fonte_urn,
    NULLIF(normalize_string(fonte_codice), '')                   AS fonte_codice,
    NULLIF(normalize_string(eiv), '')                            AS eiv_raw,
    TRY_CAST(eiv AS DATE)                                        AS eiv,
    NULLIF(normalize_string(eli_version), '')                    AS eli_version,
    NULLIF(normalize_string(eli_type_document), '')              AS eli_type_document,
    TRY_CAST(eli_date_document AS DATE)                          AS eli_date_document,
    TRY_CAST(n_refs AS BIGINT)                                   AS n_refs,
    TRY_CAST(n_eventRef AS BIGINT)                               AS n_event_ref,
    TRY_CAST(n_repeal_events AS BIGINT)                          AS n_repeal_events,
    TRY_CAST(n_active_mods AS BIGINT)                            AS n_active_mods,
    NULLIF(normalize_string(mod_types_json), '')                 AS mod_types_json,
    CAST(has_workflow AS BOOLEAN)                                AS has_workflow,
    TRY_CAST(n_passive_ref AS BIGINT)                            AS n_passive_ref,
    NULLIF(normalize_string(event_types_json), '')               AS event_types_json
FROM raw_input
WHERE fonte_file IS NOT NULL
  AND normalize_string(fonte_file) <> ''
