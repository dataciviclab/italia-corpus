"""Fetch singolo di atti Normattiva via dettaglio-atto-urn.

Recupera leggi ordinarie non presenti in nessuna collezione ZIP,
arricchendo il corpus con vigenza dates e HTML articoli.

Uso:
    python -m lab_tools.fetch_urn_acts                    # da config/atti_singoli.txt
    python -m lab_tools.fetch_urn_acts --urn "urn:..."    # singolo URN
    python -m lab_tools.fetch_urn_acts --top 20           # top N dal grafo (richiede legal-graph)

Output: data/derived/atti_api.parquet
"""

from __future__ import annotations

import argparse
import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from lab_tools._paths import OUTDIR
from lab_tools.normattiva_client import fetch_act_by_urn

logger = logging.getLogger(__name__)

CONFIG_URN = Path(__file__).parent.parent / "config" / "atti_singoli.txt"
OUTPUT_PARQUET = OUTDIR / "atti_api.parquet"

# Rate limiting: IPZS richiede accesso educato
RATE_LIMIT_SECONDS = 2.5

# TTL: re-fetch un atto solo se l'ultimo fetch è più vecchio di questi giorni.
# Le leggi ordinarie storiche cambiano raramente; 30 giorni è un buon compromesso.
TTL_DAYS = 30


def load_urn_config(config_path: Path) -> list[dict]:
    """Carica URN da config/atti_singoli.txt.

    Formato: urn | note
    Riga con # = commento.
    """
    if not config_path.exists():
        logger.warning("Config %s not found", config_path)
        return []

    urns = []
    for line in config_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("|", 1)
        urn = parts[0].strip()
        note = parts[1].strip() if len(parts) > 1 else ""
        if urn.startswith("urn:"):
            urns.append({"urn": urn, "note": note})

    logger.info("Loaded %d URNs from %s", len(urns), config_path)
    return urns


def parse_atto(atto: dict, urn: str) -> dict:
    """Estrae metadati strutturati dalla response dettaglio-atto-urn."""
    html = atto.get("articoloHtml", "")

    # Parse articles from HTML
    art_ids = re.findall(r'id="art_(\w+)"', html)

    # Detect abrogation from tombstone
    abrogato = "ABROGATO" in html.upper() or "DECADUTO" in html.upper()

    # Vigenza dates (YYYYMMDD format)
    vig_in = atto.get("articoloDataInizioVigenza", "")
    vig_out = atto.get("articoloDataFineVigenza", "")

    # Normalize dates to YYYY-MM-DD
    def normalize_date(d: str) -> str:
        if not d or len(d) != 8 or not d.isdigit():
            return ""
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"

    # Determine stato
    if vig_out and vig_out != "99999999":
        stato = "abrogato"
    elif abrogato:
        stato = "abrogato"
    else:
        stato = "vigente"

    return {
        "urn": urn,
        "titolo": atto.get("titolo", ""),
        "sotto_titolo": atto.get("sottoTitolo", ""),
        "tipo_codice": atto.get("tipoProvvedimentoCodice", ""),
        "tipo_descrizione": atto.get("tipoProvvedimentoDescrizione", ""),
        "numero": atto.get("numeroProvvedimento"),
        "anno": atto.get("annoProvvedimento"),
        # GU metadata
        "anno_gu": atto.get("annoGU"),
        "numero_gu": atto.get("numeroGU"),
        # Vigenza
        "vigenza_inizio": normalize_date(vig_in),
        "vigenza_fine": normalize_date(vig_out) if vig_out != "99999999" else "",
        "stato": stato,
        # Content
        "articolo_html": html,
        "html_length": len(html),
        "n_articoli": len(art_ids),
        "articoli_ids": ",".join(art_ids[:50]),  # cap for parquet
        # Provenance
        "source": "normattiva_api",
        "endpoint": "dettaglio-atto-urn",
        "fetched_at": datetime.now().isoformat(),
    }


