"""Estrae metadati da tutte le collezioni legislative del corpus.
Dedup per filename: ogni atto appare una volta con campo 'collezioni' multiplo.

Produce CSV + Parquet in data/derived/.

Uso: python -m lab_tools.extract
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from lab_tools._frontmatter import parse_frontmatter

REPO = Path(__file__).resolve().parent.parent
OUTDIR = REPO / "data" / "derived"
CONFIG_COLLEZIONI = REPO / "config" / "collezioni.txt"

RE_TIPO = re.compile(
    r'^([A-Z\u00c0-\u00d9\s\-]+?)\s+(\d{1,2})\s+([a-zA-Z]+)\s+(\d{4})\s+n\.\s*(\d+)',
    re.MULTILINE,
)
RE_OGGETTO = re.compile(
    r'^={3,}\s*$\s*^(.+?)\s*$\s*^-{3,}', re.MULTILINE | re.DOTALL,
)
RE_VIGORE = re.compile(
    r'Entrata in vigore\s+(?:del\s+)?(?:provvedimento:|del decreto:)?\s*(\d{1,2}/\d{1,2}/\d{4})'
)
RE_CELEX = re.compile(r'CELEX:([A-Z0-9]+)')
RE_DIR_ANNO = re.compile(r'direttiva\s+(\d{4})\s*[/-]\s*\d+', re.IGNORECASE)

MESI = {
    "gennaio": "01", "febbraio": "02", "marzo": "03", "aprile": "04",
    "maggio": "05", "giugno": "06", "luglio": "07", "agosto": "08",
    "settembre": "09", "ottobre": "10", "novembre": "11", "dicembre": "12",
}

FIELDNAMES = [
    "collezione", "filename", "tipo", "data", "numero",
    "oggetto", "entrata_vigore", "celex",
    "anno_atto", "anno_dir", "ritardo",
    "vigente", "urn", "codice_redazionale",
]


def _parse_data(g: str, m: str, a: str) -> str:
    return f"{a}-{MESI.get(m.lower(), '00')}-{g.zfill(2)}"


def _anno_dir(oggetto: str) -> int | None:
    m = RE_DIR_ANNO.search(oggetto or "")
    if m:
        a = int(m.group(1))
        return a if 1950 <= a <= 2030 else None
    return None


def _anno_da_celex(celex: str) -> int | None:
    """Estrae l'anno dal CELEX di tipo L (direttiva) o R (regolamento) più recente.

    Tra CELEX multipli sceglie il più recente, non il primo ordinato.
    Formato: 3YYYYLXXXX (L=directive) o 3YYYYRXXXX (regulation).
    """
    if not celex:
        return None
    anni = []
    for c in celex.split(";"):
        c = c.strip()
        if len(c) >= 6 and c[1:5].isdigit() and c[5:6] in ("L", "R"):
            anno = int(c[1:5])
            if 1950 <= anno <= 2030:
                anni.append(anno)
    return max(anni) if anni else None


def _extract_body_fields(raw: str, filepath: Path) -> dict | None:
    """Estrae tipo/data/numero/oggetto dal body con regex (fallback)."""
    m = RE_TIPO.search(raw)
    if not m:
        return None
    tipo, g, mt, a, num = m.group(1).strip(), m.group(2), m.group(3), m.group(4), m.group(5)
    data = _parse_data(g, mt, a)
    m2 = RE_OGGETTO.search(raw)
    oggetto = m2.group(1).strip() if m2 else filepath.name.replace(".md", "")[:300]
    return {
        "tipo": tipo,
        "data": data,
        "numero": num,
        "oggetto": oggetto,
        "anno_atto": int(a),
        "ritardo": a,  # placeholder per calcolo dopo CELEX
    }


def _extract_celex_vigore(raw: str) -> tuple[str, str]:
    """CELEX + entrata in vigore dal body (comune a frontmatter e legacy)."""
    m3 = RE_VIGORE.search(raw)
    vigore = ""
    if m3:
        gg, mm, aa = m3.group(1).split("/")
        vigore = f"{aa}-{mm.zfill(2)}-{gg.zfill(2)}"
    celex_list = sorted(set(RE_CELEX.findall(raw)))
    celex = ";".join(celex_list)
    return celex, vigore


def extract(filepath: Path, collezione: str = "") -> dict | None:
    raw = filepath.read_text("utf-8", errors="replace")

    # ── Ramo BASE64 (file con nome data_nome) ──
    if re.match(r'^\d{4}-\d{2}-\d{2}_', filepath.name):
        celex = RE_CELEX.findall(raw)
        if not celex:
            return None
        return {"collezione": collezione, "filename": filepath.name,
                "tipo": "BASE64", "data": "", "numero": "",
                "oggetto": filepath.name[:300], "entrata_vigore": "",
                "celex": ";".join(sorted(set(celex))),
                "vigente": None, "urn": "", "codice_redazionale": ""}

    # ── Fast path: frontmatter YAML ──
    fm = parse_frontmatter(raw)
    if fm and fm.get("tipo"):
        tipo = str(fm["tipo"])
        numero = str(fm.get("numero", ""))
        data = str(fm.get("data", ""))
        oggetto = str(fm.get("titolo", "")) or filepath.name.replace(".md", "")[:500]
        vigente = bool(fm.get("vigente", True))
        urn = str(fm.get("urn", ""))
        codice_redazionale = str(fm.get("codice_redazionale", ""))
        celex, vigore = _extract_celex_vigore(raw)
        anno_atto = int(data[:4]) if len(data) >= 4 and data[:4].isdigit() else 0
        anno = _anno_dir(oggetto) or _anno_da_celex(celex)
        ritardo = (anno_atto - anno) if anno and anno <= anno_atto < anno + 100 else None
        return {"collezione": collezione, "filename": filepath.name,
                "tipo": tipo, "data": data, "numero": numero,
                "oggetto": oggetto[:500], "entrata_vigore": vigore,
                "celex": celex, "anno_atto": anno_atto,
                "anno_dir": anno or 0, "ritardo": ritardo,
                "vigente": vigente, "urn": urn,
                "codice_redazionale": codice_redazionale}

    # ── Fallback: regex body (file legacy senza frontmatter) ──
    body = _extract_body_fields(raw, filepath)
    if not body:
        return None
    celex, vigore = _extract_celex_vigore(raw)
    anno = _anno_dir(body.get("oggetto", "")) or _anno_da_celex(celex)
    ritardo = (int(body["anno_atto"]) - anno) if anno and anno <= int(body["anno_atto"]) < anno + 100 else None
    return {"collezione": collezione, "filename": filepath.name,
            "tipo": body["tipo"], "data": body["data"], "numero": body["numero"],
            "oggetto": body["oggetto"][:500], "entrata_vigore": vigore,
            "celex": celex, "anno_atto": body["anno_atto"],
            "anno_dir": anno or 0, "ritardo": ritardo,
            "vigente": None, "urn": "", "codice_redazionale": ""}


def _collezioni_legislative() -> list[Path]:
    """Legge da config/collezioni.txt: solo directory elencate ed esistenti."""
    if not CONFIG_COLLEZIONI.exists():
        return []
    nomi = [line.strip() for line in CONFIG_COLLEZIONI.read_text().splitlines() if line.strip()]
    return sorted(d for d in (REPO / n for n in nomi) if d.is_dir())


def _dedup(records: list[dict]) -> list[dict]:
    """Raggruppa per filename: merge collezioni, tiene primo record."""
    by_file: dict[str, dict] = {}
    for r in records:
        fn = r["filename"]
        if fn in by_file:
            existing = by_file[fn]["collezione"]
            nuova = r["collezione"]
            if nuova and nuova not in existing:
                by_file[fn]["collezione"] = existing + ";" + nuova
        else:
            by_file[fn] = dict(r)
    return list(by_file.values())


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    for col_dir in _collezioni_legislative():
        nome = col_dir.name
        for f in sorted(col_dir.glob("*.md")):
            r = extract(f, collezione=nome)
            if r:
                records.append(r)
    records = _dedup(records)
    if not records:
        print("Nessun atto estratto.")
        return
    csv_path = OUTDIR / "normativa.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(records)
    print(f"TOTALE: {len(records)} atti -> {csv_path}")
    print(f"Con CELEX: {sum(1 for r in records if r['celex'])}")
    try:
        import pandas as pd
        df = pd.DataFrame(records)
        pqt = OUTDIR / "normativa.parquet"
        df.to_parquet(pqt, index=False)
        print(f"Parquet: {pqt} ({len(df)} righe)")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
