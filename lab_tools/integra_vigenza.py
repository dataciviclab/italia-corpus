"""Ricalcola `stato` dai segnali di abrogazione del corpus e dichiara la fonte.

Il campo `stato` nasce dal tombstone nel markdown (`PROVVEDIMENTO ABROGATO` /
`DECRETO DECADUTO`, vedi extract.py). Funziona solo sugli snapshot VIGENZA
(testo consolidato): gli snapshot ORIGINALE non portano tombstone e restano
marcati "vigente" anche se l'atto è abrogato (issue #67, D.Lgs 50/2016).

Precedenza applicata a `stato` (solo fonti autorevoli):
  1. tombstone "decaduto" o "abrogato"           -> invariato (fonte=vigenza_snapshot)
  2. edge AKN repeal/substitution (target)       -> abrogato   (fonte=akn)
  3. nessuna fonte autorevole:
       - snapshot VIGENZA                        -> stato tombstone (vigenza_snapshot)
       - snapshot ORIGINALE                      -> stato tombstone (unknown)

Il segnale regex `abrogato_da` (n_abrogazioni > 0) è **solo candidato**: la
validazione su campione mostra bassa precisione (abrogazioni article-level,
mismatch di tipo atto, citazioni) e NON modifica `stato`. Viene esposto via
`vigenza_fonte='regex'` per le indagini a valle.

`vigenza_fonte` (colonna additiva, backward-compatible) dichiara l'origine
dello stato:
  - `vigenza_snapshot` : da snapshot VIGENZA (testo consolidato) — sia tombstone
                         esplicito sia assenza di tombstone ("confermato vigente")
  - `akn`              : override da edge AKN repeal/substitution (autorevole)
  - `unknown`          : snapshot ORIGINALE senza segnale autorevole (stato di
                         default, NON verificato)
  - `regex`            : candidato regex presente, `stato` NON modificato

`apply_vigenza` è idempotente: gli URN target AKN sono esclusi dal ramo
tombstone, così rieseguirla sullo stesso parquet non degrada la provenienza
(akn -> vigenza_snapshot).

Dipendenze:
- `akn_relations.parquet` (prodotto dal fetch) per gli edge repeal/substitution.
- `abrogato_da` / `n_abrogazioni` in normativa.parquet (prodotti da
  integra_costituzionali). Se assenti, il candidato regex non è disponibile.

Da eseguire DOPO integra_costituzionali e PRIMA di grafo/arricchisci (così
`fonte_stato` negli edge e `qualita_score` usano lo stato corretto).

Uso: python -m lab_tools.integra_vigenza
"""

from __future__ import annotations

from pathlib import Path

from lab_tools._paths import OUTDIR

NORMATIVA = OUTDIR / "normativa.parquet"
AKN_RELATIONS = OUTDIR / "akn_relations.parquet"

# Relazioni AKN che abrogano/sostituiscono il target (act-level).
AKN_ABROGA_TYPES = ("repeal", "substitution")
_AKN_REQUIRED_COLS = frozenset({"rel_type", "target_urn"})

FONTE_VIGENZA_SNAPSHOT = "vigenza_snapshot"
FONTE_AKN = "akn"
FONTE_REGEX = "regex"
FONTE_UNKNOWN = "unknown"

_RE_VIGENZA = r"_VIGENZA_"


def akn_abrogation_targets(path: Path) -> set[str]:
    """URN degli atti target di edge AKN repeal/substitution.

    Solleva SystemExit con messaggio chiaro se il parquet non ha lo schema
    atteso (rel_type, target_urn) — evita KeyError oscuri a valle.
    """
    import pandas as pd

    if not path.exists():
        return set()
    rel = pd.read_parquet(path)
    missing = _AKN_REQUIRED_COLS - set(rel.columns)
    if missing:
        raise SystemExit(
            f"{path.name}: colonne mancanti {sorted(missing)} "
            f"(attese {sorted(_AKN_REQUIRED_COLS)}). Schema akn_relations cambiato?"
        )
    sel = rel[rel["rel_type"].isin(AKN_ABROGA_TYPES)]
    return set(sel["target_urn"].dropna().astype(str))


