"""Fetch giornaliero da Normattiva — download AKN XML -> conversione -> salva .md.

Uso: python -m lab_tools.fetch_normattiva [--only COLLEZIONE1,COLLEZIONE2]

Ottimizzazione: manifest per collezione — se dataCreazione invariato,
salta download+convert (risparmia ~11 min su giorni senza cambi).
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import random
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path

from lab_tools._paths import (
    COLLEZIONI_DIRNAME,
    COLLEZIONI_ROOT,
    OUTDIR,
    REPO,
    load_collezioni,
    load_pin,
)
from lab_tools.akn_parser import akn_xml_to_markdown, conta_allegati
from lab_tools.akn_relations import (
    extract_from_xml,
    load_staged_akn,
    merge_akn_artifacts,
    stage_akn_rows,
)
from lab_tools.allegati import aggiorna_indice, scrivi_atto
from lab_tools.identity import data_codice, versione_da_filename
from lab_tools.normattiva_client import (
    download_collection,
    extract_zip,
    fetch_predefined_collections,
    filter_collections,
    merge_collections_by_name,
)
from lab_tools.urn import add_urn, expand_index

logger = logging.getLogger(__name__)

MANIFEST_PATH = OUTDIR / "_fetch_manifest.json"
ALLEGATI_REPORT = OUTDIR / "_allegati_report.json"
ALLEGATI_DIR = OUTDIR / "allegati"
ALLEGATI_PARQUET = OUTDIR / "allegati.parquet"


def _load_manifest() -> dict:
    """Carica il manifest delle collezioni fetchate."""
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _load_allegati_report() -> dict:
    """Carica il report allegati precedente (accumulativo tra i fetch).

    Solo le collezioni non skippate vengono aggiornate: senza il merge, ogni
    giorno si vedrebbe solo il sottoinsieme rifetchato e il perimetro non si
    completerebbe.
    """
    if ALLEGATI_REPORT.exists():
        try:
            return json.loads(ALLEGATI_REPORT.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_manifest(manifest: dict) -> None:
    """Salva il manifest delle collezioni fetchate."""
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True))


def _collection_unchanged(collection: dict, manifest: dict) -> bool:
    """Verifica se una collezione è invariata dall'ultimo fetch.

    Usa dataCreazione dalla API come fingerprint: se la data non cambia,
    il contenuto della collezione non è cambiato.
    """
    nome = collection.get("nomeCollezione", "")
    data_creazione = collection.get("dataCreazione", "")
    if not nome or not data_creazione:
        return False
    entry = manifest.get(nome, {})
    return entry.get("dataCreazione") == data_creazione


def _load_collezioni_pin() -> tuple[list[str], dict[str, str]]:
    """Nomi + formato richiesto, dal parser unico in `_paths`."""
    return load_collezioni(), load_pin()


def _load_collezioni() -> list[str]:
    """Nomi delle collezioni da fetchare (senza il pin di formato)."""
    return _load_collezioni_pin()[0]


def _filtra_per_formato(
    collections: list[dict], pin: dict[str, str]
) -> tuple[list[dict], list[tuple[str, str, str]]]:
    """Tiene solo le collezioni col formato richiesto (o senza pin).

    Returns:
        (da_processare, scarti) con scarti = [(nome, richiesto, disponibile)].
    """
    tenute: list[dict] = []
    scarti: list[tuple[str, str, str]] = []
    for c in collections:
        nome = c.get("nomeCollezione", "")
        richiesto = pin.get(nome)
        disponibile = (c.get("formatoCollezione") or "").strip().upper()
        if richiesto and disponibile != richiesto:
            scarti.append((nome, richiesto, disponibile or "?"))
            continue
        tenute.append(c)
    return tenute, scarti


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


def _read_xml(path: Path) -> str:
    """Testo XML, decodificando base64 se serve.

    Alcuni atti grossi arrivano **base64-encoded dentro lo ZIP** (Codice civile,
    attuazione c.c.): il primo byte è `P` (base64 di `<?xml`), non `<`, e la
    conversione falliva con `syntax error: line 1, column 0`. Il payload è XML
    valido una volta decodificato.
    """
    raw = path.read_bytes()
    probe = raw.lstrip()
    if probe.startswith(b"\xef\xbb\xbf"):  # BOM UTF-8
        probe = probe[3:]
    if not probe.startswith(b"<"):
        raw = base64.b64decode(raw)
    return raw.decode("utf-8", errors="replace")


def _file_da_sostituire(old_names: list[str], new_names: list[str]) -> set[str]:
    """Nomi vecchi da cancellare: solo gli atti presenti nella nuova sorgente.

    Se un atto non compare nel nuovo set (conversione fallita, XML malformato),
    il vecchio file **resta**: lo swap non deve cancellare testo buono.
    """
    nuovi = {c for c in (data_codice(n) for n in new_names) if c}
    return {n for n in old_names if data_codice(n) in nuovi}


def process_collection(
    collection: dict,
    work_dir: Path,
    corpus_dir: Path,
    urn_index: dict[str, str],
    stage_dir: Path | None = None,
    report: dict | None = None,
    allegati_rows: list[dict] | None = None,
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
        n_allegati = 0
        chars_allegati = 0
        rel_rows: list[dict] = []
        meta_rows: list[dict] = []
        for xml_file in xml_files:
            try:
                content = _read_xml(xml_file)
                n_doc, chars_doc = conta_allegati(content)
                n_allegati += n_doc
                chars_allegati += chars_doc
                source_path = f"{COLLEZIONI_DIRNAME}/{subdir}/{xml_file.stem}.md"
                fm, markdown = akn_xml_to_markdown(content, urn_index, source_path)

                # Allegati (#94): il testo dei codici sta qui. Un file per atto,
                # indice con provenienza (`versione`/`snapshot_data`) e hash.
                versione, snapshot = versione_da_filename(xml_file.name)
                cod = data_codice(xml_file.stem) or xml_file.stem
                righe_allegati = scrivi_atto(
                    content, fm.urn or "", cod, versione, snapshot, ALLEGATI_DIR, urn_index
                )
                if allegati_rows is not None:
                    allegati_rows.extend(righe_allegati)

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

                # Update live URN index (punta alla destinazione finale).
                # `add_urn`: su una coppia sola il fallback anno+numero avrebbe
                # guard di univocità vacui (vedi lab_tools/urn.py)
                if fm.urn:
                    add_urn(urn_index, fm.urn, f"{COLLEZIONI_DIRNAME}/{subdir}/{md_filename}")

                count += 1
            except Exception as e:
                logger.warning("Failed to convert %s: %s", xml_file.name, e)

        if stage_dir is not None and (rel_rows or meta_rows):
            stage_akn_rows(rel_rows, meta_rows, stage_dir, nome)
            logger.info("  AKN staged: %d relations, %d acts", len(rel_rows), len(meta_rows))

        if count == 0:
            logger.warning("All conversions failed for %r — keeping existing files", nome)
            return 0

        # 4. Swap per atto: sostituisci solo gli atti presenti nella nuova
        # sorgente. Se un atto non ha convertito (XML malformato/base64), il
        # vecchio file resta — non si cancella testo buono (incidente 2026-10-29:
        # Codice civile sparito per un `syntax error`).
        nuovi = [new_file.name for new_file in staging_dir.glob("*.md")]
        vecchi = [old_file.name for old_file in dest_dir.glob("*.md")]
        da_cancellare = _file_da_sostituire(vecchi, nuovi)
        if len(da_cancellare) < len(vecchi):
            logger.warning(
                "  %d file vecchi mantenuti (atti assenti dalla nuova sorgente)",
                len(vecchi) - len(da_cancellare),
            )
        for old_file in dest_dir.glob("*.md"):
            if old_file.name in da_cancellare:
                old_file.unlink()

        for new_file in staging_dir.glob("*.md"):
            shutil.move(str(new_file), str(dest_dir / new_file.name))

        logger.info("Converted %d/%d files for %r", count, len(xml_files), nome)
        # Misura #94: il testo degli allegati oggi non è servito. Counter per
        # collezione, così il perimetro si decide sui numeri, non su 16/40.
        logger.info("  allegati: %d doc, %d char", n_allegati, chars_allegati)
        if report is not None:
            report[nome] = {
                "xml": len(xml_files),
                "doc": n_allegati,
                "chars": chars_allegati,
            }
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
    our_names, pin_config = _load_collezioni_pin()
    if only_names:
        our_names = [n for n in our_names if n in only_names]
        pin_config = {n: f for n, f in pin_config.items() if n in our_names}

    collections = filter_collections(all_collections, only_names=our_names)

    # Pin di formato: config + manifest (il formato con cui la collezione e'
    # stata fetchata l'ultima volta). Se il pin non e' disponibile si salta.
    manifest = _load_manifest()
    pin = dict(pin_config)
    for nome, entry in manifest.items():
        fmt = (entry.get("formato") or "").strip().upper()
        if fmt and nome not in pin:
            pin[nome] = fmt

    presenti_api = {c["nomeCollezione"] for c in collections}
    for nome in our_names:
        if nome in pin and nome not in presenti_api:
            logger.warning(
                "%s: collezione assente dall'API — skip, mantengo i file esistenti",
                nome,
            )

    collections, scarti_formato = _filtra_per_formato(collections, pin)
    for nome, richiesto, disponibile in scarti_formato:
        logger.warning(
            "%s: formato %s non disponibile (API: %s) — skip, mantengo i file esistenti",
            nome,
            richiesto,
            disponibile,
        )
    logger.info(
        "Processing %d collections (%d total from API)",
        len(collections), len(all_collections),
    )

    # 3. Build URN index from existing corpus
    # alias (slug, anno+numero, codici): vedi lab_tools/urn.py
    urn_index = expand_index(_build_urn_index(REPO).items())

    # 3b. Staging AKN su disco (sopravvive a errori di merge a fine run)
    stage_dir = OUTDIR / "_akn_stage"
    if stage_dir.exists():
        shutil.rmtree(stage_dir, ignore_errors=True)
    stage_dir.mkdir(parents=True, exist_ok=True)

    # 4. Process each collection
    total = 0
    failed: list[str] = []
    allegati_rows: list[dict] = []
    ALLEGATI_DIR.mkdir(parents=True, exist_ok=True)
    report_allegati = _load_allegati_report()
    n_skipped = 0
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

            # Manifest check: salta se la collezione non è cambiata
            if _collection_unchanged(collection, manifest):
                n_skipped += 1
                logger.info("  ⏭️  Invariata (dataCreazione=%s) — skip",
                           collection.get("dataCreazione", "?"))
                continue

            count = process_collection(
                collection, work_dir, COLLEZIONI_ROOT, urn_index,
                stage_dir=stage_dir, report=report_allegati,
                allegati_rows=allegati_rows,
            )
            total += count
            if count == 0:
                failed.append(nome)
            else:
                # Aggiorna manifest per collezione processata con successo
                manifest[nome] = {
                    "dataCreazione": collection.get("dataCreazione", ""),
                    "formato": collection.get("formatoCollezione", ""),
                    "last_fetch": datetime.now().isoformat(),
                }
                report_allegati.setdefault(nome, {})["fetched_at"] = manifest[nome][
                    "last_fetch"
                ]

            # Random sleep between collections (avoid rate limiting)
            if i < len(collections) - 1:
                time.sleep(random.uniform(1.0, 3.0))

        if n_skipped > 0:
            logger.info("Manifest: %d collezioni skip, %d processate", n_skipped, len(collections) - n_skipped)

        # Salva manifest sempre (aggiorna anche dopo primo run)
        _save_manifest(manifest)
        if allegati_rows:
            try:
                tot = aggiorna_indice(allegati_rows, ALLEGATI_PARQUET)
                logger.info("allegati: %d doc -> %s", tot, ALLEGATI_PARQUET)
            except ImportError:
                logger.warning("pandas assente: allegati.parquet non scritto")

        if report_allegati:
            ALLEGATI_REPORT.write_text(
                json.dumps(report_allegati, indent=2, sort_keys=True),
                encoding="utf-8",
            )

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
                    collection, work_dir, COLLEZIONI_ROOT, urn_index,
                    stage_dir=stage_dir, report=report_allegati,
                    allegati_rows=allegati_rows,
                )
                total += count
                if count == 0:
                    still_failed.append(nome)
                else:
                    report_allegati.setdefault(nome, {})["fetched_at"] = (
                        datetime.now().isoformat()
                    )
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
