"""Costruisce il grafo dei riferimenti normativi: archi orientati fonte → bersaglio.

Legge tutti i file .md delle collezioni legislative, estrae i link relativi ../,
li risolve in path assoluti del corpus, e produce un dataset con archi, peso e
metadati (anno, collezione, tipo) arricchiti da normativa.parquet.

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

RE_LINK = re.compile(r'\.\./([^)]+?)\.md')


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
    """Carica normativa.parquet e costruisce lookup filename → metadati."""
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


def estrai_link(body: str) -> list[str]:
    """Estrae i path dei link ../ da un body markdown, decodificati."""
    links = RE_LINK.findall(body)
    return [urllib.parse.unquote(link) + ".md" for link in links]


def risolvi_path(link_decoded: str, current_relpath: Path) -> Path | None:
    """Risolve un link relativo ../ in path assoluto rispetto al repo.

    Args:
        link_decoded: path decodificato (es. 'Decreti Legislativi/TU.md')
        current_relpath: path relativo del file corrente (es. 'DL Proroghe/x.md')

    Returns:
        Path risolto (relativo al repo) oppure None se non risolvibile.
    """
    parent = current_relpath.parent
    if str(parent) == ".":
        return None  # file in root, ../ andrebbe sopra — non dovrebbe capitare
    resolved = (parent.parent / link_decoded).resolve()
    # Verifica che sia dentro REPO
    try:
        return resolved.relative_to(REPO)
    except ValueError:
        return None


def _stampa_metriche(archi: list[dict], file_set_size: int):
    """Stampa metriche riassuntive del grafo."""
    total = len(archi)
    if total == 0:
        print("Nessun arco estratto.")
        return

    citati = set(a["bersaglio_filename"] for a in archi)
    fonti = set(a["fonte_filename"] for a in archi)
    risolti = sum(1 for a in archi if a["esiste"])
    non_risolti = total - risolti

    print(f"\n📊 Grafo riferimenti — metriche")
    print(f"{'='*40}")
    print(f"  Archi totali:        {total:>8,}")
    print(f"  Risolvibili:         {risolti:>8,} ({risolti/total*100:.1f}%)" if total else "")
    print(f"  Non risolvibili:     {non_risolti:>8,} ({non_risolti/total*100:.1f}%)" if total else "")
    print(f"  Atti citanti (fonti): {len(fonti):>8,}")
    print(f"  Atti citati (bers.): {len(citati):>8,}")
    print(f"  File nel corpus:     {file_set_size:>8,}")

    # Top citati (solo risolti)
    if risolti > 0:
        counter = Counter()
        for a in archi:
            if a["esiste"]:
                counter[(a["bersaglio_filename"])] += a["peso"]
        print(f"\n  Top 10 atti più citati:")
        for path, count in counter.most_common(10):
            short = path[:70]
            print(f"    {count:5d}x  {short}")


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)

    print("Costruzione file set...")
    file_set = _build_file_set()
    print(f"  {len(file_set)} file .md trovati")

    print("Caricamento normativa.parquet...")
    normativa = _load_normativa_lookup()
    print(f"  {len(normativa)} atti caricati")

    print("Estrazione link dai body...")
    archi: list[dict] = []
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

            # Conta occorrenze per link unico
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

                esiste = bersaglio_path in file_set if bersaglio_path else False

                # Metadati fonte
                fonte_meta = normativa.get(relpath.name, {})
                # Metadati bersaglio (solo se esiste)
                bersaglio_meta = normativa.get(bersaglio_fn, {}) if esiste else {}

                arco = {
                    "fonte_filename": str(relpath),
                    "fonte_collezione": nome_collezione,
                    "fonte_anno": fonte_meta.get("anno_atto", 0),
                    "fonte_tipo": fonte_meta.get("tipo", ""),
                    "bersaglio_filename": bersaglio_fn,
                    "bersaglio_path": bersaglio_path or "",
                    "bersaglio_collezione": bersaglio_meta.get("collezione", ""),
                    "bersaglio_anno": bersaglio_meta.get("anno_atto", 0),
                    "bersaglio_tipo": bersaglio_meta.get("tipo", ""),
                    "peso": peso,
                    "esiste": esiste,
                }
                archi.append(arco)

    _stampa_metriche(archi, len(file_set))

    # Salva CSV
    csv_path = OUTDIR / "riferimenti.csv"
    import csv as csv_module
    fieldnames = [
        "fonte_filename", "fonte_collezione", "fonte_anno", "fonte_tipo",
        "bersaglio_filename", "bersaglio_path", "bersaglio_collezione",
        "bersaglio_anno", "bersaglio_tipo", "peso",
    ]
    # Rimuovi campo tecnico 'esiste' prima di scrivere
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
        df = df.drop(columns=["esiste"])
        pqt = OUTDIR / "riferimenti.parquet"
        df.to_parquet(pqt, index=False)
        print(f"Parquet: {pqt} ({len(df)} righe, {len(df.columns)} colonne)")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
