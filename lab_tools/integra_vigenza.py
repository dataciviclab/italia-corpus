"""Ricalcola `stato` dallo **status autorevole** Normattiva + dalla nota ufficiale.

`stato` è un metadato ufficiale, non un'euristica sul testo. Due segnali, in
cascata (poi propagati a **tutte** le snapshot dell'atto via join):

  1. **lista ufficiale degli abrogati** — `status.parquet` (vedi
     `fetch_status.py`), da `POST /ricerca/avanzata` con filtro
     `classeProvvedimento=3` (coincide con la collezione ufficiale "Atti
     normativi abrogati"). Match → `abrogato`, `vigenza_fonte='normattiva'`.
     NB: la classe 2 ("aggiornato") NON è "vigente" → non usata.
  2. **nota whole-act** `PROVVEDIMENTO ABROGATO` nel testo (markup ufficiale
     Normattiva, già in `stato` da `extract`): copre le abrogazioni assenti
     dalla lista (es. D.Lgs 220/1995) → `abrogato`, `vigenza_fonte='non_coperto'`.
  3. altrimenti → `vigente`, `vigenza_fonte='esclusione'`.

Join e regole:
  1. join `normativa` ↔ `status` su **(codice_redazionale, data GU)** — il
     filename del corpus porta la data GU (`<dataGU>_<codice>_…`);
     `(codice, anno, numero)` NON è univoco (atti diversi condividono
     codice/anno/numero, es. GU diverse);
  2. il join è **atto-level**: ORIGINALE e VIGENZA della stessa legge
     condividono `(codice, data_gu)` → stesso `stato` (fix #67: le snapshot
     ORIGINALE non portano la nota e resterebbero `vigente`);
  3. fallback su **codice** (se univoco in status) per GU discordanti;
  4. collezione **'DL decaduti'** → `decaduto`.

`vigenza_fonte` = `normattiva` | `non_coperto` | `esclusione`.

**Rimosso**: override dagli eventi AKN (article-level → falsi positivi, es.
Codice Civile). La nota whole-act resta (è markup ufficiale, non euristica).

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
FONTE_NON_COPERTO = "non_coperto"
FONTE_ESCLUSIONE = "esclusione"

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


_PRIO_STATO = {"decaduto": 0, "abrogato": 1, "vigente": 2}


def _propaga_atto(df, stato, fonte):
    """Propaga `stato`/`fonte` a tutte le snapshot della stessa chiave atto.

    L'atto è identificato da `_k` (codice+GU): ORIGINALE e VIGENZA della stessa
    legge condividono la chiave. Prende lo stato più forte (decaduto > abrogato
    > vigente) e ne propaga stato+fonte a tutte le righe (fix #67: le snapshot
    ORIGINALE non portano la nota e resterebbero `vigente`). Pura.
    """
    import pandas as pd

    tmp = pd.DataFrame(
        {
            "_k": df["_k"],
            "_s": stato,
            "_f": fonte,
            "_p": stato.map(_PRIO_STATO),
        }
    )
    best = (
        tmp.sort_values("_p").drop_duplicates("_k", keep="first").set_index("_k")
    )
    return df["_k"].map(best["_s"]), df["_k"].map(best["_f"])


def apply_status(normativa, status):
    """Applica lo status autorevole. Pura (no I/O).

    `normativa`: DataFrame con `codice_redazionale`, `filename`, `collezione`,
    `stato`, `vigente`.
    `status`: DataFrame con `codice_redazionale`, `data_gu`, `stato` —
    contiene **solo gli abrogati** (classe 3 = lista ufficiale).

    `stato` per riga:
      1. match su **(codice_redazionale, data_gu)** → `status.stato`
         (`fonte='normattiva'`);
      2. fallback match su **codice_redazionale** (se univoco in status) →
         `status.stato` (`fonte='normattiva'`);
      3. non coperto ma con **tombstone whole-act** (`abrogato`/`decaduto`
         nello stato pregresso) → **invariato** (`fonte='non_coperto'`) — NON
         forzare `vigente` (regressione: l'archivio non classifica tutti gli atti);
      4. non coperto senza tombstone → `vigente` (`fonte='esclusione'`).

    Poi: collezione **'DL decaduti'** → `decaduto`.
    """
    df = normativa.copy()
    import pandas as pd

    # data GU dal filename del corpus (`<dataGU>_<codice>_…`)
    gu_norm = df["filename"].astype("string").str.slice(0, 10)
    df["_k"] = _chiave(df["codice_redazionale"], gu_norm)

    st = status[["codice_redazionale", "data_gu", "stato"]].copy()
    st["_k"] = _chiave(st["codice_redazionale"], st["data_gu"])
    # tie-break deterministico per le chiavi duplicate residue: preferisci
    # 'abrogato' — non dipendere dall'ordine della risposta API.
    st["_prio"] = st["stato"].map({"abrogato": 0, "vigente": 1}).fillna(2)
    st = st.sort_values("_prio").drop_duplicates("_k", keep="first")
    # fallback per codice: solo se il codice ha UNA sola riga in status
    cod_size = st.groupby("codice_redazionale")["_k"].transform("size")
    st_cod = (
        st[cod_size == 1][["codice_redazionale", "stato"]]
        .rename(columns={"stato": "_st_cod"})
    )
    st = st[["_k", "stato"]].rename(columns={"stato": "_st"})

    df = df.merge(st, on="_k", how="left")
    df = df.merge(st_cod, on="codice_redazionale", how="left")

    matched = df["_st"].notna() | df["_st_cod"].notna()
    tomb = df["stato"].astype("string").str.strip().str.lower()

    nuovo = df["_st"].where(df["_st"].notna(), df["_st_cod"])
    # 3. non coperto ma con tombstone whole-act → invariato
    nonmatch_tomb = ~matched & tomb.isin(["abrogato", "decaduto"])
    nuovo = nuovo.where(~nonmatch_tomb, tomb)
    # 4. non coperto senza tombstone → vigente (per esclusione)
    nuovo = nuovo.where(matched | nonmatch_tomb, "vigente")

    # collezione 'DL decaduti' → decaduto
    decaduto = df["collezione"].astype("string").str.contains(
        COLLEZIONE_DECADUTI, na=False
    )
    nuovo = nuovo.where(~decaduto, "decaduto")

    fonte = pd.Series(FONTE_ESCLUSIONE, index=df.index, dtype=object)
    fonte[nonmatch_tomb] = FONTE_NON_COPERTO
    fonte[matched] = FONTE_NORMATTIVA

    # propagazione atto-level (ORIGINALE e VIGENZA condividono `_k`) → fix #67
    nuovo, fonte = _propaga_atto(df, nuovo, fonte)

    df["stato"] = nuovo
    df["vigente"] = nuovo == "vigente"
    df["vigenza_fonte"] = fonte

    return df.drop(columns=["_k", "_st", "_st_cod"])


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

    print(f"normativa: {before} righe")
    print("stato:")
    print(df["stato"].value_counts().to_string())
    print("vigenza_fonte:")
    print(df["vigenza_fonte"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
