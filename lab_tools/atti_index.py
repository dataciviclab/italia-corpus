"""Indice del catalogo Normattiva: `atti_index.parquet`.

Il corpus (`normativa.parquet`) copre solo gli atti delle collezioni che
fetchiamo: ~20,8k su un catalogo di ~205k atti. Le relazioni AKN però citano
atti che non abbiamo — e senza un indice non sappiamo dire **quali mancano**
né agganciare le citazioni a un'identità.

Questo stage enumera il catalogo ufficiale via `POST /ricerca/avanzata`
(metadati, **nessun testo**) per le tre classiProvvedimento e produce:

    codice_redazionale, data_gu, classe, stato, denominazione, anno, numero,
    data_emanazione, ..., in_corpus, corpus_urn, corpus_filename,
    urn, urn_fonte, fetched_at

Identità e join:

- la chiave dell'atto è **(codice_redazionale, data_gu)**: il codice
  redazionale è riciclato (stesso codice per atti diversi in anni diversi,
  vedi docs/PIPELINE.md), quindi il solo codice non basta;
- `in_corpus` si risolve sul prefisso stabile del filename
  (`AAAA-MM-GG_CODICE`, via `identity.data_codice`) — nessun fuzzy match;
- un atto può comparire in **più classiProvvedimento** (aggiornato e poi
  abrogato): resta una riga sola, con la classe 3 (lista ufficiale abrogati),
  come fa `integra_vigenza`;
- `tipo_slug`/`emittente` e `urn` si **apprendono** dal corpus
  (`denominazioneAtto` → tipo/emittente). Regola: valore modale con quota ≥95%
  e almeno 10 osservazioni; sotto quella soglia il tipo vale solo se coincide
  con la traslitterazione della denominazione (`DECRETO-LEGGE` →
  `decreto.legge`) e l'emittente solo se è strutturale (`stato`). La URN si
  costruisce solo con tipo **e** emittente noti (altrimenti `urn_fonte = NULL`):
  un emittente indovinato produrrebbe una URN plausibile e sbagliata, peggio
  di nessuna URN.

`stato`: `abrogato` = classe 3 (lista ufficiale abrogati) · `non_abrogato` =
classe 1/2, cioè **assente** da quella lista — non è una prova di vigenza
(stessa semantica di `vigenza_fonte='esclusione'` a valle).

L'output non va in git (rigenerato e soggetto a drift, come `status.parquet`):
viene pubblicato dal layer toolkit (`datasets/atti-index/`) e consumato da
legal-graph.

Uso:
    python -m lab_tools.atti_index
    python -m lab_tools.atti_index --max-pagine 1   # smoke (poche pagine/classe)
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime

from lab_tools._paths import OUTDIR
from lab_tools.identity import data_codice
from lab_tools.normattiva_client import (
    CLASSE_ABROGATO,
    CLASSE_VIGENTE,
    RICERCA_PAGE_SIZE,
    FetchIncompleto,
    itera_atti_per_classe,
)
from lab_tools.urn import parse_urn

logger = logging.getLogger(__name__)

OUTPUT = OUTDIR / "atti_index.parquet"

CLASSI = (*CLASSE_VIGENTE, CLASSE_ABROGATO)  # ("1", "2", "3")
STATO_PER_CLASSE = {CLASSE_ABROGATO: "abrogato"}
STATO_DEFAULT = "non_abrogato"
_TITOLO_MAX = 300
_NUMERO_RE = re.compile(r"^\d+$")


def build_rows(atti_per_classe: list[tuple[str, list[dict]]]) -> list[dict]:
    """Righe dell'indice dagli atti grezzi della ricerca (pura, no I/O).

    Salta gli atti senza `codiceRedazionale` o `dataGU`: senza la coppia non
    c'è identità e la riga sarebbe indistinguibile da un duplicato.
    """
    rows: list[dict] = []
    for classe, atti in atti_per_classe:
        classe = str(classe)
        for a in atti:
            codice = (a.get("codiceRedazionale") or "").strip()
            data_gu = (a.get("dataGU") or "").strip()
            if not codice or not data_gu:
                continue
            anno = a.get("annoProvvedimento")
            rows.append(
                {
                    "codice_redazionale": codice,
                    "data_gu": data_gu,
                    "classe": classe,
                    "stato": STATO_PER_CLASSE.get(classe, STATO_DEFAULT),
                    "denominazione": (a.get("denominazioneAtto") or "").strip() or None,
                    "anno": int(anno) if str(anno or "").isdigit() else None,
                    "numero": (a.get("numeroProvvedimento") or "").strip() or None,
                    "data_emanazione": (a.get("dataEmanazione") or "")[:10] or None,
                    "numero_gu": (a.get("numeroGU") or "").strip() or None,
                    "titolo": (a.get("titoloAtto") or "").strip()[:_TITOLO_MAX] or None,
                    "descrizione": (a.get("descrizioneAtto") or "").strip() or None,
                }
            )
    return rows


# Un atto può comparire in più classiProvvedimento (es. un DL aggiornato e poi
# abrogato → classe 2 e classe 3). La classe 3 è la lista ufficiale abrogati:
# vince, perché è lo stesso criterio di `integra_vigenza`.
PRECEDENZA_CLASSE = {CLASSE_ABROGATO: 3, "2": 2, "1": 1}


def deduplica(righe: list[dict]) -> tuple[list[dict], int]:
    """Una riga per `(codice_redazionale, data_gu)`, con la classe più forte.

    Returns:
        (righe deduplicate nell'ordine di prima apparizione, n righe scartate).
    """
    scelte: dict[tuple[str, str], dict] = {}
    scartate = 0
    for r in righe:
        chiave = (r["codice_redazionale"], r["data_gu"])
        attuale = scelte.get(chiave)
        if attuale is None:
            scelte[chiave] = r
            continue
        scartate += 1
        if PRECEDENZA_CLASSE.get(r["classe"], 0) > PRECEDENZA_CLASSE.get(attuale["classe"], 0):
            scelte[chiave] = r
    return list(scelte.values()), scartate


def indice_corpus(corpus_rows: list[dict]) -> dict[tuple[str, str], dict]:
    """`(codice_redazionale, data_gu) -> {urn, filename}` dal corpus.

    `corpus_rows` sono le righe di `normativa.parquet` (almeno `filename`,
    `urn`). La data GU è il prefisso del filename: è la stessa convenzione su
    cui `integra_vigenza` fa il join con lo status.
    """
    out: dict[tuple[str, str], dict] = {}
    for r in corpus_rows:
        filename = r.get("filename") or ""
        cod = data_codice(filename)
        if not cod:
            continue
        data_gu, codice = cod.split("_", 1)
        out.setdefault(
            (codice, data_gu),
            {"urn": r.get("urn"), "filename": filename},
        )
    return out


SHARE_MINIMA = 0.95
OSSERVAZIONI_MINIME = 10
# Emittenti "strutturali": gli atti dello Stato non hanno un ministero
# competente, quindi valgono anche con poche osservazioni (regi decreti e
# luogotenenziali sono pochi nel corpus). Per gli altri emittenti la regola
# resta: ≥OSSERVAZIONI_MINIME osservazioni (un solo decreto di un ministero
# non deve etichettare 2.540 decreti).
EMITTENTI_STRUTTURALI = frozenset({"stato"})


def _slug_denominazione(denominazione: str) -> str:
    """`DECRETO-LEGGE` → `decreto.legge` (traslitterazione dello slug NIR)."""
    return re.sub(r"[^a-z0-9]+", ".", (denominazione or "").strip().lower()).strip(".")


def _maggioranza(conteggi: dict[str, int]) -> tuple[str, int, int] | None:
    """(valore modale, occorrenze, totale) oppure None se il dict è vuoto."""
    if not conteggi:
        return None
    valore, n = max(conteggi.items(), key=lambda kv: kv[1])
    return valore, n, sum(conteggi.values())


def _tipo_accettato(
    conteggi_tipo: dict[str, int],
    denominazione: str,
    share_minima: float = SHARE_MINIMA,
    osservazioni_minime: int = OSSERVAZIONI_MINIME,
) -> str | None:
    """Tipo modale: quota ≥95% e (≥10 osservazioni **o** slug coerente col nome).

    La seconda condizione recupera le denominazioni rare (es. `DECRETO
    LUOGOTENENZIALE`, 6 atti nel corpus) senza aprire a un'etichetta arbitraria:
    il tipo osservato deve coincidere con la traslitterazione della
    denominazione.
    """
    m = _maggioranza(conteggi_tipo)
    if m is None:
        return None
    valore, n, totale = m
    if n / totale < share_minima:
        return None
    if totale >= osservazioni_minime:
        return valore
    return valore if valore == _slug_denominazione(denominazione) else None


def _emittente_accettato(
    conteggi_emit: dict[str, int],
    share_minima: float = SHARE_MINIMA,
    osservazioni_minime: int = OSSERVAZIONI_MINIME,
) -> str | None:
    """Emittente modale: ≥95% e (≥10 osservazioni **o** emittente strutturale)."""
    m = _maggioranza(conteggi_emit)
    if m is None:
        return None
    valore, n, totale = m
    if n / totale < share_minima:
        return None
    if totale >= osservazioni_minime or valore in EMITTENTI_STRUTTURALI:
        return valore
    return None


def _mappa_urn(
    righe: list[dict],
    share_minima: float = SHARE_MINIMA,
    osservazioni_minime: int = OSSERVAZIONI_MINIME,
) -> tuple[dict[str, str], dict[tuple[str, str], str], set[str]]:
    """Apprende `denominazione -> tipo` e `(denominazione, tipo) -> emittente`.

    Returns:
        (tipi, emittenti, denominazioni ambigue) — ambigua = tipo non
        determinabile con la regola di maggioranza.
    """
    visti: dict[str, dict[tuple[str, str], int]] = {}
    for r in righe:
        den = r.get("denominazione")
        urn = r.get("corpus_urn")
        if not den or not urn:
            continue
        p = parse_urn(urn)
        if not p:
            continue
        per_tipo = visti.setdefault(den, {})
        per_tipo[(p[0], p[1])] = per_tipo.get((p[0], p[1]), 0) + 1

    tipi: dict[str, str] = {}
    emittenti: dict[tuple[str, str], str] = {}
    ambigue: set[str] = set()
    for den, coppie in visti.items():
        conteggi_tipo: dict[str, int] = {}
        for (_emit, tipo), n in coppie.items():
            conteggi_tipo[tipo] = conteggi_tipo.get(tipo, 0) + n
        tipo = _tipo_accettato(conteggi_tipo, den, share_minima, osservazioni_minime)
        if tipo is None:
            ambigue.add(den)
            continue
        tipi[den] = tipo
        emittenti_qui: dict[str, int] = {}
        for (emit, t), n in coppie.items():
            if t == tipo:
                emittenti_qui[emit] = emittenti_qui.get(emit, 0) + n
        emit = _emittente_accettato(emittenti_qui, share_minima, osservazioni_minime)
        if emit:
            emittenti[(den, tipo)] = emit
    return tipi, emittenti, ambigue


def collega_corpus(
    righe: list[dict],
    indice: dict[tuple[str, str], dict],
    *,
    share_minima: float = SHARE_MINIMA,
    osservazioni_minime: int = OSSERVAZIONI_MINIME,
) -> dict:
    """Aggiunge identità e appartenenza al corpus alle righe del catalogo.

    Colonne aggiunte (in place): `in_corpus`, `corpus_urn`, `corpus_filename`,
    `tipo_slug`, `emittente`, `urn`, `urn_fonte`.

    Returns:
        Riepilogo: conteggi per `urn_fonte`, tipi noti, denominazioni ambigue.
    """
    for r in righe:
        hit = indice.get((r["codice_redazionale"], r["data_gu"]))
        r["in_corpus"] = hit is not None
        r["corpus_urn"] = hit["urn"] if hit else None
        r["corpus_filename"] = hit["filename"] if hit else None

    tipi, emittenti, ambigue = _mappa_urn(righe, share_minima, osservazioni_minime)

    apprese = assenti = tipo_noto = 0
    for r in righe:
        den = r.get("denominazione") or ""
        tipo = tipi.get(den)
        emit = emittenti.get((den, tipo)) if tipo else None
        r["tipo_slug"] = tipo
        r["emittente"] = emit
        if tipo:
            tipo_noto += 1

        if r["corpus_urn"]:
            r["urn"] = r["corpus_urn"]
            r["urn_fonte"] = "corpus"
            continue
        numero = r.get("numero") or ""
        if tipo and emit and r.get("data_emanazione") and _NUMERO_RE.match(numero):
            r["urn"] = f"urn:nir:{emit}:{tipo}:{r['data_emanazione']};{numero}"
            r["urn_fonte"] = "appresa"
            apprese += 1
        else:
            r["urn"] = None
            r["urn_fonte"] = None
            assenti += 1

    return {
        "urn_corpus": sum(1 for r in righe if r["urn_fonte"] == "corpus"),
        "urn_appresa": apprese,
        "urn_assente": assenti,
        "tipo_noto": tipo_noto,
        "denominazioni_ambigue": sorted(ambigue),
    }


def riepilogo(righe: list[dict]) -> dict:
    """Numeri del gap: totale, in corpus, per decade e per denominazione."""
    totale = len(righe)
    in_corpus = sum(1 for r in righe if r.get("in_corpus"))
    decadi: dict[int, list[int]] = {}
    tipi: dict[str, list[int]] = {}
    for r in righe:
        anno = r.get("anno") or 0
        dec = (anno // 10) * 10 if anno else 0
        d = decadi.setdefault(dec, [0, 0])
        d[0] += 1
        d[1] += 1 if r.get("in_corpus") else 0
        den = r.get("denominazione") or "?"
        t = tipi.setdefault(den, [0, 0])
        t[0] += 1
        t[1] += 1 if r.get("in_corpus") else 0
    return {"totale": totale, "in_corpus": in_corpus, "decadi": decadi, "tipi": tipi}


def _stampa_riepilogo(rep: dict, ident: dict) -> None:
    totale, in_corpus = rep["totale"], rep["in_corpus"]
    pct = 100.0 * in_corpus / totale if totale else 0.0
    print(f"catalogo: {totale} atti · in corpus {in_corpus} ({pct:.1f}%) · mancanti {totale - in_corpus}")
    print(
        f"tipo appreso: {ident['tipo_noto']} · urn: corpus {ident['urn_corpus']} · "
        f"appresa {ident['urn_appresa']} · assente {ident['urn_assente']}"
    )
    if ident["denominazioni_ambigue"]:
        amb = ", ".join(ident["denominazioni_ambigue"][:6])
        print(f"denominazioni ambigue (urn non costruita): {len(ident['denominazioni_ambigue'])} — {amb}")
    print("\nmancanti per decade:")
    for dec in sorted(rep["decadi"]):
        tot, inside = rep["decadi"][dec]
        print(f"  {dec}s  mancanti {tot - inside:>6}  su {tot:>6}  ({100.0 * inside / tot:.1f}% in corpus)")
    print("\nprime 12 denominazioni per atti mancanti:")
    top = sorted(rep["tipi"].items(), key=lambda kv: -(kv[1][0] - kv[1][1]))[:12]
    for den, (tot, inside) in top:
        print(f"  {den[:42]:42s} mancanti {tot - inside:>6}  su {tot:>6}")


def _fetch(page_size: int, max_pagine: int | None) -> list[tuple[str, list[dict]]]:
    strict = max_pagine is None
    out: list[tuple[str, list[dict]]] = []
    for classe in CLASSI:
        atti = list(
            itera_atti_per_classe(
                classe,
                page_size=page_size,
                max_pagine=max_pagine,
                strict=strict,
            )
        )
        logger.info("classe %s: %d atti", classe, len(atti))
        out.append((classe, atti))
    return out


def main() -> int:
    try:
        import pandas as pd
    except ImportError:
        raise SystemExit("pandas necessario (extra dev).")

    parser = argparse.ArgumentParser(description="Indice del catalogo Normattiva")
    parser.add_argument("--page-size", type=int, default=RICERCA_PAGE_SIZE)
    parser.add_argument("--max-pagine", type=int, default=None, help="Limita le pagine per classe (smoke).")
    parser.add_argument("--corpus", default=None, help="normativa.parquet (default: data/derived)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        atti_per_classe = _fetch(args.page_size, args.max_pagine)
    except FetchIncompleto as e:
        raise SystemExit(
            "Fetch INCOMPLETO — atti_index NON scritto (per non pubblicare un "
            f"catalogo parziale come se fosse completo): {e}"
        )

    righe = build_rows(atti_per_classe)
    if not righe:
        raise SystemExit("Nessun atto scaricato — atti_index non scritto.")
    righe, n_dedup = deduplica(righe)
    if n_dedup:
        logger.info("dedup catalogo: %d righe doppie (stesso codice+data in più classi)", n_dedup)

    corpus_path = args.corpus
    if corpus_path is None:
        corpus_path = str(OUTDIR / "normativa.parquet")
    corpus = pd.read_parquet(corpus_path, columns=["filename", "urn"])
    indice = indice_corpus(corpus.to_dict("records"))

    ident = collega_corpus(righe, indice)
    rep = riepilogo(righe)

    df = pd.DataFrame(righe)
    df["fetched_at"] = datetime.now().isoformat(timespec="seconds")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUTPUT, index=False)

    _stampa_riepilogo(rep, ident)
    print(f"\natti_index: {len(df)} atti -> {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
