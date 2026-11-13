"""Canonicalizza gli URN di `akn_relations` (#142).

Le forme AKN (`codice.civile`, `regiodecreto`,
`decretodelpresidentedellarepubblica`, …) non matchano i nodi canonici del
corpus: i consumer che fanno join esatto sull'URN (legal-graph) scartano
quegli edge. Qui si mappano con l'indice di `urn.expand_index` — la stessa
catena di `grafo_riferimenti`: codice → esatto → slug → annuale.

Output: riscrittura di `data/derived/akn_relations.parquet` (dedup sulla chiave
dopo la mappatura).

Uso: python -m lab_tools.akn_canonicalizza
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable

from lab_tools._paths import OUTDIR
from lab_tools.urn import IndiceUrn, canonical_key, expand_index, lookup, regola

logger = logging.getLogger(__name__)

NORMATIVA_PARQUET = OUTDIR / "normativa.parquet"
AKN_PARQUET = OUTDIR / "akn_relations.parquet"
# Il grano è quello del clean (`edge_id` include `detail`): due articoli
# diversi dello stesso atto sono due righe, non un duplicato.
REL_KEY = ["fonte_urn", "target_urn", "rel_type", "origin", "detail"]


def canonical_index(urns: Iterable[str]) -> IndiceUrn:
    """Indice che mappa ogni forma (esatta/alias/slug/annuale) all'URN canonico."""
    puliti = sorted({str(u).strip() for u in urns if str(u or "").strip()})
    return expand_index((u, u) for u in puliti)


def canonicalizza_urns(df, index: IndiceUrn):
    """Riscrive fonte/target con l'URN canonico. Ritorna (df, per_regola, duplicati).

    `per_regola` conta i valori cambiati per regola (`codice`, `slug`, …);
    `duplicati` sono le righe collassate perché due forme diverse della stessa
    relazione diventano la stessa chiave dopo la mappatura.
    """
    per_regola: Counter[str] = Counter()

    def _map(u: object) -> object:
        if not isinstance(u, str) or not u:
            return u
        canon = lookup(index, u)
        if canon and canon != u:
            per_regola[regola(index, u) or "?"] += 1
            return canon
        return u

    nuovo = df.copy()
    for col in ("fonte_urn", "target_urn"):
        nuovo[col] = nuovo[col].map(_map)
    prima = len(nuovo)
    chiave = [c for c in REL_KEY if c in nuovo.columns]
    nuovo = nuovo.drop_duplicates(subset=chiave, keep="last")
    return nuovo, per_regola, prima - len(nuovo)


def _slug(u: object) -> object:
    """Chiave normalizzata dell'URN (None per le forme non NIR: UE, ecc.)."""
    if not isinstance(u, str) or not u:
        return u
    return canonical_key(u) or u


def _lista_union(valori) -> str | None:
    """Unione delle liste comma-separated (`art_3,art_47`)."""
    out: set[str] = set()
    for v in valori:
        if isinstance(v, str):
            out.update(x.strip() for x in v.split(",") if x.strip())
    return ",".join(sorted(out)) or None


def _primo_non_vuoto(valori) -> object:
    for v in valori:
        if isinstance(v, str) and v.strip():
            return v
    return None


def dedup_per_slug(df):
    """Una riga per relazione anche quando l'URN arriva in forme diverse.

    Il merge non sostituisce una riga orfana il cui `target_urn` è scritto in
    una forma che il parser non produce più (`decretodelpresidentedellarepubblica`
    vs `decreto.del.presidente.della.repubblica`): le due righe restano e quella
    vecchia non ha `contesto`/`locator` (dato di prima del re-parse). Qui si
    raggruppa sulla chiave normalizzata (`urn.canonical_key`): si tiene la forma
    nuova e si uniscono locator/articolo; `contesto` è il primo non vuoto.
    """
    slug = df.copy()
    slug["_fs"] = slug["fonte_urn"].map(_slug)
    slug["_ts"] = slug["target_urn"].map(_slug)
    chiave = ["_fs", "_ts", "rel_type", "origin"]
    # riga con contesto in coda: `last` sulle identità prende la forma nuova.
    # Una stringa vuota non è contesto: 93.971 righe nel raw hanno `''`.
    if "contesto" in slug.columns:
        slug["_ctx"] = slug["contesto"].fillna("").astype(str).str.strip().ne("")
    else:
        slug["_ctx"] = False
    slug = slug.sort_values("_ctx", kind="stable")

    agg: dict[str, object] = {
        "fonte_urn": "last",
        "fonte_codice": "last",
        "target_urn": "last",
        "detail": "last",
        "contesto": _primo_non_vuoto,
    }
    # `evidenza` viaggia con `contesto`: se la riga vecchia è l'unica ad averla
    # (alias URN), non deve sparire nel collasso.
    if "evidenza" in slug.columns:
        agg["evidenza"] = _primo_non_vuoto
    for col in ("locator", "articolo"):
        if col in slug.columns:
            agg[col] = _lista_union
    for col in slug.columns:
        if col not in agg and not col.startswith("_"):
            agg[col] = "last"

    out = slug.groupby(chiave, as_index=False, dropna=False).agg(agg)
    return out.drop(columns=[c for c in out.columns if c.startswith("_")])


def main() -> None:
    import pandas as pd

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not NORMATIVA_PARQUET.exists():
        raise SystemExit(f"{NORMATIVA_PARQUET} non trovato: esegui prima extract.")
    if not AKN_PARQUET.exists():
        raise SystemExit(f"{AKN_PARQUET} non trovato: esegui prima il fetch AKN.")

    urns = pd.read_parquet(NORMATIVA_PARQUET, columns=["urn"])["urn"].dropna()
    index = canonical_index(urns)
    df = pd.read_parquet(AKN_PARQUET)
    # Retro-compat: i raw precedenti non hanno evidenza/locator/articolo.
    for col in ("evidenza", "locator", "articolo"):
        if col not in df.columns:
            df[col] = None
    nuovo, per_regola, duplicati = canonicalizza_urns(df, index)
    prima_alias = len(nuovo)
    nuovo = dedup_per_slug(nuovo)
    nuovo.to_parquet(AKN_PARQUET, index=False)

    cambiati = sum(per_regola.values())
    print(
        f"akn_relations: {len(df)} righe, {cambiati} URN canonicalizzati, "
        f"{duplicati} duplicati collassati"
    )
    print(
        f"  alias collassati (chiave normalizzata): {prima_alias - len(nuovo)}; "
        f"righe finali {len(nuovo)}"
    )
    print(f"  per regola: {dict(per_regola)}")


if __name__ == "__main__":
    main()
