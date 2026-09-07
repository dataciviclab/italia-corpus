"""Fetch giornaliero da Normattiva — download AKN XML -> conversione -> salva .md.

Uso: python -m lab_tools.fetch_normattiva [--only COLLEZIONE1,COLLEZIONE2]
"""

from __future__ import annotations

import argparse
import logging
import random
import shutil
import tempfile
import time
from pathlib import Path

from lab_tools.akn_parser import akn_xml_to_markdown
from lab_tools.normattiva_client import (
    download_collection,
    extract_zip,
    fetch_predefined_collections,
    filter_collections,
    merge_collections_by_name,
)

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent
CONFIG_COLLEZIONI = REPO / "config" / "collezioni.txt"


def _load_collezioni() -> list[str]:
    """Legge config/collezioni.txt e restituisce i nomi delle collezioni."""
    if not CONFIG_COLLEZIONI.exists():
        return []
    return [line.strip() for line in CONFIG_COLLEZIONI.read_text().splitlines() if line.strip()]


def _build_urn_index(corpus_dir: Path) -> dict[str, str]:
    """Scansiona il corpus esistente e costruisce la mappa URN -> path relativo."""
    urn_index: dict[str, str] = {}
    for md_file in corpus_dir.rglob("*.md"):
        try:
            text = md_file.read_text("utf-8", errors="replace")[:4096]
        except OSError:
            continue
        if not text.startswith("---"):
            continue
        end = text.find("---", 3)
        if end < 0:
            continue
        block = text[3:end]
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("urn:"):
                urn_value = stripped.split(":", 1)[1].strip()
                rel = md_file.relative_to(corpus_dir)
                urn_index[urn_value] = str(rel)
                break
    logger.info("URN index: %d entries from existing corpus", len(urn_index))
    return urn_index


def _update_urn_index(urn_index: dict[str, str], md_dir: Path, corpus_dir: Path) -> None:
    """Aggiorna l'indice URN con i nuovi file appena scritti."""
    for md_file in md_dir.rglob("*.md"):
        try:
            text = md_file.read_text("utf-8", errors="replace")[:4096]
        except OSError:
            continue
        if not text.startswith("---"):
            continue
        end = text.find("---", 3)
        if end < 0:
            continue
        block = text[3:end]
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("urn:"):
                urn_value = stripped.split(":", 1)[1].strip()
                rel = md_file.relative_to(corpus_dir)
                urn_index[urn_value] = str(rel)
                break


def _collection_subdir(nome: str) -> str:
    """Converte il nome API in nome cartella (spazi, no trattini)."""
    return nome.strip()


def process_collection(
    collection: dict,
    work_dir: Path,
    corpus_dir: Path,
    urn_index: dict[str, str],
) -> int:
    """Scarica, parse, e salva i .md di una collezione. Restituisce il conteggio."""
    nome = collection["nomeCollezione"]
    subdir = _collection_subdir(nome)
    dest_dir = corpus_dir / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Download
    zip_path = download_collection(collection, work_dir)
    if zip_path is None:
        return 0

    # Extract
    extract_dir = work_dir / f"extract_{subdir.replace(' ', '_')}"
    extract_dir.mkdir(exist_ok=True)
    try:
        xml_files = extract_zip(zip_path, extract_dir)
        zip_path.unlink(missing_ok=True)

        if not xml_files:
            logger.warning("No XML files in %r, skipping", nome)
            return 0

        # Convert
        count = 0
        for xml_file in xml_files:
            try:
                content = xml_file.read_text("utf-8", errors="replace")
                source_path = f"{subdir}/{xml_file.stem}.md"
                fm, markdown = akn_xml_to_markdown(content, urn_index, source_path)

                # Filename: same as XML stem but .md
                md_filename = xml_file.stem + ".md"
                md_path = dest_dir / md_filename
                md_path.write_text(markdown, encoding="utf-8")

                # Update live URN index
                if fm.urn:
                    urn_index[fm.urn] = str(md_path.relative_to(corpus_dir))

                count += 1
            except Exception as e:
                logger.warning("Failed to convert %s: %s", xml_file.name, e)

        logger.info("Converted %d/%d files for %r", count, len(xml_files), nome)
        return count

    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Normattiva vigenti")
    parser.add_argument(
        "--only", type=str, default=None,
        help="Solo queste collezioni (separate da virgola)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Scarica e converti ma non sovrascrivere il corpus",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s [%(name)s] %(message)s",
    )

    only_names = args.only.split(",") if args.only else None

    # 1. Fetch collections list
    raw = fetch_predefined_collections()
    all_collections = merge_collections_by_name(raw)

    # 2. Filter: solo le nostre + solo vigenti
    our_names = _load_collezioni()
    if only_names:
        our_names = [n for n in our_names if n in only_names]

    collections = filter_collections(all_collections, only_names=our_names)
    logger.info(
        "Processing %d collections (%d total from API)",
        len(collections), len(all_collections),
    )

    # 3. Build URN index from existing corpus
    urn_index = _build_urn_index(REPO)

    # 4. Process each collection
    total = 0
    with tempfile.TemporaryDirectory(prefix="normattiva-") as tmp:
        work_dir = Path(tmp)
        for i, collection in enumerate(collections):
            nome = collection["nomeCollezione"]
            logger.info("[%d/%d] %s", i + 1, len(collections), nome)

            if args.dry_run:
                zip_path = download_collection(collection, work_dir)
                if zip_path:
                    extract_dir = work_dir / f"check_{i}"
                    extract_dir.mkdir(exist_ok=True)
                    xml_files = extract_zip(zip_path, extract_dir)
                    logger.info("  -> %d XML files (dry run, not saving)", len(xml_files))
                    zip_path.unlink(missing_ok=True)
                    shutil.rmtree(extract_dir, ignore_errors=True)
                continue

            count = process_collection(collection, work_dir, REPO, urn_index)
            total += count

            # Random sleep between collections (avoid rate limiting)
            if i < len(collections) - 1:
                time.sleep(random.uniform(1.0, 3.0))

    logger.info("DONE — %d atti convertiti in totale", total)


if __name__ == "__main__":
    main()
