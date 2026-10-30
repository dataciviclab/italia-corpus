"""Scarica gli allegati AKN senza toccare il corpus (#94).

Uso: `python -m lab_tools.fetch_allegati [--only COLLEZIONE1,COLLEZIONE2]`

Legge l'espressione **disponibile** (anche `O`) e scrive `allegati/` +
`allegati.parquet`. Non modifica `collezioni/`: nessuno swap, nessun downgrade.
Serve a sbloccare i codici, oggi pinnati `V` ma esposti solo come `O`.
"""

from __future__ import annotations

import argparse
import logging
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from lab_tools._paths import OUTDIR, load_collezioni
from lab_tools.akn_parser import extract_frontmatter
from lab_tools.allegati import aggiorna_indice, scrivi_atto
from lab_tools.fetch_normattiva import _read_xml
from lab_tools.identity import data_codice, versione_da_filename
from lab_tools.normattiva_client import (
    download_collection,
    extract_zip,
    fetch_predefined_collections,
    filter_collections,
    merge_collections_by_name,
)

ALLEGATI_DIR = OUTDIR / "allegati"
ALLEGATI_PARQUET = OUTDIR / "allegati.parquet"

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Allegati AKN (read-only)")
    parser.add_argument(
        "--only",
        default=None,
        help="Solo queste collezioni (separate da virgola)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    nomi = load_collezioni()
    if args.only:
        richieste = {n.strip() for n in args.only.split(",") if n.strip()}
        nomi = [n for n in nomi if n in richieste]

    colls = filter_collections(
        merge_collections_by_name(fetch_predefined_collections()), only_names=nomi
    )

    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="allegati-") as tmp:
        work = Path(tmp)
        for collection in colls:
            nome = collection["nomeCollezione"]
            zip_path = download_collection(collection, work)
            if zip_path is None:
                logger.warning("%s: download fallito", nome)
                continue
            files = extract_zip(zip_path, work / nome.replace(" ", "_"))
            n_atti = 0
            for xml_file in files:
                try:
                    content = _read_xml(xml_file)
                    fm = extract_frontmatter(ET.fromstring(content))
                except Exception as exc:  # noqa: BLE001 — un atto non blocca gli altri
                    logger.warning("%s: %s", xml_file.name, exc)
                    continue
                versione, snapshot = versione_da_filename(xml_file.name)
                righe = scrivi_atto(
                    content,
                    fm.urn or "",
                    data_codice(xml_file.stem) or xml_file.stem,
                    versione,
                    snapshot,
                    ALLEGATI_DIR,
                )
                if righe:
                    n_atti += 1
                    rows.extend(righe)
            logger.info("%s: %d atti con allegati", nome, n_atti)

    if rows:
        totale = aggiorna_indice(rows, ALLEGATI_PARQUET)
        logger.info("allegati: %d doc -> %s", totale, ALLEGATI_PARQUET)
    else:
        logger.warning("nessun allegato trovato")


if __name__ == "__main__":
    main()
