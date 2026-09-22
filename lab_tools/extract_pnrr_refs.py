#!/usr/bin/env python3
"""Estrae riferimenti PNRR (missioni, componenti, investimenti) dai testi normativi.

Analizza ogni atto nel corpus italia-corpus e cerca pattern strutturati
del tipo:
  - "Missione N, Componente N, Investimento N.N"
  - "MNCI-N.N" (shorthand)
  - "MNCI-N.N-N" (milestone/target)

Output: pnrr_references.parquet con una riga per riferimento trovato.

Usage:
  python -m lab_tools.extract_pnrr_refs
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import duckdb

COLLECTIONS_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = COLLECTIONS_DIR / "data" / "derived"

# Pattern per estrarre riferimenti PNRR strutturati
# 1. Forma estesa: "Missione N, Componente N, Investimento N.N"
MISSIONE_PATTERN = re.compile(
    r"(?:Missione|m)\s*(\d+)\s*,?\s*(?:Componente|c)\s*(\d+)"
    r"(?:\s*,?\s*(?:Investimento|i)\s*(\d+)\.(\d+))?"
    r"(?:\s*,?\s*(?:Subinvestimento|subinvestimento|Sub)\s*(\d+)\.(\d+)\.(\d+))?"
    r"(?:\s*,?\s*(?:Riforma|r)\s*(\d+(?:\.\d+)?))?"
    r"(?:\s+del\s+PNRR)?",
    re.IGNORECASE
)

# 2. Shorthand: "M1C2-I1.7" o "M6C1-4" (milestone)
SHORTHAND_PATTERN = re.compile(
    r"M(\d)C(\d)(?:-(?:I(\d+)\.(\d+)|(\d+)))?"
)

# 3. Milestone/target: "M1C1-60" o "M6C1-4"
MILESTONE_PATTERN = re.compile(
    r"(?:Milestone|Target|traguardo|obiettivo)\s+M(\d)C(\d)-(\d+)",
    re.IGNORECASE
)


def extract_pnrr_refs(text: str) -> list[dict]:
    """Estrai tutti i riferimenti PNRR da un testo."""
    refs = []

    # Forma estesa
    for m in MISSIONE_PATTERN.finditer(text):
        missione, componente = int(m.group(1)), int(m.group(2))
        investimento = f"{m.group(3)}.{m.group(4)}" if m.group(3) else None
        subinvestimento = f"{m.group(5)}.{m.group(6)}.{m.group(7)}" if m.group(5) else None
        riforma = m.group(8)
        refs.append({
            "tipo": "missione",
            "missione": missione,
            "componente": componente,
            "investimento": investimento,
            "subinvestimento": subinvestimento,
            "riforma": riforma,
            "snippet": text[max(0, m.start()-20):m.end()+20],
        })

    # Shorthand
    for m in SHORTHAND_PATTERN.finditer(text):
        missione, componente = int(m.group(1)), int(m.group(2))
        investimento = f"{m.group(3)}.{m.group(4)}" if m.group(3) else None
        milestone = m.group(5)
        refs.append({
            "tipo": "shorthand",
            "missione": missione,
            "componente": componente,
            "investimento": investimento,
            "subinvestimento": None,
            "riforma": None,
            "milestone": milestone,
            "snippet": text[max(0, m.start()-20):m.end()+20],
        })

    # Milestone/target
    for m in MILESTONE_PATTERN.finditer(text):
        refs.append({
            "tipo": "milestone",
            "missione": int(m.group(1)),
            "componente": int(m.group(2)),
            "milestone_id": m.group(3),
            "snippet": text[max(0, m.start()-20):m.end()+20],
        })

    return refs


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / "pnrr_references.parquet"

    all_refs = []
    md_files = sorted(COLLECTIONS_DIR.glob("*/*.md"))
    print(f"Scanning {len(md_files)} files...")

    for i, md in enumerate(md_files):
        if i % 5000 == 0 and i > 0:
            print(f"  {i}/{len(md_files)} ({len(all_refs)} refs found)...")
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Only scan if file mentions PNRR
        if "PNRR" not in text and "pnrr" not in text.lower():
            continue

        refs = extract_pnrr_refs(text)
        for ref in refs:
            ref["filename"] = md.name
            ref["collection"] = md.parent.name
        all_refs.extend(refs)

    print(f"\nTotal: {len(all_refs)} PNRR references in {len(md_files)} files")

    if not all_refs:
        print("No references found!")
        return 1

    # Write to parquet via DuckDB
    import json
    tmp_file = OUTPUT_DIR / "_tmp_pnrr_refs.json"
    tmp_file.write_text(json.dumps(all_refs, ensure_ascii=False))
    con = duckdb.connect(":memory:")
    con.execute(f"CREATE TABLE refs AS SELECT * FROM read_json_auto('{tmp_file}')")
    con.execute(f"COPY refs TO '{output_file}' (FORMAT PARQUET, COMPRESSION 'zstd')")

    n = con.execute("SELECT COUNT(*) FROM refs").fetchone()[0]
    print(f"Saved: {output_file} ({n} rows)")

    # Summary
    by_missione = con.execute("""
        SELECT missione, componente, COUNT(*) as cnt
        FROM refs
        WHERE missione IS NOT NULL
        GROUP BY missione, componente
        ORDER BY missione, componente
    """).fetchall()
    print(f"\nBy missione/componente:")
    for r in by_missione:
        print(f"  M{r[0]}C{r[1]}: {r[2]} refs")

    # Unique acts
    unique_acts = con.execute("SELECT COUNT(DISTINCT filename) FROM refs").fetchone()[0]
    print(f"\nUnique acts with PNRR refs: {unique_acts}")

    con.close()
    tmp_file.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
