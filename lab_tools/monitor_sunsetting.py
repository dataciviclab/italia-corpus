"""Monitor sunsetting: identifica candidati alla decadenza automatica.

Calcola metriche di sunsetting per ogni atto vigente:
- eta_anni: anni dall'atto
- ultimo_riferimento: anno dell'ultima citazione in ingresso
- anni_senza_citazioni: anni dall'ultima citazione
- sunsetting_score: 0-100 (più alto = più candidato alla decadenza)

Aggiunge colonne a normativa.parquet.

Da eseguire DOPO integra_costituzionali.

Uso: python -m lab_tools.monitor_sunsetting
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTDIR = REPO / "data" / "derived"
NORMATIVA_PARQUET = OUTDIR / "normativa.parquet"
RIFERIMENTI_PARQUET = OUTDIR / "riferimenti.parquet"

ANNO_CORRENTE = datetime.now().year


def _calcola_sunsetting_score(row: dict) -> int:
    """Calcola sunsetting_score 0-100 (più alto = più candidato).

    Regole:
    - Base: 0
    - Pre-1980 mai citati: +40
    - Pre-1980 poco citati (1-3): +25
    - 1980-2000 mai citati: +20
    - DL proroghe con >20 anni: +30
    - Orfano: +15
    - Score qualità basso (<50): +10
    - Testi Unici / Codici: -20 (strutturali, non si toccano)
    """
    score = 0

    eta = ANNO_CORRENTE - row.get("anno_atto", 0)
    n_cit = row.get("n_citazioni", 0)
    orfano = row.get("orfano", False)
    collezione = row.get("collezione", "")
    qualita = row.get("qualita_score", 100)

    # Fascia età + citazioni
    if row.get("anno_atto", 0) < 1980:
        if n_cit == 0:
            score += 40
        elif n_cit <= 3:
            score += 25
    elif row.get("anno_atto", 0) < 2000:
        if n_cit == 0:
            score += 20

    # DL proroghe vecchie
    if "DL proroghe" in collezione and eta > 20:
        score += 30

    # Orfano
    if orfano:
        score += 15

    # Qualità bassa
    if qualita < 50:
        score += 10

    # Strutturali: non si toccano
    if "Testi Unici" in collezione or "Codici" in collezione:
        score -= 20

    return max(0, min(100, score))


def main() -> None:
    try:
        import pandas as pd
    except ImportError:
        raise SystemExit("Errore: pandas necessario.")

    if not NORMATIVA_PARQUET.exists():
        raise SystemExit(f"Errore: {NORMATIVA_PARQUET} non trovato.")
    if not RIFERIMENTI_PARQUET.exists():
        raise SystemExit(f"Errore: {RIFERIMENTI_PARQUET} non trovato.")

    df = pd.read_parquet(NORMATIVA_PARQUET)
    df_rif = pd.read_parquet(RIFERIMENTI_PARQUET)
    print(f"normativa: {len(df)} atti")

    # Rimuovi colonne da run precedenti
    for col in ["eta_anni", "anni_senza_citazioni", "sunsetting_score"]:
        if col in df.columns:
            df = df.drop(columns=[col])

    # Calcola ultimo riferimento in ingresso
    df_rif_res = df_rif[df_rif["risolto"] == True]  # noqa: E712
    ultimo_ref = df_rif_res.groupby("bersaglio_filename")["fonte_anno"].max().reset_index()
    ultimo_ref.columns = ["filename", "ultimo_riferimento"]
    df = df.merge(ultimo_ref, on="filename", how="left")

    # Calcola metriche
    df["eta_anni"] = ANNO_CORRENTE - df["anno_atto"]
    df["anni_senza_citazioni"] = df["ultimo_riferimento"].apply(
        lambda x: ANNO_CORRENTE - x if pd.notna(x) and x > 0 else None
    )
    df["sunsetting_score"] = df.apply(lambda r: _calcola_sunsetting_score(r.to_dict()), axis=1)

    # Salva
    df.to_parquet(NORMATIVA_PARQUET, index=False)
    print(f"Arricchito: {NORMATIVA_PARQUET}")
    print(f"  Colonne: {len(df.columns)}")

    # Metriche
    print(f"\n📊 Metriche sunsetting")
    print(f"{'='*40}")
    print(f"  Score medio:              {df['sunsetting_score'].mean():>8.1f}")
    print(f"  Score > 50 (candidati):   {(df['sunsetting_score'] > 50).sum():>8,}")
    print(f"  Score > 70 (forti):       {(df['sunsetting_score'] > 70).sum():>8,}")
    print(f"  DL proroghe >20 anni:     {((df['collezione'].str.contains('DL proroghe')) & (df['eta_anni'] > 20)).sum():>8,}")
    print(f"  Vigenti pre-1980 no-cit:  {((df['stato']=='vigente') & (df['anno_atto']<1980) & (df['n_citazioni']==0)).sum():>8,}")


if __name__ == "__main__":
    main()
