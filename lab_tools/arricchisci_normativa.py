"""Arricchisce normativa.parquet con segnali di qualità calcolati dal grafo.

Legge normativa.parquet + riferimenti.parquet e aggiunge:
- n_citazioni: conteggio citazioni in ingresso (dal grafo)
- orfano: nessuna citazione in uscita né in ingresso
- qualita_score: punteggio composito 0-100 (più alto = migliore)

Da eseguire DOPO grafo_riferimenti.

Uso: python -m lab_tools.arricchisci_normativa
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTDIR = REPO / "data" / "derived"
NORMATIVA_PARQUET = OUTDIR / "normativa.parquet"
RIFERIMENTI_PARQUET = OUTDIR / "riferimenti.parquet"


def _calcola_score(row: dict) -> int:
    """Calcola qualita_score 0-100 per un atto.

    Regole:
    - Base: 100
    - Duplicato: -40
    - Stato non vigente: -30
    - Orfano con sostanza (>500 parole): -25
    - Orfano senza sostanza: -10
    - Pre-1980 mai citato: -15
    """
    score = 100

    if row.get("duplicato"):
        score -= 40

    if row.get("stato") != "vigente":
        score -= 30

    orfano = row.get("orfano", False)
    if orfano:
        if row.get("lunghezza_parole", 0) > 500:
            score -= 25
        else:
            score -= 10

    if (
        row.get("anno_atto", 0) < 1980
        and row.get("n_citazioni", 0) == 0
        and row.get("stato") == "vigente"
    ):
        score -= 15

    return max(0, score)


def _conta_citazioni_per_atto(df_norm, df_rif):
    """`n_citazioni` per **atto** (`urn`), assegnato alla riga corrente.

    Le citazioni sono contate per `bersaglio_filename`: con più espressioni per
    atto possono cadere su una riga non corrente. Il totale dell'atto va sulla
    riga corrente (le altre restano 0), così `Σ n_citazioni` = archi risolti —
    invariante verificata qui sotto.
    """
    import pandas as pd

    rif = df_rif[df_rif["risolto"] == True]  # noqa: E712
    incoming = rif.groupby("bersaglio_filename").size()

    df = df_norm.copy()
    df["_cit_filename"] = df["filename"].map(incoming).fillna(0).astype(int)

    urn = (
        df["urn"].fillna("").astype(str)
        if "urn" in df.columns
        else pd.Series([""] * len(df), index=df.index)
    )
    corrente = (
        df["is_current"].fillna(False).astype(bool)
        if "is_current" in df.columns
        else pd.Series([True] * len(df), index=df.index)
    )

    tot_per_urn = df.groupby(urn)["_cit_filename"].sum()
    df["n_citazioni"] = 0
    con_urn = urn != ""
    riga_corrente = con_urn & corrente
    df.loc[riga_corrente, "n_citazioni"] = (
        urn[riga_corrente].map(tot_per_urn).fillna(0).astype(int)
    )
    # righe senza URN (oggi 0): il conteggio del filename è già per atto
    df.loc[~con_urn, "n_citazioni"] = df.loc[~con_urn, "_cit_filename"]

    df = df.drop(columns=["_cit_filename"])

    # Invariante: cambia l'attribuzione, non il totale.
    attesi = int(rif.shape[0])
    totale = int(df["n_citazioni"].sum())
    if totale != attesi:
        raise ValueError(
            f"invariante: Σ n_citazioni={totale} != archi risolti={attesi} — "
            "il conteggio per atto deve conservare la somma (per-filename, non "
            "per-atto, perderebbe le citazioni su espressioni non correnti)"
        )

    return df


def main() -> None:
    try:
        import pandas as pd
    except ImportError:
        raise SystemExit("Errore: pandas necessario.")

    if not NORMATIVA_PARQUET.exists():
        raise SystemExit(f"Errore: {NORMATIVA_PARQUET} non trovato. Esegui prima extract.")
    if not RIFERIMENTI_PARQUET.exists():
        raise SystemExit(f"Errore: {RIFERIMENTI_PARQUET} non trovato. Esegui prima grafo_riferimenti.")

    df_norm = pd.read_parquet(NORMATIVA_PARQUET)
    df_rif = pd.read_parquet(RIFERIMENTI_PARQUET)

    print(f"normativa: {len(df_norm)} atti")
    print(f"riferimenti: {len(df_rif)} archi")

    # Conta citazioni in ingresso per atto (urn), non per filename
    df = _conta_citazioni_per_atto(df_norm, df_rif)

    # Orfano: 0 citazioni in uscita (riferimenti_interni) AND 0 in ingresso
    df["orfano"] = (df["riferimenti_interni"] == 0) & (df["n_citazioni"] == 0)

    # Score
    df["qualita_score"] = df.apply(lambda r: _calcola_score(r.to_dict()), axis=1)

    # Salva
    df.to_parquet(NORMATIVA_PARQUET, index=False)
    print(f"\nArricchito: {NORMATIVA_PARQUET}")
    print(f"  Colonne: {list(df.columns)}")

    # Metriche
    print("\n📊 Metriche qualità")
    print(f"{'='*40}")
    print(f"  Con citazioni:     {(df['n_citazioni'] > 0).sum():>8,}")
    print(f"  Orfani:            {df['orfano'].sum():>8,}")
    print(f"  Duplicati:         {df.get('duplicato', pd.Series()).sum() if 'duplicato' in df.columns else 'N/A':>8}")
    print(f"  Score medio:       {df['qualita_score'].mean():>8.1f}")
    print(f"  Score < 50:        {(df['qualita_score'] < 50).sum():>8,}")
    print(f"  Score = 100:       {(df['qualita_score'] == 100).sum():>8,}")


if __name__ == "__main__":
    main()
