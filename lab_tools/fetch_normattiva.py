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

from lab_tools._paths import (
    COLLEZIONI_DIRNAME,
    COLLEZIONI_ROOT,
    CONFIG_COLLEZIONI,
    OUTDIR,
    REPO,
)
from lab_tools.akn_parser import akn_xml_to_markdown
from lab_tools.akn_relations import (
    extract_from_xml,
    load_staged_akn,
    merge_akn_artifacts,
    stage_akn_rows,
)
from lab_tools.normattiva_client import (
    download_collection,
    extract_zip,
    fetch_predefined_collections,
    filter_collections,
    merge_collections_by_name,
)

logger = logging.getLogger(__name__)


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
    stage_dir: Path | None = None,
) -> int:
    """Scarica, parse, e salva i .md di una collezione. Restituisce il conteggio.

    Ordine: scarica → estrai → converti in staging → swap atomico.
    Se download fallisce o non produce XML, i file esistenti restano intatti.
    Se stage_dir è fornito, salva relazioni/metadati AKN in JSONL per collezione.
    """
    nome = collection["nomeCollezione"]
    subdir = _collection_subdir(nome)
    dest_dir = corpus_dir / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 1. Download PRIMA di cancellare qualsiasi cosa
    zip_path = download_collection(collection, work_dir)
    if zip_path is None:
        logger.warning("Download failed for %r — keeping existing files", nome)
        return 0

    # 2. Extract
    extract_dir = work_dir / f"extract_{subdir.replace(' ', '_')}"
    extract_dir.mkdir(exist_ok=True)
    staging_dir = work_dir / f"staging_{subdir.replace(' ', '_')}"
    staging_dir.mkdir(exist_ok=True)

    try:
        xml_files = extract_zip(zip_path, extract_dir)
        zip_path.unlink(missing_ok=True)

        if not xml_files:
            logger.warning("No XML files in %r — keeping existing files", nome)
            return 0

        # 3. Converti in staging (i .md esistenti restano intatti finché non swap)
        count = 0
        rel_rows: list[dict] = []
        meta_rows: list[dict] = []
        for xml_file in xml_files:
            try:
                content = xml_file.read_text("utf-8", errors="replace")
                source_path = f"{COLLEZIONI_DIRNAME}/{subdir}/{xml_file.stem}.md"
                fm, markdown = akn_xml_to_markdown(content, urn_index, source_path)

                if stage_dir is not None:
                    try:
                        relations, meta = extract_from_xml(content)
                        rel_rows.extend(relations)
                        if meta and meta.get("fonte_urn"):
                            meta["fonte_file"] = f"{subdir}/{xml_file.name}"
                            meta_rows.append(meta)
                    except Exception as exc:  # noqa: BLE001 — non bloccare il fetch MD
                        logger.warning("AKN relations failed for %s: %s", xml_file.name, exc)

                md_filename = xml_file.stem + ".md"
                md_path = staging_dir / md_filename
                md_path.write_text(markdown, encoding="utf-8")

                # Update live URN index (punta alla destinazione finale)
                if fm.urn:
                    urn_index[fm.urn] = f"{COLLEZIONI_DIRNAME}/{subdir}/{md_filename}"

                count += 1
            except Exception as e:
                logger.warning("Failed to convert %s: %s", xml_file.name, e)

        if stage_dir is not None and (rel_rows or meta_rows):
            stage_akn_rows(rel_rows, meta_rows, stage_dir, nome)
            logger.info("  AKN staged: %d relations, %d acts", len(rel_rows), len(meta_rows))

        if count == 0:
            logger.warning("All conversions failed for %r — keeping existing files", nome)
            return 0

        # 4. Swap atomico: cancella i vecchi .md, sposta i nuovi da staging
        for old_file in dest_dir.glob("*.md"):
            old_file.unlink()

        for new_file in staging_dir.glob("*.md"):
            shutil.move(str(new_file), str(dest_dir / new_file.name))

        logger.info("Converted %d/%d files for %r", count, len(xml_files), nome)
        return count

    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)
        shutil.rmtree(staging_dir, ignore_errors=True)


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

    # 3b. Staging AKN su disco (sopravvive a errori di merge a fine run)
    stage_dir = OUTDIR / "_akn_stage"
    if stage_dir.exists():
        shutil.rmtree(stage_dir, ignore_errors=True)
    stage_dir.mkdir(parents=True, exist_ok=True)

    # 4. Process each collection
    total = 0
    failed: list[str] = []
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
                else:
                    failed.append(nome)
                continue

            count = process_collection(collection, work_dir, COLLEZIONI_ROOT, urn_index, stage_dir=stage_dir)
            total += count
            if count == 0:
                failed.append(nome)

            # Random sleep between collections (avoid rate limiting)
            if i < len(collections) - 1:
                time.sleep(random.uniform(1.0, 3.0))

        # 4b. Seconda passata sulle collection fallite (API flaky)
        if failed:
            logger.warning("Retry pass per collection fallite: %s", ", ".join(failed))
            still_failed: list[str] = []
            for nome in failed:
                collection = next((c for c in collections if c["nomeCollezione"] == nome), None)
                if collection is None:
                    still_failed.append(nome)
                    continue
                time.sleep(random.uniform(2.0, 5.0))
                count = process_collection(
                    collection, work_dir, COLLEZIONI_ROOT, urn_index, stage_dir=stage_dir
                )
                total += count
                if count == 0:
                    still_failed.append(nome)
                else:
                    logger.info("Retry OK per %r (%d file)", nome, count)
            failed = still_failed

    # 5. Carica staging + merge artifact AKN
    rel_rows, meta_rows = load_staged_akn(stage_dir)
    if rel_rows or meta_rows:
        try:
            rel_path, meta_path = merge_akn_artifacts(
                rel_rows, meta_rows, OUTDIR
            )
            logger.info(
                "AKN artifacts (merged): %d relations -> %s; %d acts -> %s",
                len(rel_rows), rel_path,
                len(meta_rows), meta_path,
            )
        except ImportError:
            logger.warning("pandas/pyarrow non disponibili — artifact AKN non scritti")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Scrittura artifact AKN fallita: %s", exc)
    else:
        logger.warning("Nessun dato AKN in staging — artifact non aggiornati")

    logger.info("DONE — %d atti convertiti in totale", total)

    if failed:
        n_ok = len(collections) - len(failed)
        # Soft-fail: se la maggioranza è arrivata, il corpus aggiornato vale
        # comunque (le collection fallite restano con i file preesistenti).
        if n_ok >= max(1, int(len(collections) * 0.8)):
            logger.error(
                "FAILED collections soft (%d/%d): %s — procedo comunque "
                "(file preesistenti conservati)",
                len(failed), len(collections), ", ".join(failed),
            )
            return
        logger.error(
            "FAILED collections (%d/%d): %s",
            len(failed), len(collections), ", ".join(failed),
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
