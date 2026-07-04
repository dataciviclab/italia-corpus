"""Estrae citazioni della Costituzione dai body degli atti normativi.

Cerca pattern come "art. 76 della Costituzione", "articolo 117 della Costituzione"
e produce un dataset derivato con archi atto → articolo costituzionale citato.

Output: data/derived/citazioni-costituzionali.parquet
Richiede: normativa.parquet (per metadati anno/collezione)

Uso: python -m lab_tools.estrai_citazioni_costituzionali
"""

from __future__ import annotations

import csv as csv_module
import re
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

REPO = Path(__file__).resolve().parent.parent
OUTDIR = REPO / "data" / "derived"
CONFIG_COLLEZIONI = REPO / "config" / "collezioni.txt"
NORMATIVA_PARQUET = OUTDIR / "normativa.parquet"

# Pattern: art. N, articolo N, articoli N [e M] della Costituzione
# Pattern per citazioni costituzionali: i numeri devono essere
# IMMEDIATAMENTE prima di "della Costituzione" — niente falsi positivi
# da art. X di leggi ordinarie.
RE_SINGOLARE = re.compile(
    r'(?:art\.|articolo)\s+(\d+)\s+della\s*Costituzione',
    re.IGNORECASE,
)
RE_NUMERO = re.compile(r'\d+')
# Pattern per trovare "articoli ... della Costituzione" senza backtracking:
# cerca 'della Costituzione' con str.find, poi guarda indietro per 'articoli'.
CONTESTO_RAGGIO = 80
# Distanza massima tra 'articoli' e 'della Costituzione'
MAX_ARTICOLI_DIST = 120


def _collezioni_legislative() -> list[Path]:
    """Legge da config/collezioni.txt: solo directory elencate ed esistenti."""
    if not CONFIG_COLLEZIONI.exists():
        return []
    nomi = [line.strip() for line in CONFIG_COLLEZIONI.read_text().splitlines() if line.strip()]
    return sorted(d for d in (REPO / n for n in nomi) if d.is_dir())


def _load_normativa_lookup() -> dict[str, dict]:
    """Carica normativa.parquet e costruisce lookup filename → metadati."""
    if not NORMATIVA_PARQUET.exists():
        print(f"Attenzione: {NORMATIVA_PARQUET} non trovato. Arricchimento saltato.")
        return {}
    table = pq.read_table(NORMATIVA_PARQUET, columns=["filename", "collezione", "anno_atto", "tipo"])
    lookup: dict[str, dict] = {}
    for i in range(table.num_rows):
        fn = table.column("filename")[i].as_py()
        if fn:
            lookup[fn] = {
                "collezione": table.column("collezione")[i].as_py() or "",
                "anno_atto": table.column("anno_atto")[i].as_py() or 0,
                "tipo": table.column("tipo")[i].as_py() or "",
            }
    return lookup


