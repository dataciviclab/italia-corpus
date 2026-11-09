-- mart_direttive_per_anno — direttive UE citate, per anno e stato di
-- risoluzione. `n_con_ritardo` / `n_in_ritardo` usano solo i ritardi
-- plausibili (<= 3 anni): oltre, spesso manca la prima misura in Cellar.

SELECT
    substring(celex, 2, 4)                          AS anno,
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
GROUP BY 1, 2
ORDER BY anno, stato
