#!/usr/bin/env python3
"""Estrae abrogazioni dai testi normativi (ottimizzato per righe).

Cerca "è abrogato", "sono abrogati", "abrogato da" nei testi
e collega l'atto che abroga all'atto abrogato.

Output: abrogations_raw.parquet

Usage:
  python -m lab_tools.extract_abrogations
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

COLLECTIONS_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = COLLECTIONS_DIR / "data" / "derived"

# Regex per trovare atti abrogati: "legge N anno, n. X" o "decreto legislativo N anno, n. X"
ATTO_REF = re.compile(
    r"(?:legge|decreto[\s-]legge|decreto legislativo|decreto del Presidente(?:\s+della Repubblica)?|"
    r"regio decreto(?:[\s-]legislativo)?)"
    r"\s+(?:del\s+)?(?:\d{1,2}\s+\w+\s+)?(\d{4})[,\s]+n[.\s]*(\d+)",
    re.IGNORECASE
)

# Filtro: escludi abrogazioni generiche ("disposizioni contrarie/incompatibili")
SKIP_PAT = re.compile(r"contrari\w+|incompatibil\w+|precedenti\w+|concilienti|non compatibil", re.IGNORECASE)


def extract_from_file(filepath: Path) -> list[dict]:
    """Estrai abrogazioni da un file, riga per riga (memoria efficiente)."""
    try:
        lines = filepath.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    results = []
    for line in lines:
        if "abrog" not in line.lower():
            continue
        if SKIP_PAT.search(line):
            continue
        for ref in ATTO_REF.finditer(line):
            year, num = int(ref.group(1)), int(ref.group(2))
            results.append({
                "abrogating_file": filepath.name,
                "abrogating_collection": filepath.parent.name,
                "abrogated_year": year,
                "abrogated_number": num,
                "context": line.strip()[:200],
            })
    return results


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / "abrogations_raw.parquet"

    md_files = sorted(COLLECTIONS_DIR.glob("*/*.md"))
    print(f"Scanning {len(md_files)} files for abrogations...")

    all_abro = []
    for i, md in enumerate(md_files):
        if i % 5000 == 0:
            print(f"  {i}/{len(md_files)} ({len(all_abro)} abrogations)...", flush=True)
        refs = extract_from_file(md)
        all_abro.extend(refs)

    print(f"\nTotal raw: {len(all_abro)}")

    # Deduplicate
    seen = set()
    unique = []
    for r in all_abro:
        key = (r["abrogating_file"], r["abrogated_year"], r["abrogated_number"])
        if key not in seen:
            seen.add(key)
            unique.append(r)

    print(f"After dedup: {len(unique)}")

    if not unique:
        print("No abrogations found!")
        return 1

    # Save
    import pandas as pd
    df = pd.DataFrame(unique)
    df.to_parquet(output_file, index=False)

    print(f"Saved: {output_file} ({len(df)} rows)")

    # Summary
    print(f"\n=== Top atti abrogati ===")
    top = df.groupby(["abrogated_year", "abrogated_number"]).size().reset_index(name="n").sort_values("n", ascending=False).head(10)
    for _, r in top.iterrows():
        print(f"  {int(r['abrogated_number'])}/{int(r['abrogated_year'])}: abrogato {r['n']} volte")

    n_abrogators = df["abrogating_file"].nunique()
    n_abrogated = df.groupby(["abrogated_year", "abrogated_number"]).ngroups
    print(f"\nAtti che abrogano: {n_abrogators}")
    print(f"Atti abrogati unici: {n_abrogated}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
