-- mart_modifiche_tipizzate — repeal/substitution/split/join (successioni)
-- Più informativo di abrogations_raw: tipi AKN + URN target

SELECT
    rel_type,
    COUNT(*) AS n_relazioni,
    COUNT(DISTINCT fonte_urn) AS n_fonti,
    COUNT(DISTINCT target_urn) AS n_bersagli
FROM clean_input
WHERE rel_type IN ('repeal', 'substitution', 'split', 'join', 'renumbering')
GROUP BY rel_type
HAVING COUNT(*) >= 1
ORDER BY n_relazioni DESC
