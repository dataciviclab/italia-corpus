"""Scarica lo status autorevole (vigente/abrogato) da Normattiva.

Lo status atto-level è un **metadato**: NON va derivato dal testo (tombstone,
eventi AKN). La fonte è `POST /ricerca/avanzata` con filtro `classeProvvedimento`
(tipologia ufficiale IPZS):

    1 = atto normativo – senza aggiornamenti  -> vigente
    2 = atto normativo – aggiornato           -> vigente
    3 = atto normativo – abrogato             -> abrogato

Ritorna **metadati** (nessun testo) → artifact `data/derived/status.parquet`,
chiave `codice_redazionale` (copertura corpus 100%).

Nota: la ricerca **non distingue** `decaduto` (i DL decaduti sono classe 3).
La distinzione è preservata a valle da `integra_vigenza` (collezione
'DL decaduti').

WAF IPZS: pacing obbligatorio (vedi `normattiva_client.RICERCA_PACE_SECONDS`).

Uso:
    python -m lab_tools.fetch_status
    python -m lab_tools.fetch_status --max-pagine 2   # smoke (poche pagine/classe)
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime

from lab_tools._paths import OUTDIR
from lab_tools.normattiva_client import (
    CLASSE_ABROGATO,
    CLASSE_VIGENTE,
    RICERCA_PAGE_SIZE,
    FetchIncompleto,
    itera_atti_per_classe,
)

logger = logging.getLogger(__name__)

OUTPUT = OUTDIR / "status.parquet"

# classeProvvedimento → stato (atto-level)
STATO_PER_CLASSE: dict[str, str] = {"1": "vigente", "2": "vigente", "3": "abrogato"}

_TITOLO_MAX = 300


def build_rows(atti_per_classe: list[tuple[str, list[dict]]]) -> list[dict]:
    """Trasforma gli atti grezzi della ricerca in righe status. Pura (no I/O).

    Args:
        atti_per_classe: lista di (classe, [atto, ...]) dove `atto` è un
            elemento di `listaAtti` della ricerca avanzata.

    Returns:
        Righe con chiave `codice_redazionale` e `stato`.
    """
    rows: list[dict] = []
    for classe, atti in atti_per_classe:
        stato = STATO_PER_CLASSE.get(str(classe))
        if stato is None:
            logger.warning("classe sconosciuta ignorata: %r", classe)
            continue
        for a in atti:
            cod = a.get("codiceRedazionale")
            if not cod:
                continue
            rows.append(
                {
                    "codice_redazionale": cod,
                    "stato": stato,
                    "classe": str(classe),
                    "denominazione": a.get("denominazioneAtto"),
                    "anno": a.get("annoProvvedimento"),
                    "numero": a.get("numeroProvvedimento"),
                    "data_gu": a.get("dataGU"),
                    "titolo": (a.get("titoloAtto") or "")[:_TITOLO_MAX],
                }
            )
    return rows


def _fetch_all(page_size: int, max_pagine: int | None) -> list[tuple[str, list[dict]]]:
    """Scarica tutte le classi (paginazione + pacing nel client).

    Con `max_pagine=None` (fetch completo) `strict=True`: un errore o un
    conteggio incompleto solleva `FetchIncompleto` e NON si scrive un file
    parziale.
    """
    strict = max_pagine is None
    out: list[tuple[str, list[dict]]] = []
    for classe in (*CLASSE_VIGENTE, CLASSE_ABROGATO):
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
        raise SystemExit("pandas necessario.")

    parser = argparse.ArgumentParser(description="Fetch status da Normattiva")
    parser.add_argument("--page-size", type=int, default=RICERCA_PAGE_SIZE)
    parser.add_argument(
        "--max-pagine", type=int, default=None,
        help="Limita le pagine per classe (smoke test).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    try:
        atti_per_classe = _fetch_all(args.page_size, args.max_pagine)
    except FetchIncompleto as e:
        raise SystemExit(
            f"Fetch INCOMPLETO — status.parquet NON scritto (per non pubblicare "
            f"dati parziali): {e}"
        )
    rows = build_rows(atti_per_classe)
    if not rows:
        raise SystemExit("Nessun atto scaricato — status.parquet non scritto.")

    df = pd.DataFrame(rows)
    # vintage: quando lo status è stato effettivamente scaricato (per dichiarare
    # la freschezza a valle; in CI può essere stale se il WAF ha bloccato il fetch)
    df["fetched_at"] = datetime.now().isoformat(timespec="seconds")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUTPUT, index=False)

    print(f"status: {len(df)} atti -> {OUTPUT}")
    print(df["stato"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
