"""Identity-fetch delle direttive UE citate dal corpus (prototipo).

Mappa gli URN ``urn:nir:eu:direttivaue:YYYY;N`` (e la variante
``direttiva.ue``) su CELEX e recupera da CELLAR i metadati minimi:
titolo ITA/ENG, data, scadenza di recepimento, vigenza.

Fonte: SPARQL CELLAR del Publications Office (ontologia CDM).
Nessun testo viene scaricato: ``legal_text`` degrada al link EUR-Lex.

Uso:
    python -m lab_tools.fetch_direttive_ue             # scan + titoli (cache)
    python -m lab_tools.fetch_direttive_ue --refresh   # ignora la cache
    python -m lab_tools.fetch_direttive_ue --limit 50  # prova veloce

Output: ``out/direttive_ue/direttive_ue.parquet``
Cache:  ``out/direttive_ue/{cellar_scan,titoli}.json``
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "out" / "direttive_ue"
SCAN_CACHE = OUT_DIR / "cellar_scan.json"
TITLES_CACHE = OUT_DIR / "titoli.json"
OUTPUT = OUT_DIR / "direttive_ue.parquet"
RIFERIMENTI = REPO / "data" / "derived" / "riferimenti.parquet"

SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
CDM = "http://publications.europa.eu/ontology/cdm#"
LANG = "http://publications.europa.eu/resource/authority/language"
RESOURCE_TYPE = "http://publications.europa.eu/resource/authority/resource-type"
DIR_TYPES = (f"<{RESOURCE_TYPE}/DIR>", f"<{RESOURCE_TYPE}/DIR_IMPL>", f"<{RESOURCE_TYPE}/DIR_DEL>")

FIRST_YEAR = 1958
TITLE_BATCH = 100
RETRIES = 3

URN_RE = re.compile(r"urn:nir:eu:direttiva(?:\.?ue):(\d{4});(\d+)$")
CELEX_RE = re.compile(r"3\d{4}L\d{4}$")


def celex_from_urn(urn: str) -> str | None:
    """``urn:nir:eu:direttivaue:1989;391`` -> ``31989L0391``."""
    m = URN_RE.match(urn)
    if not m:
        return None
    anno, numero = m.groups()
    return f"3{anno}L{int(numero):04d}"


def _sparql(query: str, timeout: int = 120) -> list[dict]:
    """Esegue una query SPARQL e restituisce i binding, con retry."""
    data = urllib.parse.urlencode({"query": query, "format": "application/sparql-results+json"}).encode()
    last: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(
                SPARQL_ENDPOINT,
                data=data,
                headers={"User-Agent": "DataCivicLab-italia-corpus/0.1", "Accept": "application/sparql-results+json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)["results"]["bindings"]
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            logger.warning("SPARQL tentativo %d/%d fallito: %s", attempt, RETRIES, exc)
            time.sleep(2**attempt)
    raise RuntimeError(f"SPARQL non disponibile dopo {RETRIES} tentativi: {last}")


def load_targets(path: Path = RIFERIMENTI) -> dict[str, dict]:
    """CELEX attesi -> URN varianti e numero di citazioni."""
    if not path.exists():
        raise FileNotFoundError(f"{path} non trovato: serve il riferimento del build")
    df = pd.read_parquet(path, columns=["bersaglio_urn"])
    targets: dict[str, dict] = {}
    urn_ue: set[str] = set()
    for urn in df["bersaglio_urn"]:
        if not urn.startswith("urn:nir:eu:"):
            continue
        urn_ue.add(urn)
        celex = celex_from_urn(urn)
        if celex is None:
            continue
        entry = targets.setdefault(celex, {"urns": set(), "n_citazioni": 0})
        entry["urns"].add(urn)
        entry["n_citazioni"] += 1
    logger.info("target: %d URN UE -> %d CELEX distinti", len(urn_ue), len(targets))
    return targets


def _year_query(year: int) -> str:
    types = ", ".join(DIR_TYPES)
    return f"""PREFIX cdm: <{CDM}>
SELECT DISTINCT ?work ?celex ?date ?datetranspos ?inforce WHERE {{
  ?work cdm:work_has_resource-type ?type .
  FILTER(?type IN ({types}))
  ?work cdm:resource_legal_id_celex ?celex .
  FILTER(STRSTARTS(?celex, "3{year}"))
  OPTIONAL {{ ?work cdm:work_date_document ?date }}
  OPTIONAL {{ ?work cdm:directive_date_transposition ?datetranspos }}
  OPTIONAL {{ ?work cdm:resource_legal_in-force ?inforce }}
}}
"""


def scan_cellar(refresh: bool = False) -> dict[str, dict]:
    """Scansiona le direttive per anno e indicizza per CELEX base."""
    if SCAN_CACHE.exists() and not refresh:
        cached = json.loads(SCAN_CACHE.read_text())
        logger.info("scan da cache: %d CELEX (%s)", len(cached["works"]), cached["fetched_at"])
        return cached["works"]

    years = range(FIRST_YEAR, datetime.now().year + 2)
    works: dict[str, dict] = {}
    t0 = time.time()
    for i, year in enumerate(years, 1):
        for row in _sparql(_year_query(year)):
            celex = row["celex"]["value"]
            if not CELEX_RE.match(celex):
                continue
            entry = works.setdefault(
                celex,
                {
                    "work": row["work"]["value"],
                    "data": None,
                    "scadenze": set(),
                    "in_vigore": None,
                },
            )
            entry["data"] = entry["data"] or row.get("date", {}).get("value")
            if "datetranspos" in row:
                entry["scadenze"].add(row["datetranspos"]["value"])
            if "inforce" in row:
                entry["in_vigore"] = row["inforce"]["value"] in {"1", "true"}
        if i % 10 == 0:
            logger.info("scan %d anni (%d), %d CELEX, %.0fs", i, year, len(works), time.time() - t0)

    payload = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "works": {k: {**v, "scadenze": sorted(v["scadenze"])} for k, v in works.items()},
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SCAN_CACHE.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    logger.info("scan completo: %d CELEX in %.0fs", len(works), time.time() - t0)
    return payload["works"]


def _titles_query(work_uris: list[str]) -> str:
    values = " ".join(f"<{u}>" for u in work_uris)
    return f"""PREFIX cdm: <{CDM}>
