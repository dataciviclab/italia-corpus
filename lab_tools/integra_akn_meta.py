"""Integra akn_act_meta in normativa.parquet (EIV, mod counts, workflow).

Da eseguire DOPO extract (e idealmente dopo fetch che ha scritto akn_act_meta).

Aggiunge colonne (backward-compatible, non sovrascrive grafo regex):
- ingresso_in_vigore: data EIV da authorialNote AKN
- akn_n_refs, akn_n_active_mods, akn_n_passive_ref, akn_n_repeal_events
- akn_mod_types (JSON string), akn_has_workflow
- akn_meta_source: 'akn' se join riuscito

Uso: python -m lab_tools.integra_akn_meta
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTDIR = REPO / "data" / "derived"
NORMATIVA = OUTDIR / "normativa.parquet"
AKN_META = OUTDIR / "akn_act_meta.parquet"

META_COLS = [
    "ingresso_in_vigore",
    "akn_n_refs",
    "akn_n_active_mods",
    "akn_n_passive_ref",
    "akn_n_repeal_events",
    "akn_mod_types",
    "akn_has_workflow",
    "akn_meta_source",
]


def main() -> int:
    try:
        import json

        import pandas as pd
    except ImportError:
        raise SystemExit("pandas/pyarrow necessari.")

    if not NORMATIVA.exists():
        raise SystemExit("normativa.parquet mancante — esegui prima extract.")
    if not AKN_META.exists():
        raise SystemExit(
            "akn_act_meta.parquet mancante — esegui prima fetch "
            "(o python -m lab_tools.akn_relations --xml-dir ...)."
        )

    df = pd.read_parquet(NORMATIVA)
    meta = pd.read_parquet(AKN_META)

    for c in META_COLS:
        if c not in df.columns:
            df[c] = None

    meta = meta.copy()
    if "mod_types_json" in meta.columns:
        meta["mod_types_json"] = meta["mod_types_json"].where(
            meta["mod_types_json"].notna(), None
        )
    elif "mod_types" in meta.columns:
        meta["mod_types_json"] = meta["mod_types"].apply(
            lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, dict) else (
                x if isinstance(x, str) else None
            )
        )
    else:
        meta["mod_types_json"] = None

    keep = meta[
        [
            "fonte_urn",
            "fonte_codice",
            "eiv",
            "n_refs",
            "n_active_mods",
            "n_passive_ref",
            "n_repeal_events",
            "mod_types_json",
            "has_workflow",
        ]
    ].rename(
        columns={
            "fonte_urn": "_urn",
            "fonte_codice": "_codice",
            "eiv": "ingresso_in_vigore",
            "n_refs": "akn_n_refs",
            "n_active_mods": "akn_n_active_mods",
            "n_passive_ref": "akn_n_passive_ref",
            "n_repeal_events": "akn_n_repeal_events",
            "mod_types_json": "akn_mod_types",
            "has_workflow": "akn_has_workflow",
        }
    )
    keep = keep.drop_duplicates(subset=["_urn", "_codice"], keep="last")

    before = len(df)
    # prepara chiavi join
    df["_urn"] = df.get("urn")
    df["_codice"] = df.get("codice_redazionale")

    merged = df.merge(
        keep.drop(columns=["_codice"], errors="ignore"),
        on="_urn",
        how="left",
        suffixes=("", "_akn"),
    )
    # fallback per righe senza urn match ma con codice
    if "_codice" in keep.columns:
        miss = merged["akn_n_refs"].isna() & merged["ingresso_in_vigore"].isna()
        miss &= merged["_codice"].isin(keep["_codice"].dropna())
        if miss.any():
            by_cod = keep.dropna(subset=["_codice"]).drop_duplicates("_codice")
            by_cod = by_cod.drop(columns=["_urn"], errors="ignore")
            fallback = merged.loc[miss, ["_codice"]].merge(
                by_cod, on="_codice", how="left"
            )
            for c in [
                "ingresso_in_vigore",
                "akn_n_refs",
                "akn_n_active_mods",
                "akn_n_passive_ref",
                "akn_n_repeal_events",
                "akn_mod_types",
                "akn_has_workflow",
            ]:
                if c in fallback.columns:
                    merged.loc[miss, c] = fallback[c].values

    joined = merged["ingresso_in_vigore"].notna() | merged["akn_n_refs"].notna()
    merged["akn_meta_source"] = None
    merged.loc[joined, "akn_meta_source"] = "akn"

    merged = merged.drop(columns=["_urn", "_codice"], errors="ignore")
    # evita colonne _x/_y residue da merge
    merged = merged.loc[:, ~merged.columns.str.endswith("_akn")]

    merged.to_parquet(NORMATIVA, index=False)

    n_join = int(joined.sum())
    n_eiv = int(merged["ingresso_in_vigore"].notna().sum())
    print(f"normativa: {before} -> {len(merged)} atti (invariato se join left)")
    print(f"join AKN meta: {n_join}")
    print(f"con ingresso_in_vigore: {n_eiv}")
    print(f"colonne: {list(merged.columns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
