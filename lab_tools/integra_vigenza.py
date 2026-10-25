"""Ricalcola `stato` dallo **status autorevole** Normattiva.

Lo status atto-level è un **metadato**, non va derivato dal testo. La fonte è
`status.parquet` (vedi `fetch_status.py`), prodotto da `POST /ricerca/avanzata`
con filtro `classeProvvedimento` (tipologia ufficiale IPZS).

Regole:
  1. join `normativa` ↔ `status` su **(codice_redazionale, data GU)** — il
     filename del corpus porta la data GU (`<dataGU>_<codice>_…`);
     `(codice_redazionale, anno, numero)` NON è univoco (atti diversi
     condividono codice/anno/numero, es. GU diverse);
  2. `stato` = `status.stato` (`vigente` | `abrogato`), `vigenza_fonte='normattiva'`;
  3. collezione **'DL decaduti'** → `decaduto` (la ricerca non distingue
     `decaduto`, che è una categoria del corpus);
  4. non coperto da `status` → `stato` invariato, `vigenza_fonte='unknown'`.

**Rimosso**: tombstone (per lo `stato`) e override dagli eventi AKN
(article-level → falsi positivi, es. Codice Civile).

Da eseguire DOPO `extract` e DOPO `fetch_status`, e PRIMA di `grafo`/
`arricchisci` (così `fonte_stato` negli edge e `qualita_score` usano lo stato
corretto).

Uso: python -m lab_tools.integra_vigenza
"""

from __future__ import annotations

from lab_tools._paths import OUTDIR

NORMATIVA = OUTDIR / "normativa.parquet"
STATUS = OUTDIR / "status.parquet"

FONTE_NORMATTIVA = "normattiva"
FONTE_UNKNOWN = "unknown"

# Collezione i cui atti sono "decaduti" (la ricerca li classifica abrogati).
COLLEZIONE_DECADUTI = "DL decaduti"


def _chiave(cod, gu):
    """Chiave atto = codice_redazionale + data GU (stringhe).

    La data GU è il **discriminante**: `(codice, anno, numero)` NON è univoco
    (atti diversi condividono codice/anno/numero). Il filename del corpus porta
    la data GU (`<dataGU>_<codice>_…`), la ricerca il campo `data_gu`.
    """
    return (
        cod.astype("string").fillna("")
        + "|"
        + gu.astype("string").fillna("")
    )


def apply_status(normativa, status):
    """Applica lo status autorevole. Pura (no I/O).

    `normativa`: DataFrame con `codice_redazionale`, `filename`, `collezione`,
    `stato`, `vigente`.
    `status`: DataFrame con `codice_redazionale`, `data_gu`, `stato`.

    Ritorna una copia di `normativa` con `stato`, `vigente`, `vigenza_fonte`.
    """
    df = normativa.copy()
    # data GU dal filename del corpus (`<dataGU>_<codice>_…`)
    gu_norm = df["filename"].astype("string").str.slice(0, 10)
    df["_k"] = _chiave(df["codice_redazionale"], gu_norm)

    st = status[["codice_redazionale", "data_gu", "stato"]].copy()
    st["_k"] = _chiave(st["codice_redazionale"], st["data_gu"])
    # tie-break deterministico per le chiavi duplicate residue (1 caso noto,
    # es. 26G00061): preferisci 'abrogato' (stato terminale) — non dipendere
    # dall'ordine della risposta API.
    st["_prio"] = st["stato"].map({"abrogato": 0, "vigente": 1}).fillna(2)
    st = (
        st.sort_values("_prio")
        .drop_duplicates("_k", keep="first")[["_k", "stato"]]
        .rename(columns={"stato": "_st"})
    )

    df = df.merge(st, on="_k", how="left")
    matched = df["_st"].notna()

    # 1. stato di base: status autorevole, fallback al valore pregresso
    nuovo = df["stato"].astype("string").str.strip().str.lower()
    nuovo = nuovo.where(~matched, df["_st"])

    # 2. decaduto: collezione dedicata (la ricerca non lo distingue)
    decaduto = df["collezione"].astype("string").str.contains(
        COLLEZIONE_DECADUTI, na=False
    )
    nuovo = nuovo.where(~decaduto, "decaduto")

    df["stato"] = nuovo
    df["vigente"] = nuovo == "vigente"
    df["vigenza_fonte"] = FONTE_UNKNOWN
    df.loc[matched, "vigenza_fonte"] = FONTE_NORMATTIVA

    return df.drop(columns=["_k", "_st"])


def main() -> int:
    try:
        import pandas as pd
    except ImportError:
        raise SystemExit("pandas necessario.")

    if not NORMATIVA.exists():
        raise SystemExit("normativa.parquet mancante — esegui prima extract.")
    if not STATUS.exists():
        raise SystemExit(
            "status.parquet mancante — esegui prima fetch_status "
            "(python -m lab_tools.fetch_status)."
        )

    df = pd.read_parquet(NORMATIVA)
    status = pd.read_parquet(STATUS)
    before = len(df)

    df = apply_status(df, status)
    df.to_parquet(NORMATIVA, index=False)

    n_unknown = int((df["vigenza_fonte"] == FONTE_UNKNOWN).sum())
    print(f"normativa: {before} righe")
    print("stato:")
    print(df["stato"].value_counts().to_string())
    print("vigenza_fonte:")
    print(df["vigenza_fonte"].value_counts().to_string())
    print(f"non coperti da status (unknown): {n_unknown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
