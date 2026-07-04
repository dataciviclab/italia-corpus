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
# Cattura il PRIMO numero articolo (per "articoli 76 e 87" prende 76)
# Trova la frase tra (art.|articolo/i) e "della Costituzione", poi estrai TUTTI i numeri
RE_FRASE = re.compile(
    r'(?:art\.|articolo|articoli)\s(.+?)\s+della\s*Costituzione',
    re.IGNORECASE | re.DOTALL,
)
RE_NUMERO = re.compile(r'\d+')
# Contesto: 80 caratteri prima e dopo il match
CONTESTO_RAGGIO = 80


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

    Gestisce: 'art. 76', 'articolo 117', 'articoli 76 e 87', 'articoli 76, 87 e 117'.
    """
    matches: list[tuple[int, str]] = []
    for m in RE_FRASE.finditer(raw):
        # Estrai TUTTI i numeri dalla frase tra "articoli" e "della Costituzione"
        numeri = [int(n) for n in RE_NUMERO.findall(m.group(1))]
        for art in numeri:
            if art < 1 or art > 139:
                continue  # fuori range articoli Costituzione
            start = max(0, m.start() - CONTESTO_RAGGIO)
            end = min(len(raw), m.end() + CONTESTO_RAGGIO)
            contesto = raw[start:end].replace("\n", " ").strip()
            matches.append((art, contesto))
    return matches


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
