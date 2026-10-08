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

from lab_tools._paths import COLLEZIONI_ROOT, CONFIG_COLLEZIONI, OUTDIR, REPO

NORMATIVA_PARQUET = OUTDIR / "normativa.parquet"

RE_LINK = re.compile(r'\.\./([^)]+?)\.md')


def _collezioni_legislative() -> list[Path]:
    """Legge da config/collezioni.txt: solo directory elencate ed esistenti."""
    if not CONFIG_COLLEZIONI.exists():
        return []
    nomi = [line.strip() for line in CONFIG_COLLEZIONI.read_text().splitlines() if line.strip()]
    return sorted(d for d in (COLLEZIONI_ROOT / n for n in nomi) if d.is_dir())


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
                "materia": row.get("materia", ""),
                "stato": row.get("stato", ""),
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
    risolti = sum(1 for a in archi if a["risolto"])
    non_risolti = total - risolti
    by_orig = Counter(a.get("origine", "regex") for a in archi)

    print("\n📊 Grafo riferimenti — metriche")
    print(f"{'='*40}")
    print(f"  Archi totali:        {total:>8,}")
    print(f"  Risolvibili:         {risolti:>8,} ({risolti/total*100:.1f}%)" if total else "")
    print(f"  Non risolvibili:     {non_risolti:>8,} ({non_risolti/total*100:.1f}%)" if total else "")
    print(f"  Per origine:         {dict(by_orig)}")
    print(f"  Atti citanti (fonti): {len(fonti):>8,}")
    print(f"  Atti citati (bers.): {len(citati):>8,}")
    print(f"  File nel corpus:     {file_set_size:>8,}")

    # Top citati (solo risolti)
    if risolti > 0:
        counter = Counter()
        for a in archi:
            if a["risolto"]:
                counter[(a["bersaglio_filename"])] += a["peso"]
        print("\n  Top 10 atti più citati:")
        for path, count in counter.most_common(10):
            short = path[:70]
            print(f"    {count:5d}x  {short}")


def _load_urn_to_filename() -> dict[str, str]:
    """urn -> filename da normativa.parquet (per join AKN)."""
    try:
        import pandas as pd
    except ImportError:
        return {}
    if not NORMATIVA_PARQUET.exists():
        return {}
    df = pd.read_parquet(NORMATIVA_PARQUET, columns=["urn", "filename"])
    df = df.dropna(subset=["urn"])
    return dict(zip(df["urn"], df["filename"]))


def _archi_da_akn_relations(
    normativa: dict[str, dict],
    urn_to_fn: dict[str, str],
) -> list[dict]:
    """Cita AKN (origin=ref) con entrambe le estremità risolte nel corpus.

    Aggiunge archi con origine='akn', peso=1. Non sovrascrive il grafo regex:
    il consumatore distingue da colonna `origine`.
    """
    akn_path = OUTDIR / "akn_relations.parquet"
    if not akn_path.exists() or not urn_to_fn:
        print("  akn_relations.parquet assente o nessun URN — union AKN saltata")
        return []

    try:
        import pandas as pd
    except ImportError:
        return []

    df = pd.read_parquet(akn_path)
    if df.empty or "origin" not in df.columns:
        return []
    cit = df[df["origin"] == "ref"].copy()
    if cit.empty:
        print("  Nessuna citation AKN — union saltata")
        return []

    archi: list[dict] = []
    n_skip = 0
    for _, row in cit.iterrows():
        f_urn, t_urn = row.get("fonte_urn"), row.get("target_urn")
        f_fn = urn_to_fn.get(f_urn)
        t_fn = urn_to_fn.get(t_urn)
        if not f_fn or not t_fn:
            n_skip += 1
            continue
        f_meta = normativa.get(Path(f_fn).name, {})
        t_meta = normativa.get(Path(t_fn).name, {})
        archi.append(
            {
                "fonte_filename": f_fn,
                "fonte_collezione": f_meta.get("collezione", ""),
                "fonte_anno": f_meta.get("anno_atto", 0),
                "fonte_tipo": f_meta.get("tipo", ""),
                "fonte_materia": f_meta.get("materia", ""),
                "fonte_stato": f_meta.get("stato", ""),
                "bersaglio_filename": Path(t_fn).name,
                "bersaglio_path": t_fn,
                "bersaglio_collezione": t_meta.get("collezione", ""),
                "bersaglio_anno": t_meta.get("anno_atto", 0),
                "bersaglio_tipo": t_meta.get("tipo", ""),
                "bersaglio_materia": t_meta.get("materia", ""),
                "bersaglio_stato": t_meta.get("stato", ""),
                "peso": 1,
                "risolto": True,
                "origine": "akn",
                "rel_type": "citation",
            }
        )
    print(f"  AKN citations in corpus: {len(archi)} (skip esterne: {n_skip})")
    return archi


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

                risolto = bersaglio_path in file_set if bersaglio_path else False

                # Metadati fonte
                fonte_meta = normativa.get(relpath.name, {})
                # Metadati bersaglio (solo se risolto)
                bersaglio_meta = normativa.get(bersaglio_fn, {}) if risolto else {}
                # Path vuoto se non risolto — il consumer non deve fare ipotesi
                bp = bersaglio_path if risolto else ""

                arco = {
                    "fonte_filename": str(relpath),
                    "fonte_collezione": nome_collezione,
                    "fonte_anno": fonte_meta.get("anno_atto", 0),
                    "fonte_tipo": fonte_meta.get("tipo", ""),
                    "fonte_materia": fonte_meta.get("materia", ""),
                    "fonte_stato": fonte_meta.get("stato", ""),
                    "bersaglio_filename": bersaglio_fn,
                    "bersaglio_path": bp or "",
                    "bersaglio_collezione": bersaglio_meta.get("collezione", ""),
                    "bersaglio_anno": bersaglio_meta.get("anno_atto", 0),
                    "bersaglio_tipo": bersaglio_meta.get("tipo", ""),
                    "bersaglio_materia": bersaglio_meta.get("materia", ""),
                    "bersaglio_stato": bersaglio_meta.get("stato", ""),
                    "peso": peso,
                    "risolto": risolto,
                    "origine": "regex",
                    "rel_type": "citation",
                }
                archi.append(arco)

    print("Union AKN (citation strutturate)...")
    urn_to_fn = _load_urn_to_filename()
    archi.extend(_archi_da_akn_relations(normativa, urn_to_fn))

    _stampa_metriche(archi, len(file_set))

    # Salva Parquet (il CSV è ignorato da git, solo locale)
    try:
        import pandas as pd
        df = pd.DataFrame(archi)
        # colonna origine sempre presente
        if "origine" not in df.columns:
            df["origine"] = "regex"
        pqt = OUTDIR / "riferimenti.parquet"
        df.to_parquet(pqt, index=False)
        print(f"Parquet: {pqt} ({len(df)} righe, {len(df.columns)} colonne)")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