def fetch_and_store(urns: list[dict], output_path: Path) -> int:
    """Fetch ogni URN e salva risultati in parquet.

    TTL cache: se output_path esiste e un atto è stato fetchato
    meno di TTL_DAYS giorni fa, viene riutilizzato senza re-fetch.
    """
    try:
        import pandas as pd
    except ImportError:
        logger.error("pandas required for parquet output")
        return 0

    # Load existing data for TTL cache
    existing: dict[str, dict] = {}
    if output_path.exists():
        try:
            old_df = pd.read_parquet(output_path)
            if "fetched_at" in old_df.columns and len(old_df) > 0:
                cutoff = datetime.now() - timedelta(days=TTL_DAYS)
                for _, row in old_df.iterrows():
                    urn = row.get("urn", "")
                    fetched_at = row.get("fetched_at")
                    if urn and fetched_at:
                        try:
                            fa = datetime.fromisoformat(str(fetched_at))
                            if fa > cutoff:
                                existing[urn] = row.to_dict()
                        except (ValueError, TypeError):
                            pass
                logger.info(
                    "TTL cache: %d atti freschi (fetchati entro %d giorni)",
                    len(existing), TTL_DAYS,
                )
        except Exception as e:
            logger.warning("Cannot load existing parquet for TTL cache: %s", e)

    rows = []
    n_found = 0
    n_cached = 0
    to_fetch = []

    # First pass: check cache
    for item in urns:
        urn = item["urn"]
        if urn in existing:
            row = dict(existing[urn])
            row["note_config"] = item.get("note", "")
            rows.append(row)
            n_cached += 1
        else:
            to_fetch.append(item)

    logger.info(
        "Fetch: %d da cache, %d da fetchare (TTL=%d giorni)",
        n_cached, len(to_fetch), TTL_DAYS,
    )

    # Second pass: fetch missing/stale
    for i, item in enumerate(to_fetch, 1):
        urn = item["urn"]
        note = item.get("note", "")
        logger.info("[%d/%d] Fetching %s (%s)", i, len(to_fetch), urn, note)

        atto = fetch_act_by_urn(urn)
        if atto:
            row = parse_atto(atto, urn)
            row["note_config"] = note
            row["fetched_at"] = datetime.now().isoformat()
            rows.append(row)
            n_found += 1
            logger.info(
                "  ✅ %s → %s (vig %s → %s, %d chars)",
                row["titolo"][:50],
                row["stato"],
                row["vigenza_inizio"],
                row["vigenza_fine"] or "∞",
                row["html_length"],
            )
        else:
            logger.warning("  ❌ Not found: %s", urn)

        # Rate limit (skip after last)
        if i < len(to_fetch):
            time.sleep(RATE_LIMIT_SECONDS)

    # Save parquet
    if rows:
        df = pd.DataFrame(rows)
        # Ensure fetched_at column exists for all rows
        if "fetched_at" not in df.columns:
            df["fetched_at"] = datetime.now().isoformat()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(output_path, index=False)
        logger.info(
            "Saved %d acts to %s (cached=%d, fetched=%d)",
            len(df), output_path, n_cached, n_found,
        )
    else:
        logger.warning("No acts fetched — parquet not written")

    return n_found


def main():
    parser = argparse.ArgumentParser(description="Fetch atti Normattiva via URN")
    parser.add_argument("--urn", help="Single URN to fetch")
    parser.add_argument("--config", type=Path, default=CONFIG_URN,
                       help="Config file with URNs")
    parser.add_argument("--output", type=Path, default=OUTPUT_PARQUET,
                       help="Output parquet path")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.urn:
        # Single URN mode
        urns = [{"urn": args.urn, "note": "cli"}]
    else:
        urns = load_urn_config(args.config)

    if not urns:
        logger.error("No URNs to fetch")
        return

    n_found = fetch_and_store(urns, args.output)
    logger.info("Done: %d/%d acts fetched", n_found, len(urns))


if __name__ == "__main__":
    main()
