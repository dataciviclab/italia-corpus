"""Costruisce il grafo unificato dei riferimenti normativi.

Legge tutti i file .md delle collezioni legislative e produce un unico
dataset con due tipi di archi:
  - tipo_riferimento="atto": link relativi ../ ad altri atti nel corpus
  - tipo_riferimento="costituzione": citazioni "art. N della Costituzione"

Output: data/derived/riferimenti.parquet

Uso: python -m lab_tools.grafo_riferimenti
"""

from __future__ import annotations

import re
import urllib.parse
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTDIR = REPO / "data" / "derived"
CONFIG_COLLEZIONI = REPO / "config" / "collezioni.txt"
NORMATIVA_PARQUET = OUTDIR / "normativa.parquet"

# ── Pattern per link relativi (riferimenti ad altri atti) ──
RE_LINK = re.compile(r'\.\./([^)]+?)\.md')

# ── Pattern per citazioni costituzionali ──
RE_COST_SINGOLARE = re.compile(
    r'(?:art\.|articolo)\s+(\d+)\s+della\s*Costituzione',
    re.IGNORECASE,
)
RE_NUMERO = re.compile(r'\d+')
CONTESTO_RAGGIO = 80
MAX_ARTICOLI_DIST = 120
RE_MD_LINK = re.compile(r'\[([^\]]*)\]\([^)]+\)')


def _collezioni_legislative() -> list[Path]:
    """Legge da config/collezioni.txt: solo directory elencate ed esistenti."""
    if not CONFIG_COLLEZIONI.exists():
        return []
    nomi = [line.strip() for line in CONFIG_COLLEZIONI.read_text().splitlines() if line.strip()]
    return sorted(d for d in (REPO / n for n in nomi) if d.is_dir())


def _build_file_set() -> set[str]:
    """Costruisce set di path relativi di tutti i file .md nelle collezioni."""
    files: set[str] = set()
    for col_dir in _collezioni_legislative():
        for f in col_dir.glob("*.md"):
            files.add(str(f.relative_to(REPO)))
    return files


def _load_normativa_lookup() -> dict[str, dict]:
    """Carica normativa.parquet e costruisce lookup filename -> metadati."""
    try:
        import pandas as pd
    except ImportError:
        print("Errore: pandas necessario per leggere normativa.parquet.")
        return {}

    if not NORMATIVA_PARQUET.exists():
        print(f"Attenzione: {NORMATIVA_PARQUET} non trovato. Arricchimento saltato.")
        return {}

    df = pd.read_parquet(NORMATIVA_PARQUET)
    lookup: dict[str, dict] = {}
    for _, row in df.iterrows():
        fn = row.get("filename", "")
        if fn:
            lookup[fn] = {
                "collezione": row.get("collezione", ""),
                "anno_atto": row.get("anno_atto", 0),
                "tipo": row.get("tipo", ""),
            }
    return lookup


# ── Estrazione link relativi ────────────────────────────────────────


def estrai_link(body: str) -> list[str]:
    """Estrae i path dei link ../ da un body markdown, decodificati."""
    links = RE_LINK.findall(body)
    return [urllib.parse.unquote(link) + ".md" for link in links]


def risolvi_path(link_decoded: str, current_relpath: Path) -> Path | None:
    """Risolve un link relativo ../ in path assoluto rispetto al repo."""
    parent = current_relpath.parent
    if str(parent) == ".":
        return None
    resolved = (parent.parent / link_decoded).resolve()
    try:
        return resolved.relative_to(REPO)
    except ValueError:
        return None


# ── Estrazione citazioni costituzionali ─────────────────────────────


def estrai_citazioni_costituzionali(raw: str) -> list[tuple[int, str]]:
    """Estrae (articolo, contesto) da un body markdown.

    Gestisce:
      'art. 76 della Costituzione' -> [76]
      'articoli 76 e 87 della Costituzione' -> [76, 87]
    """
    clean = RE_MD_LINK.sub(r'\1', raw)
    matches: list[tuple[int, str]] = []
    low = clean.lower()

    # Singolare: regex semplice
    for m in RE_COST_SINGOLARE.finditer(clean):
        art = int(m.group(1))
        if 1 <= art <= 139:
            start = max(0, m.start() - CONTESTO_RAGGIO)
            end = min(len(clean), m.end() + CONTESTO_RAGGIO)
            matches.append((art, clean[start:end].replace("\n", " ").strip()))

    # Plurale: str.find() lineare
    pos = 0
    while True:
        idx = low.find("della costituzione", pos)
        if idx < 0:
            break
        lookback_start = max(0, idx - MAX_ARTICOLI_DIST)
        chunk = clean[lookback_start:idx]
        art_idx = chunk.lower().rfind("articoli")
        if art_idx < 0:
            pos = idx + 1
            continue
        fragment = chunk[art_idx + len("articoli"):].strip()
        numeri = [int(n) for n in RE_NUMERO.findall(fragment)]
        for art in numeri:
            if 1 <= art <= 139:
                start = max(0, idx - CONTESTO_RAGGIO)
                end = min(len(clean), idx + len(" della Costituzione") + CONTESTO_RAGGIO)
                matches.append((art, clean[start:end].replace("\n", " ").strip()))
        pos = idx + 1

    # Dedup
    seen: set[tuple[int, str]] = set()
    unique: list[tuple[int, str]] = []
    for art, ctx in matches:
        key = (art, ctx[:100])
        if key not in seen:
            seen.add(key)
            unique.append((art, ctx))
    return unique


