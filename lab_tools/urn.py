"""Normalizzazione e alias degli URN NIR.

Lo stesso atto è scritto in forme diverse dal corpus (frontmatter dei MD e
`normativa.parquet`) e dalle relazioni AKN (`akn_relations.parquet`). Tre casi,
misurati su 251.918 edge di citazione:

- **slug del tipo**: AKN `decretodelpresidentedellarepubblica` vs corpus
  `decreto.del.presidente.della.repubblica` — 50.280 edge;
- **data di riferimento**: la citazione usa la data di pubblicazione in GU, il
  corpus l'emanazione (`legge:1991-07-21;203` vs `legge:1991-07-12;203`) — il
  numero è unico per tipo e anno — 1.072 edge;
- **codici sistematici**: AKN `codice.civile:1942-03-16;262` vs corpus
  `regio.decreto:1942-03-16;262` — 3.574 edge su 3 atti.

Questo modulo è l'unico posto in cui la corrispondenza è definita: lo usano
`fetch_normattiva._build_urn_index` e `grafo_riferimenti._load_urn_to_filename`,
quindi tutti i consumer (in primis `akn_parser.resolve_ref`) la ottengono
indicizzando con `expand_index`.

Regola di risoluzione — **nessun fuzzy match**:

1. URN esatto;
2. slug canonico (tipo senza punti/trattini), solo se univoco;
3. ``(emettitore, tipo, anno, numero)``, solo se punta a una sola entità;
4. tabella statica ``ALIAS_CODICI``.

Le chiavi alias non sovrascrivono mai un URN esatto già presente.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

# Forma NIR canonica: urn:nir:<emettitore>:<tipo>:<YYYY-MM-DD>;<numero>
_URN_RE = re.compile(r"^urn:nir:([^:]+):([^:]+):(\d{4}-\d{2}-\d{2});(\d+)$")
_SEPARATORI_SLUG = re.compile(r"[.\-]")
# L'AKN scrive lo slug concatenato e a volte **senza i connettivi**:
# `decretolegislativo` (corpus `decreto.legislativo`),
# `decretolegge` (corpus `decreto.legge`),
# `decretodelpresidentedellarepubblica` (corpus `decreto.del.presidente.della.repubblica`).
# Il connettivo va tolto **dopo** aver concatenato, così le due forme coincidono.
# `di` è escluso: è sottostringa di parole di tipo (`difesa`, `dighe`).
_CONNETTIVI = re.compile(r"della|delle|dello|degli|dei|del")

# Codici sistematici: l'AKN cita il codice come atto a sé, il corpus lo tiene
# sotto l'atto che lo approva. Tre atti, tabella esplicita (niente euristiche).
ALIAS_CODICI: dict[str, str] = {
    "urn:nir:stato:codice.civile:1942-03-16;262": "urn:nir:stato:regio.decreto:1942-03-16;262",
    "urn:nir:stato:codice.penale:1930-10-19;1398": "urn:nir:stato:regio.decreto:1930-10-19;1398",
    "urn:nir:stato:codice.procedura.civile:1940-10-28;1443": (
        "urn:nir:stato:regio.decreto:1940-10-28;1443"
    ),
    "urn:nir:presidente.repubblica:codice.procedura.penale:1988-09-22;447": (
        "urn:nir:stato:decreto.del.presidente.della.repubblica:1988-09-22;447"
    ),
}


def parse_urn(urn: str) -> tuple[str, str, str, str] | None:
    """(emettitore, tipo, data, numero) oppure None se la forma non è NIR."""
    m = _URN_RE.match((urn or "").strip())
    return (m.group(1), m.group(2), m.group(3), m.group(4)) if m else None


def _slug(tipo: str) -> str:
    """Slug del tipo normalizzato: senza separatori né connettivi."""
    return _CONNETTIVI.sub("", _SEPARATORI_SLUG.sub("", tipo.lower()))


def canonical_key(urn: str) -> str | None:
    """URN con lo slug del tipo normalizzato (senza separatori né connettivi)."""
    p = parse_urn(urn)
    if not p:
        return None
    return f"urn:nir:{p[0]}:{_slug(p[1])}:{p[2]};{p[3]}"


def annual_key(urn: str) -> tuple[str, str, str, str] | None:
    """(emettitore, tipo normalizzato, anno, numero).

    Il numero è unico per tipo e anno, quindi la coppia anno+numero identifica
    l'atto anche quando la data citata è quella di pubblicazione in GU.
    """
    p = parse_urn(urn)
    if not p:
        return None
    return (p[0], _slug(p[1]), p[2][:4], p[3])


class IndiceUrn(dict):
    """Indice ``urn -> valore`` con alias, che ricorda gli URN **esatti**.

    Distinguere le chiavi esatte da quelle alias serve a `regola`: una chiave
    canonica inserita da `expand_index` può coincidere con un URN citato in
    forma AKN, ma non è un URN esatto del corpus.
    """

    esatti: frozenset[str]

    def __init__(self, *args, esatti: Iterable[str] = (), **kwargs):
        super().__init__(*args, **kwargs)
        self.esatti = frozenset(esatti)


def expand_index(pairs: Iterable[tuple[str, str]]) -> IndiceUrn:
    """Aggiunge a una mappa ``urn -> valore`` le chiavi alias risolte.

    Args:
        pairs: coppie ``(urn, valore)`` (valore = path o filename).

    Returns:
        `IndiceUrn` con, oltre agli URN esatti, le chiavi ``canonical_key``,
        ``annual_key`` (tupla) e ``ALIAS_CODICI`` che risultano univoche.

    Tie-break: per una chiave con più espressioni **vince l'ultima coppia in
    ordine di input** (come il `dict(zip(...))` che questo sostituisce), così
    l'attribuzione degli edge resta quella di prima e il delta è additivo.
    """
    index = IndiceUrn()
    canonici: dict[str, list[str]] = defaultdict(list)
    annuali: dict[tuple, list[tuple[str, str]]] = defaultdict(list)
    esatti: list[str] = []

    for urn, valore in pairs:
        if not urn or valore is None:
            continue
        index[urn] = valore  # ultimo vince (compat col comportamento precedente)
        esatti.append(urn)
        ck = canonical_key(urn)
        if ck:
            canonici[ck].append(valore)
        ak = annual_key(urn)
        if ak:
            annuali[ak].append((urn, valore))

    index.esatti = frozenset(esatti)

    for ck, valori in canonici.items():
        if ck not in index and len(set(valori)) == 1:
            index[ck] = valori[-1]

    for ak, coppie in annuali.items():
        if ak in index:
            continue
        # un solo atto dietro la chiave: le sue espressioni (ORIGINALE/VIGENZA)
        # condividono lo slug canonico
        if len({canonical_key(u) for u, _ in coppie}) == 1:
            index[ak] = coppie[-1][1]

    for sorgente, destinazione in ALIAS_CODICI.items():
        if sorgente not in index and destinazione in index:
            index[sorgente] = index[destinazione]

    return index


def add_urn(index: dict, urn: str, valore: str) -> None:
    """Aggiunge una singola coppia all'indice (path incrementale del fetch).

    A differenza di `expand_index` **non** aggiunge il fallback anno+numero:
    su una coppia sola i guard di univocità sarebbero vacui e la chiave
    potrebbe risolvere un atto diverso. Il fallback resta quindi al batch.
    """
    if not urn or valore is None:
        return
    index[urn] = valore
    esatti = getattr(index, "esatti", None)
    if esatti is not None:
        index.esatti = esatti | {urn}
    ck = canonical_key(urn)
    if ck and ck not in index:
        index[ck] = valore
    for sorgente, destinazione in ALIAS_CODICI.items():
        if destinazione == urn and sorgente not in index:
            index[sorgente] = valore


def lookup(index: dict, urn: str) -> str | None:
    """Risolve un URN con la catena di alias definita da `expand_index`.

    I consumer devono usare questa funzione (non `index.get(urn)`): il fallback
    anno+numero è indicizzato con una chiave tupla, quindi non è raggiungibile
    da una lookup su stringa.
    """
    if not isinstance(urn, str) or not urn:
        return None
    for chiave in (urn, canonical_key(urn), annual_key(urn)):
        if chiave is None:
            continue
        valore = index.get(chiave)
        if valore is not None:
            return valore
    return None


# Regole di risoluzione, in ordine di applicazione (per diagnostica e invarianti).
REGOLE = ("codice", "esatto", "slug", "annuale")


def regola(index: dict, urn: str) -> str | None:
    """Nome della regola che risolve `urn`, oppure None.

    `esatto` richiede che l'URN sia **davvero** un URN del corpus: le chiavi
    canoniche inserite da `expand_index` possono coincidere con una citazione
    AKN senza esserlo (per quelle la regola è `slug`).
    """
    if not isinstance(urn, str) or not urn:
        return None
    if urn in ALIAS_CODICI and urn in index:
        return "codice"
    esatti = getattr(index, "esatti", None)
    if urn in (esatti if esatti is not None else index):
        return "esatto"
    if canonical_key(urn) in index:
        return "slug"
    if annual_key(urn) in index:
        return "annuale"
    return None