SELECT ?work ?lang ?title WHERE {{
  VALUES ?work {{ {values} }}
  ?exp cdm:expression_belongs_to_work ?work ;
       cdm:expression_title ?title ;
       cdm:expression_uses_language ?lang .
  FILTER(?lang IN (<{LANG}/ITA>, <{LANG}/ENG>))
}}
"""


def fetch_titles(work_uris: list[str], refresh: bool = False) -> dict[str, dict]:
    """Titoli ITA/ENG per i work Cellar (batch di 100, cache su disco)."""
    cached: dict[str, dict] = {}
    if TITLES_CACHE.exists() and not refresh:
        cached = json.loads(TITLES_CACHE.read_text())["titoli"]
        logger.info("titoli da cache: %d work", len(cached))

    missing = [u for u in work_uris if u not in cached]
    logger.info("titoli: %d da fetchare su %d work", len(missing), len(work_uris))
    for start in range(0, len(missing), TITLE_BATCH):
        batch = missing[start : start + TITLE_BATCH]
        for row in _sparql(_titles_query(batch)):
            work = row["work"]["value"]
            lang = row["lang"]["value"].rsplit("/", 1)[-1]
            entry = cached.setdefault(work, {})
            entry[lang.lower()] = row["title"]["value"]
        logger.info("titoli: %d/%d", min(start + TITLE_BATCH, len(missing)), len(missing))

    if missing:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        TITLES_CACHE.write_text(
            json.dumps(
                {"fetched_at": datetime.now().isoformat(timespec="seconds"), "titoli": cached},
                ensure_ascii=False,
                indent=1,
            )
        )
    return cached


def build_rows(targets: dict[str, dict], works: dict[str, dict], titles: dict[str, dict]) -> pd.DataFrame:
    rows = []
    for celex, info in targets.items():
        work = works.get(celex)
        titoli = titles.get(work["work"], {}) if work else {}
        anno, numero = celex[1:5], int(celex[6:])
        risolto = work is not None
        # Cellar contiene date segnaposto (1001-01-01, 1002-02-02): scartate.
        scadenze = [s for s in work["scadenze"] if "1950-01-01" <= s <= "2100-01-01"] if work else []
        rows.append(
            {
                "celex": celex,
                "urn_varianti": ";".join(sorted(info["urns"])),
                "n_citazioni": info["n_citazioni"],
                "stato": "risolto" if risolto else "non_risolto",
                "motivo": None if risolto else "non_in_cellar",
                "work_uri": work["work"] if work else None,
                "titolo_ita": titoli.get("ita"),
                "titolo_eng": titoli.get("eng"),
                "titolo": titoli.get("ita") or titoli.get("eng"),
                "data": work["data"] if work else None,
                "scadenze": ";".join(scadenze),
                "scadenza_recepimento": min(scadenze) if scadenze else None,
                "n_scadenze": len(scadenze),
                "in_vigore": work["in_vigore"] if work else None,
                "eurlex_url": f"https://eur-lex.europa.eu/legal-content/IT/TXT/?uri=CELEX:{celex}",
                "eli_url": f"https://eur-lex.europa.eu/eli/dir/{anno}/{numero}/oj" if risolto else None,
            }
        )
    return pd.DataFrame(rows).sort_values(["n_citazioni", "celex"], ascending=[False, True]).reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Identity-fetch delle direttive UE citate dal corpus")
    parser.add_argument("--refresh", action="store_true", help="ignora le cache e rifetcha")
    parser.add_argument("--limit", type=int, default=None, help="solo le prime N direttive per citazioni (test)")
    parser.add_argument("--output", type=Path, default=OUTPUT, help=f"parquet di output (default: {OUTPUT})")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    targets = load_targets()
    if args.limit:
        top = sorted(targets, key=lambda c: -targets[c]["n_citazioni"])[: args.limit]
        targets = {c: targets[c] for c in top}

    works = scan_cellar(refresh=args.refresh)
    found = {c: works[c] for c in targets if c in works}
    titles = fetch_titles(sorted({w["work"] for w in found.values()}), refresh=args.refresh)

    df = build_rows(targets, works, titles)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.output, index=False)

    n_ok = int((df["stato"] == "risolto").sum())
    cit_ok = int(df.loc[df["stato"] == "risolto", "n_citazioni"].sum())
    cit_tot = int(df["n_citazioni"].sum())
    con_titolo = int(df["titolo"].notna().sum())
    logger.info(
        "scritto %s: %d CELEX (%d risolti, %d con titolo), citazioni %d/%d (%.1f%%)",
        args.output,
        len(df),
        n_ok,
        con_titolo,
        cit_ok,
        cit_tot,
        100 * cit_ok / cit_tot if cit_tot else 0,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