# ── Metriche ────────────────────────────────────────────────────────


def _stampa_metriche(archi: list[dict], file_set_size: int):
    """Stampa metriche riassuntive del grafo."""
    total = len(archi)
    if total == 0:
        print("Nessun arco estratto.")
        return

    archi_atto = [a for a in archi if a["tipo_riferimento"] == "atto"]
    archi_cost = [a for a in archi if a["tipo_riferimento"] == "costituzione"]

    fonti = set(a["fonte_filename"] for a in archi)
    risolti = sum(1 for a in archi_atto if a["risolto"])

    print(f"\nGrafo riferimenti — metriche")
    print(f"{'='*40}")
    print(f"  Archi totali:        {total:>8,}")
    print(f"  - atto:              {len(archi_atto):>8,} ({risolti} risolti)")
    print(f"  - costituzione:      {len(archi_cost):>8,}")
    print(f"  Atti con riferimenti: {len(fonti):>7,}")
    print(f"  File nel corpus:      {file_set_size:>7,}")


# ── Main ────────────────────────────────────────────────────────────


def main():
    import csv as csv_module

    OUTDIR.mkdir(parents=True, exist_ok=True)

    print("Costruzione file set...")
    file_set = _build_file_set()
    print(f"  {len(file_set)} file .md trovati")

    print("Caricamento normativa.parquet...")
    normativa = _load_normativa_lookup()
    print(f"  {len(normativa)} atti caricati")

    archi: list[dict] = []

    # ── Riferimenti ad altri atti (link relativi) ──
    print("Estrazione link relativi...")
    for col_dir in _collezioni_legislative():
        nome_collezione = col_dir.name
        for f in sorted(col_dir.glob("*.md")):
            relpath = f.relative_to(REPO)
            try:
                raw = f.read_text("utf-8", errors="replace")
            except Exception:
                continue

            links = estrai_link(raw)
            if not links:
                continue

            peso_counter: dict[str, int] = {}
            for link in links:
                peso_counter[link] = peso_counter.get(link, 0) + 1

            for link_decoded, peso in peso_counter.items():
                resolved = risolvi_path(link_decoded, relpath)
                if resolved is None:
                    bersaglio_fn = link_decoded
                    bersaglio_path = None
                else:
                    bersaglio_path = str(resolved)
                    bersaglio_fn = resolved.name

                risolto = bersaglio_path in file_set if bersaglio_path else False

                fonte_meta = normativa.get(relpath.name, {})
                bersaglio_meta = normativa.get(bersaglio_fn, {}) if risolto else {}
                bp = bersaglio_path if risolto else ""

                archi.append({
                    "tipo_riferimento": "atto",
                    "fonte_filename": str(relpath),
                    "fonte_collezione": nome_collezione,
                    "fonte_anno": fonte_meta.get("anno_atto", 0),
                    "fonte_tipo": fonte_meta.get("tipo", ""),
                    "bersaglio_filename": bersaglio_fn,
                    "bersaglio_path": bp or "",
                    "bersaglio_collezione": bersaglio_meta.get("collezione", ""),
                    "bersaglio_anno": bersaglio_meta.get("anno_atto", 0),
                    "bersaglio_tipo": bersaglio_meta.get("tipo", ""),
                    "peso": peso,
                    "risolto": risolto,
                })

    # ── Citazioni costituzionali ──
    print("Estrazione citazioni costituzionali...")
    for col_dir in _collezioni_legislative():
        nome_collezione = col_dir.name
        for f in sorted(col_dir.glob("*.md")):
            relpath = f.relative_to(REPO)
            try:
                raw = f.read_text("utf-8", errors="replace")
            except Exception:
                continue

            citazioni = estrai_citazioni_costituzionali(raw)
            if not citazioni:
                continue

            meta = normativa.get(relpath.name, {})
            for art, contesto in citazioni:
                archi.append({
                    "tipo_riferimento": "costituzione",
                    "fonte_filename": str(relpath),
                    "fonte_collezione": nome_collezione,
                    "fonte_anno": meta.get("anno_atto", 0),
                    "fonte_tipo": meta.get("tipo", ""),
                    "bersaglio_filename": "",
                    "bersaglio_path": "",
                    "bersaglio_collezione": "",
                    "bersaglio_anno": 0,
                    "bersaglio_tipo": "",
                    "peso": 1,
                    "risolto": True,
                    "articolo_costituzione": art,
                    "contesto": contesto[:300],
                })

    _stampa_metriche(archi, len(file_set))

    # Salva CSV
    csv_path = OUTDIR / "riferimenti.csv"
    import csv as csv_module
    fieldnames = [
        "tipo_riferimento", "fonte_filename", "fonte_collezione",
        "fonte_anno", "fonte_tipo",
        "bersaglio_filename", "bersaglio_path", "bersaglio_collezione",
        "bersaglio_anno", "bersaglio_tipo",
        "peso", "risolto", "articolo_costituzione", "contesto",
    ]
    archi_out = [{k: v for k, v in a.items() if k in fieldnames} for a in archi]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv_module.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(archi_out)
    print(f"\nCSV: {csv_path} ({len(archi)} righe)")

    # Salva Parquet
    try:
        import pandas as pd
        df = pd.DataFrame(archi)
        pqt = OUTDIR / "riferimenti.parquet"
        df.to_parquet(pqt, index=False)
        print(f"Parquet: {pqt} ({len(df)} righe, {len(df.columns)} colonne)")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
