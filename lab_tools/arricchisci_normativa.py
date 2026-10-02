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


def main() -> None:
    try:
        import pandas as pd
    except ImportError:
        print("Errore: pandas necessario.")
        return

    if not NORMATIVA_PARQUET.exists():
        print(f"Errore: {NORMATIVA_PARQUET} non trovato. Esegui prima extract.")
        return
    if not RIFERIMENTI_PARQUET.exists():
        print(f"Errore: {RIFERIMENTI_PARQUET} non trovato. Esegui prima grafo_riferimenti.")
        return

    df_norm = pd.read_parquet(NORMATIVA_PARQUET)
    df_rif = pd.read_parquet(RIFERIMENTI_PARQUET)

    print(f"normativa: {len(df_norm)} atti")
    print(f"riferimenti: {len(df_rif)} archi")

    # Conta citazioni in ingresso (solo archi risolti)
    df_rif_res = df_rif[df_rif["risolto"] == True]  # noqa: E712
    incoming = df_rif_res.groupby("bersaglio_filename").size().reset_index(name="n_citazioni")
    incoming = incoming.rename(columns={"bersaglio_filename": "filename"})

    # Merge
    df = df_norm.merge(incoming, on="filename", how="left")
    df["n_citazioni"] = df["n_citazioni"].fillna(0).astype(int)

    # Orfano: 0 citazioni in uscita (riferimenti_interni) AND 0 in ingresso
    df["orfano"] = (df["riferimenti_interni"] == 0) & (df["n_citazioni"] == 0)

    # Score
    df["qualita_score"] = df.apply(lambda r: _calcola_score(r.to_dict()), axis=1)

    # Salva
    df.to_parquet(NORMATIVA_PARQUET, index=False)
    print(f"\nArricchito: {NORMATIVA_PARQUET}")
    print(f"  Colonne: {list(df.columns)}")

    # Metriche
    print(f"\n📊 Metriche qualità")
    print(f"{'='*40}")
    print(f"  Con citazioni:     {(df['n_citazioni'] > 0).sum():>8,}")
    print(f"  Orfani:            {df['orfano'].sum():>8,}")
    print(f"  Duplicati:         {df.get('duplicato', pd.Series()).sum() if 'duplicato' in df.columns else 'N/A':>8}")
    print(f"  Score medio:       {df['qualita_score'].mean():>8.1f}")
    print(f"  Score < 50:        {(df['qualita_score'] < 50).sum():>8,}")
    print(f"  Score = 100:       {(df['qualita_score'] == 100).sum():>8,}")


if __name__ == "__main__":
    main()
