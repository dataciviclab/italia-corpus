"""Client per l'API Normattiva OpenData.

Scarica le collezioni legislative vigenti in formato Akoma Ntoso XML.
"""

from __future__ import annotations

import logging
import time
import zipfile
from pathlib import Path
from tempfile import NamedTemporaryFile

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1"
COLLECTIONS_URL = f"{BASE_URL}/collections/collection-predefinite"
DOWNLOAD_URL = f"{BASE_URL}/collections/download/collection-preconfezionata"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/zip,application/octet-stream,*/*",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.normattiva.it/",
}

DOWNLOAD_TIMEOUT = (30.0, 300.0)
MAX_RETRIES = 3
RETRY_BACKOFF = 5.0


def fetch_predefined_collections() -> list[dict]:
    """GET /collections/collection-predefinite — restituisce la lista raw."""
    resp = requests.get(COLLECTIONS_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise TypeError(f"Expected list, got {type(data).__name__}")
    logger.info("Fetched %d predefined collections from Normattiva", len(data))
    return data


def merge_collections_by_name(rows: list[dict]) -> list[dict]:
    """Dedup per nomeCollezione: priorità V (vigente) > O (originale) > M (multivigente)."""
    from collections import defaultdict

    by_name: dict[str, list[dict]] = defaultdict(list)
    order: list[str] = []
    seen: set[str] = set()

    for row in rows:
        nome = (row.get("nomeCollezione") or row.get("nome") or "").strip()
        if not nome:
            continue
        by_name[nome].append(row)
        if nome not in seen:
            seen.add(nome)
            order.append(nome)

    priority = {"V": 0, "O": 1, "M": 2}
    out: list[dict] = []
    for nome in order:
        group = by_name[nome]
        codes = {(r.get("formatoCollezione") or "").strip().upper() for r in group} & {"O", "M", "V"}
        chosen = min(codes, key=lambda c: priority.get(c, 9)) if codes else "V"
        pick = next(
            (r for r in group if (r.get("formatoCollezione") or "").strip().upper() == chosen),
            group[0],
        )
        merged = dict(pick)
        merged["nomeCollezione"] = nome
        merged["formatoCollezione"] = chosen
        out.append(merged)
    return out


def filter_collections(collections: list[dict], only_names: list[str] | None = None) -> list[dict]:
    """Filtra le collezioni per nome. Se only_names è None, prendi tutte quelle con V."""
    if only_names is not None:
        allowed = set(only_names)
        return [c for c in collections if c["nomeCollezione"] in allowed]
    return [c for c in collections if c.get("formatoCollezione") == "V"]


def download_collection(collection: dict, dest_dir: Path) -> Path | None:
    """Scarica una collezione ZIP e restituisce il path, oppure None se fallisce."""
    nome = collection.get("nomeCollezione", "")
    fmt = collection.get("formatoCollezione", "V")
    params = {"nome": nome, "formato": "AKN", "formatoRichiesta": fmt}

    for attempt in range(1, MAX_RETRIES + 1):
        zip_path: Path | None = None
        try:
            tmp = NamedTemporaryFile(suffix=".zip", dir=str(dest_dir), delete=False)
            zip_path = Path(tmp.name)

            with requests.get(
                DOWNLOAD_URL,
                params=params,
                headers=HEADERS,
                timeout=DOWNLOAD_TIMEOUT,
                stream=True,
            ) as r:
                if r.status_code != 200:
                    logger.warning(
                        "Download %r attempt %d/%d: HTTP %d",
                        nome, attempt, MAX_RETRIES, r.status_code,
                    )
                    zip_path.unlink(missing_ok=True)
                    if attempt < MAX_RETRIES:
                        time.sleep(RETRY_BACKOFF * attempt)
                    continue

                for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                    tmp.write(chunk)
            tmp.close()

            # Validate ZIP header
            with open(zip_path, "rb") as f:
                if not f.read(2) == b"PK":
                    logger.error("Collection %r: not a valid ZIP", nome)
                    zip_path.unlink(missing_ok=True)
                    return None

            logger.info("Downloaded %r (%d bytes)", nome, zip_path.stat().st_size)
            return zip_path

        except requests.RequestException as e:
            logger.warning("Download %r attempt %d/%d failed: %s", nome, attempt, MAX_RETRIES, e)
            if zip_path:
                zip_path.unlink(missing_ok=True)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF * attempt)

    logger.error("Failed to download %r after %d attempts", nome, MAX_RETRIES)
    return None


def extract_zip(zip_path: Path, dest_dir: Path) -> list[Path]:
    """Estrae lo ZIP e restituisce i path dei file XML."""
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_dir)
    xml_files = sorted(dest_dir.rglob("*.xml"))
    logger.info("Extracted %d XML files from %s", len(xml_files), zip_path.name)
    return xml_files
