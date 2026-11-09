-- mart_direttive_per_anno — direttive UE citate, per anno e stato di
-- risoluzione. L'anno è quello dell'atto (`data`, 1962-2025), non il prefisso
-- CELEX: gli URN non risolti includono citazioni impossibili (1921-1957,
-- 2027) che nel mart non devono entrare. `n_con_ritardo` / `n_in_ritardo`
-- usano solo i ritardi plausibili (<= 3 anni): oltre, spesso manca la prima
-- misura in Cellar.

SELECT
    TRY_CAST(regexp_extract(CAST("data" AS VARCHAR), '^(\d{4})', 1) AS INTEGER) AS anno,
    stato,
    COUNT(*)                                        AS n_direttive,
    COUNT(*) FILTER (WHERE ritardo_plausibile)      AS n_con_ritardo,
    COUNT(*) FILTER (
        WHERE ritardo_plausibile AND ritardo_recepimento_giorni > 0
    )                                               AS n_in_ritardo,
    CAST(
        ROUND(
            MEDIAN(ritardo_recepimento_giorni) FILTER (
                WHERE ritardo_plausibile AND ritardo_recepimento_giorni > 0
            )
        ) AS INTEGER
    )                                               AS ritardo_mediano_giorni
FROM clean_input
WHERE stato = 'risolto' AND "data" IS NOT NULL
GROUP BY 1, 2
ORDER BY anno, stato