def apply_vigenza(df, akn_targets: set[str]):
    """Applica la precedenza delle fonti. Pura: non tocca il disco.

    Ritorna una copia di `df` con `stato`, `vigente` e `vigenza_fonte`
    aggiornati. Idempotente: rieseguirla non degrada `vigenza_fonte`.
    Vedi docstring del modulo per la precedenza.
    """
    import pandas as pd

    df = df.copy()
    stato = df["stato"].astype(str).str.strip().str.lower()
    urn = df["urn"].astype(str)
    if "n_abrogazioni" in df.columns:
        n_abro = pd.to_numeric(df["n_abrogazioni"], errors="coerce").fillna(0)
    else:
        n_abro = pd.Series(0, index=df.index)
    is_vig_snapshot = df["filename"].astype(str).str.contains(_RE_VIGENZA)
    akn_target = urn.isin(akn_targets)

    new_stato = stato.copy()
    fonte = pd.Series(FONTE_UNKNOWN, index=df.index, dtype=object)

    dec = stato == "decaduto"
    gia_abrogato = stato == "abrogato"

    # 1. provenienza vigenza_snapshot: decaduto, o abrogato non-AKN (tombstone
    #    originale). Gli URN target AKN sono esclusi: il loro `abrogato` può
    #    venire da un override precedente, non dal tombstone (idempotenza).
    tomb = (dec | gia_abrogato) & ~akn_target
    fonte[tomb] = FONTE_VIGENZA_SNAPSHOT

    # 2. override AKN (decaduto resta decaduto).
    akn_mask = akn_target & ~dec
    new_stato[akn_mask] = "abrogato"
    fonte[akn_mask] = FONTE_AKN

    # 3. candidato regex: nessun override di stato, solo etichetta.
    regex_mask = (n_abro > 0) & ~dec & ~akn_mask
    fonte[regex_mask] = FONTE_REGEX

    # 4. residui: VIGENZA = snapshot consolidato; ORIGINALE = unknown.
    resid = ~(tomb | akn_mask | regex_mask)
    fonte[resid & is_vig_snapshot] = FONTE_VIGENZA_SNAPSHOT

    df["stato"] = new_stato
    df["vigente"] = new_stato == "vigente"
    df["vigenza_fonte"] = fonte
    return df


def main() -> int:
    try:
        import pandas as pd
    except ImportError:
        raise SystemExit("pandas necessario.")

    if not NORMATIVA.exists():
        raise SystemExit("normativa.parquet mancante — esegui prima extract.")

    df = pd.read_parquet(NORMATIVA)
    before = len(df)

    akn_targets = akn_abrogation_targets(AKN_RELATIONS)
    df = apply_vigenza(df, akn_targets)

    df.to_parquet(NORMATIVA, index=False)

    n_unknown = int((df["vigenza_fonte"] == FONTE_UNKNOWN).sum())
    n_akn = int((df["vigenza_fonte"] == FONTE_AKN).sum())
    n_regex = int((df["vigenza_fonte"] == FONTE_REGEX).sum())
    print(f"normativa: {before} righe")
    print("stato (dopo):")
    print(df["stato"].value_counts().to_string())
    print("vigenza_fonte:")
    print(df["vigenza_fonte"].value_counts().to_string())
    print(f"override -> abrogato via akn: {n_akn}")
    print(f"candidati regex (stato invariato): {n_regex}")
    print(f"unknown (ORIGINALE senza segnale): {n_unknown}")
    if not AKN_RELATIONS.exists():
        print(f"NOTA: {AKN_RELATIONS.name} assente — solo vigenza_snapshot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
