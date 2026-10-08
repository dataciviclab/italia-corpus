-- mart_relazioni_per_tipo — volume relazioni AKN tipizzate
-- (fonte ufficiale del grafo Normattiva, non proxy regex)

SELECT
    rel_type,
    origin,
    COUNT(*) AS n_relazioni,
    COUNT(DISTINCT fonte_urn) AS n_fonti,
    COUNT(DISTINCT target_urn) AS n_bersagli,
    SUM(CASE WHEN target_urn IS NULL OR target_urn = '' THEN 1 ELSE 0 END) AS n_senza_target
FROM clean_input
GROUP BY 1, 2
HAVING COUNT(*) >= 1
ORDER BY n_relazioni DESC
