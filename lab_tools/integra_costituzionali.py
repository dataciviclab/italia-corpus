"""Integra citazioni costituzionali e abrogazioni in normativa.parquet.

Aggiunge:
- n_articoli_cost: numero di articoli costituzionali citati dall'atto
- articoli_cost: lista articoli costituzionali citati (stringa separata da virgola)
- abrogato_da: se l'atto è menzionato come abrogato in abrogations_raw

Da eseguire DOPO classifica_tematich.

Uso: python -m lab_tools.integra_costituzionali
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTDIR = REPO / "data" / "derived"
NORMATIVA_PARQUET = OUTDIR / "normativa.parquet"
COSTITUZIONALI_PARQUET = OUTDIR / "citazioni-costituzionali.parquet"
ABROGATIONS_PARQUET = OUTDIR / "abrogations_raw.parquet"


def main() -> None:
    try:
        import pandas as pd
    except ImportError:
        raise SystemExit("Errore: pandas necessario.")

    if not NORMATIVA_PARQUET.exists():
        raise SystemExit(f"Errore: {NORMATIVA_PARQUET} non trovato.")

    df = pd.read_parquet(NORMATIVA_PARQUET)
    print(f"normativa: {len(df)} atti")

    # Rimuovi colonne già presenti (da run precedenti)
    for col in ["n_articoli_cost", "articoli_cost", "abrogato_da", "n_abrogazioni"]:
        if col in df.columns:
            df = df.drop(columns=[col])

    # ── 1. Citazioni costituzionali ──
    if COSTITUZIONALI_PARQUET.exists():
        df_cost = pd.read_parquet(COSTITUZIONALI_PARQUET)
        print(f"citazioni costituzionali: {len(df_cost)} righe")

        # Normalizza filename: usa solo basename (senza path di collezione)
        df_cost["filename"] = df_cost["fonte_filename"].apply(
            lambda x: x.split("/")[-1] if "/" in str(x) else str(x)
        )

        # Raggruppa per filename
        cost_by_file = df_cost.groupby("filename").agg(
            n_articoli_cost=("articolo", "count"),
            articoli_cost=("articolo", lambda x: ",".join(str(a) for a in sorted(set(x)))),
        ).reset_index()

        df = df.merge(cost_by_file, on="filename", how="left")
        df["n_articoli_cost"] = df["n_articoli_cost"].fillna(0).astype(int)
        df["articoli_cost"] = df["articoli_cost"].fillna("")
        print(f"  Atti con citazioni costituzionali: {(df['n_articoli_cost'] > 0).sum()}")
    else:
        print(f"  {COSTITUZIONALI_PARQUET} non trovato, skip.")
        df["n_articoli_cost"] = 0
        df["articoli_cost"] = ""

    # ── 2. Abrogazioni ──
    if ABROGATIONS_PARQUET.exists():
        df_abro = pd.read_parquet(ABROGATIONS_PARQUET)
        print(f"abrogazioni: {len(df_abro)} righe")

        # Le abrogazioni referenziano abrogated_year + abrogated_number
        # Join su anno_atto + numero per identificare atti abrogati
        df_abro["abrogato_key"] = df_abro["abrogated_year"].astype(str) + "-" + df_abro["abrogated_number"].astype(str)
        abro_keys = df_abro.groupby("abrogato_key").agg(
            abrogato_da=("abrogating_file", lambda x: "; ".join(set(x))),
            n_abrogazioni=("abrogating_file", "count"),
        ).reset_index()

        df["abrogato_key"] = df["anno_atto"].astype(str) + "-" + df["numero"].astype(str)
        df = df.merge(abro_keys, on="abrogato_key", how="left")
        df["abrogato_da"] = df["abrogato_da"].fillna("")
        df["n_abrogazioni"] = df["n_abrogazioni"].fillna(0).astype(int)
        df = df.drop(columns=["abrogato_key"])

        print(f"  Atti con abrogazioni estratte: {(df['n_abrogazioni'] > 0).sum()}")
    else:
        print(f"  {ABROGATIONS_PARQUET} non trovato, skip.")
        df["abrogato_da"] = ""
        df["n_abrogazioni"] = 0

    # Salva
    df.to_parquet(NORMATIVA_PARQUET, index=False)
    print(f"\nArricchito: {NORMATIVA_PARQUET}")
    print(f"  Colonne: {len(df.columns)}")

    # Metriche
    print(f"\n📊 Metriche integrazione")
    print(f"{'='*40}")
    print(f"  Con citazioni cost.: {(df['n_articoli_cost'] > 0).sum():>8,}")
    print(f"  Con abrogazioni:     {(df['n_abrogazioni'] > 0).sum():>8,}")
    print(f"  Media art. cost.:    {df['n_articoli_cost'].mean():>8.1f}")


if __name__ == "__main__":
    main()
