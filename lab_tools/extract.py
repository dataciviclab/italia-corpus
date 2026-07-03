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
# Atti UE: singolari e plurali, con/senza (UE), n., delegato/di esecuzione
# Cattura 3 gruppi: (tipo_parola, anno, numero)
# L'anno è il primo gruppo di 4 cifre prima dello slash; in formato
# "n. 1025/2012" l'anno è DOPO lo slash e viene scambiato in _estrai_riferimento_ue.
RE_DOC_UE = re.compile(
    r'(?:direttiva|regolamento|decisione|direttive|regolamenti|decisioni)\s*'
    r'(?:delegat[oa]\s*|di\s+esecuzione\s*)?'
    r'(?:\(?\s*UE\s*\)?\s*)?'
    r'(?:n\.?\s*)?'
    r'\(?(\d{4})\)?\s*[/-]\s*(\d+)',
    re.IGNORECASE,
)
_TIPO_CELEX = {"direttiva": "L", "regolamento": "R", "decisione": "D",
               "direttive": "L", "regolamenti": "R", "decisioni": "D"}

MESI = {
    "gennaio": "01", "febbraio": "02", "marzo": "03", "aprile": "04",
    "maggio": "05", "giugno": "06", "luglio": "07", "agosto": "08",
    "settembre": "09", "ottobre": "10", "novembre": "11", "dicembre": "12",
}

FIELDNAMES = [
    "collezione", "filename", "tipo", "data", "numero",
    "oggetto", "celex",
    "anno_atto", "anno_dir", "ritardo",
    "vigente", "urn", "codice_redazionale",
    "lunghezza_caratteri", "lunghezza_parole", "riferimenti_interni",
]


def _parse_data(g: str, m: str, a: str) -> str:
    return f"{a}-{MESI.get(m.lower(), '00')}-{g.zfill(2)}"


def _estrai_riferimento_ue(oggetto: str) -> tuple[str | None, int | None]:
    """Estrae tipo, anno e numero del PRIMO riferimento UE non secondario.
    
      'direttiva 2019/944' -> (32019L0944, 2019)
      'regolamento (UE) n. 1025/2012' -> (32012R1025, 2012)
    
    Riferimenti secondari (preceduti da 'abroga', 'modifica', ecc.)
    vengono saltati in favore del primo match principale.
    Se anno catturato non è nel range 1950-2030 (es. formato
    'n. 1025/2012'), anno e numero vengono scambiati.
    """
    matches = list(RE_DOC_UE.finditer(oggetto or ""))
    if not matches:
        return "", None

    parole_secondarie = frozenset(['abroga', 'abrogata', 'sostituisce',
        'sostituita', 'modifica', 'deroga', 'derogata'])

    def _e_principale(m) -> bool:
        """True se il match NON è preceduto da parole secondarie."""
        start = max(0, m.start() - 60)
        prefix = (oggetto or "")[start:m.start()].lower()
        return not any(w in prefix for w in parole_secondarie)

    # Cerca il primo match principale
    target = None
    for m in matches:
        if _e_principale(m):
            target = m
            break
    if target is None:
        target = matches[0]  # fallback: primo match assoluto

    # Identifica il tipo (direttiva/regolamento/decisione) dalla parola matchata
    full_text = target.group(0).lower()
    tipo = None
    for t in _TIPO_CELEX:
        if full_text.startswith(t):
            tipo = t
            break
    if not tipo:
        return "", None

    anno_candidato = int(target.group(1))
    num = target.group(2)

    # Se l'anno candidato non è valido, swap (formato 'n. 1025/2012')
    if not (1950 <= anno_candidato <= 2030):
        anno_valido = int(num)
        if not (1950 <= anno_valido <= 2030):
            return "", None
        celex = f"3{anno_valido:04d}{_TIPO_CELEX.get(tipo, 'X')}{anno_candidato:04d}"
        return celex, anno_valido

    anno = anno_candidato
    codice = _TIPO_CELEX.get(tipo, "X")
    celex = f"3{anno:04d}{codice}{int(num):04d}"
    return celex, anno


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


def _get_body(raw: str) -> str:
    """Estrae il body dal testo markdown, saltando il frontmatter YAML."""
    if raw.startswith("---"):
        end = raw.find("---", 3)
        if end >= 0:
            return raw[end + 3:].strip()
    return raw.strip()


def _body_metrics(body: str) -> dict:
    """Calcola metriche testuali dal body di un atto normativo.

    Restituisce lunghezza_caratteri, lunghezza_parole, riferimenti_interni.
    """
    return {
        "lunghezza_caratteri": len(body),
        "lunghezza_parole": len(body.split()) if body else 0,
        "riferimenti_interni": body.count("../"),
    }


def extract(filepath: Path, collezione: str = "") -> dict | None:
    raw = filepath.read_text("utf-8", errors="replace")
    body = _get_body(raw)
    metrics = _body_metrics(body)

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
        anno_atto = int(data[:4]) if len(data) >= 4 and data[:4].isdigit() else 0
        celex, anno = _estrai_riferimento_ue(oggetto)
        ritardo = (anno_atto - anno) if anno and anno <= anno_atto < anno + 100 else None
        return {"collezione": collezione, "filename": filepath.name,
                "tipo": tipo, "data": data, "numero": numero,
                "oggetto": oggetto[:500],
                "celex": celex or "", "anno_atto": anno_atto,
                "anno_dir": anno or 0, "ritardo": ritardo,
                "vigente": vigente, "urn": urn,
                "codice_redazionale": codice_redazionale,
                **metrics}

    # ── Fallback: regex body (file legacy senza frontmatter) ──
    body = _extract_body_fields(raw, filepath)
    if not body:
        return None
    celex, anno = _estrai_riferimento_ue(body.get("oggetto", ""))
    ritardo = (int(body["anno_atto"]) - anno) if anno and anno <= int(body["anno_atto"]) < anno + 100 else None
    return {"collezione": collezione, "filename": filepath.name,
            "tipo": body["tipo"], "data": body["data"], "numero": body["numero"],
            "oggetto": body["oggetto"][:500],
            "celex": celex or "", "anno_atto": body["anno_atto"],
            "anno_dir": anno or 0, "ritardo": ritardo,
            "vigente": None, "urn": "", "codice_redazionale": "",
            **metrics}


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
