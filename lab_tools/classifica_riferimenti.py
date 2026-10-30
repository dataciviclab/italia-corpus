"""Classificazione del contesto di un riferimento normativo.

Non tutte le citazioni sono diritto. La più diffusa in Italia è la **clausola
di lettura**: «…approvato con D.P.R. 28 dicembre 1985, n. 1092, *al solo fine
di facilitare la lettura delle disposizioni di cui al presente articolo*».
Il link serve a far leggere il testo di un'altra norma, non a richiamarla come
fonte: contarla come citazione gonfia le metriche di impatto e fa salire un
testo unico di servizio in cima alla classifica delle norme "più citate".

Misura (2026-10-30, `riferimenti.parquet`): 5.969 citazioni su 200.080 — il
3,0% del totale, il 6,3% di quelle classificabili — sono clausole di lettura;
il 98,7% delle citazioni regex al DPR 1092/1985 è una clausola di lettura.

La regola è volutamente **stretta**: si marca solo ciò che il contesto dichiara
esplicitamente. `False` non vuol dire "citazione sostanziale", vuol dire "non
è una clausola di lettura"; `None` vuol dire "contesto non disponibile".

Contesto non disponibile è il caso AKN: `grafo_riferimenti` scrive `akn:ref`
come segnaposto, quindi metà degli archi (105.226 su 200.080) oggi non è
classificabile. Servirà catturare il testo attorno al `<ref>` in
`akn_relations` per chiudere anche quella metà.
"""

from __future__ import annotations

import re

# Frasi che dichiarano il rinvio di sola lettura. Tenute separate e commentate:
# aggiungerne una è un cambio di contratto (la colonna `clausola_lettura`),
# non un dettaglio implementativo.
PATTERN_LETTURA: tuple[re.Pattern[str], ...] = (
    # "al solo fine di facilitare la lettura delle disposizioni di cui a…"
    re.compile(r"facilitare\s+la\s+lettura", re.IGNORECASE),
    # varianti rare/possibili: "ai soli fini della lettura"
    re.compile(r"ai\s+soli\s+fini\s+della\s+lettura", re.IGNORECASE),
)

# Segnaposto scritto da grafo_riferimenti per gli archi AKN (nessun testo)
CONTESTO_SEGNAPOSTO = "akn:ref"


def clausola_di_lettura(contesto: str | None) -> bool | None:
    """True se il contesto dichiara un rinvio di sola lettura.

    Returns:
        True   — clausola di lettura esplicita
        False  — contesto presente, nessun marker di lettura
        None   — contesto assente o segnaposto (`akn:ref`): non classificabile
    """
    if not contesto or not isinstance(contesto, str):
        return None
    testo = contesto.strip()
    if not testo or testo == CONTESTO_SEGNAPOSTO:
        return None
    return any(p.search(testo) for p in PATTERN_LETTURA)