def _estrai_citazioni(raw: str) -> list[tuple[int, str]]:
    """Estrae (articolo, contesto) da un body markdown.

    Usa str.find() per evitare catastrophic backtracking su file lunghi.
    Gestisce:
      'art. 76 della Costituzione' → [76]
      'articolo 117 della Costituzione' → [117]
      'articoli 76 e 87 della Costituzione' → [76, 87]
      'articoli 76, 87 e 117 della Costituzione' → [76, 87, 117]
    """
    matches: list[tuple[int, str]] = []
    low = raw.lower()

    # ── Singolare: regex semplice, nessun backtracking ──
    for m in RE_SINGOLARE.finditer(raw):
        art = int(m.group(1))
        if 1 <= art <= 139:
            start = max(0, m.start() - CONTESTO_RAGGIO)
            end = min(len(raw), m.end() + CONTESTO_RAGGIO)
            matches.append((art, raw[start:end].replace("\n", " ").strip()))

    # ── Plurale: str.find() lineare, zero backtracking ──
    pos = 0
    while True:
        idx = low.find("della costituzione", pos)
        if idx < 0:
            break

        # Cerca 'articoli' all'indietro (max MAX_ARTICOLI_DIST caratteri)
        lookback_start = max(0, idx - MAX_ARTICOLI_DIST)
        chunk = raw[lookback_start:idx]

        # Trova l'ultima occorrenza di 'articoli' nel chunk
        art_idx = chunk.lower().rfind("articoli")
        if art_idx < 0:
            pos = idx + 1
            continue

        # Estrai la porzione tra 'articoli' e 'della Costituzione'
        fragment = chunk[art_idx + len("articoli"):].strip()
        numeri = [int(n) for n in RE_NUMERO.findall(fragment)]

        # Filtra solo numeri validi (1-139)
        for art in numeri:
            if 1 <= art <= 139:
                # Usa idx come riferimento per il contesto
                start = max(0, idx - CONTESTO_RAGGIO)
                end = min(len(raw), idx + len(" della Costituzione") + CONTESTO_RAGGIO)
                matches.append((art, raw[start:end].replace("\n", " ").strip()))

        pos = idx + 1

    # Dedup: stessa coppia (articolo, contesto_simile) può uscire da
    # singolare+plurale o da contesti sovrapposti
    seen: set[tuple[int, str]] = set()
    unique: list[tuple[int, str]] = []
    for art, ctx in matches:
        key = (art, ctx[:100])
        if key not in seen:
            seen.add(key)
            unique.append((art, ctx))
    return unique


def _stampa_metriche(records: list[dict]):
    """Stampa metriche riassuntive."""
    total = len(records)
    if total == 0:
        print("Nessuna citazione trovata.")
        return

    fonti = set(r["fonte_filename"] for r in records)
    articoli_counter = Counter(r["articolo"] for r in records)

    print(f"\n📊 Citazioni Costituzionali — metriche")
    print(f"{'='*40}")
    print(f"  Citazioni totali:     {total:>6,}")
    print(f"  Atti citanti:         {len(fonti):>6,}")
    print(f"  Articoli citati:       {len(articoli_counter):>3}")
    print(f"\n  Top 15 articoli più citati:")
    for art, cnt in articoli_counter.most_common(15):
        print(f"    Art. {art:3d}: {cnt:5d}x")


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)

    print("Caricamento normativa.parquet...")
    normativa = _load_normativa_lookup()
    print(f"  {len(normativa)} atti caricati")

    print("Estrazione citazioni dai body...")
    records: list[dict] = []
    for col_dir in _collezioni_legislative():
        nome_collezione = col_dir.name
        for f in sorted(col_dir.glob("*.md")):
            relpath = f.relative_to(REPO)
            try:
                raw = f.read_text("utf-8", errors="replace")
            except Exception:
                continue

            citazioni = _estrai_citazioni(raw)
            if not citazioni:
                continue

            meta = normativa.get(relpath.name, {})
            for art, contesto in citazioni:
                records.append({
                    "fonte_filename": str(relpath),
                    "fonte_collezione": nome_collezione,
                    "fonte_anno": meta.get("anno_atto", 0),
                    "fonte_tipo": meta.get("tipo", ""),
                    "articolo": art,
                    "contesto": contesto[:300],
                })

    _stampa_metriche(records)

    # Salva CSV
    csv_path = OUTDIR / "citazioni-costituzionali.csv"
    import csv as csv_module
    fieldnames = [
        "fonte_filename", "fonte_collezione", "fonte_anno", "fonte_tipo",
        "articolo", "contesto",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv_module.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(records)
    print(f"\nCSV: {csv_path} ({len(records)} righe)")

    # Salva Parquet
    pqt = OUTDIR / "citazioni-costituzionali.parquet"
    table = pa.Table.from_pylist(records)
    pq.write_table(table, pqt)
    print(f"Parquet: {pqt} ({table.num_rows} righe, {table.num_columns} colonne)")


if __name__ == "__main__":
    main()
