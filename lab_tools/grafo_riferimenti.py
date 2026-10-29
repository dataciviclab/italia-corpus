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

from lab_tools._paths import COLLEZIONI_ROOT, CONFIG_COLLEZIONI, OUTDIR
from lab_tools.identity import build_indice_identita, data_codice
from lab_tools.urn import expand_index
from lab_tools.urn import lookup as urn_lookup
from lab_tools.urn import regola as urn_regola

NORMATIVA_PARQUET = OUTDIR / "normativa.parquet"

RE_LINK = re.compile(r'\.\./([^)]+?)\.md')

# Soglia dell'invariante: **bersagli distinti** regex non risolti ammessi.
# Oggi 6 (gli XML che il fetch non è riuscito a convertire); prima del churn
# erano ~6-11, dopo il churn 1.262. Il conteggio per bersaglio (non per link)
# rende il gate robusto a quanti link puntano allo stesso atto mancante.
MAX_REGEX_BERSAGLI_NON_RISOLTI = 50

# Max context length stored per side (chars). Total evidence ≤ 2 * _CTX_MAX + link text.
_CTX_MAX = 120


def _collezioni_legislative() -> list[Path]:
    """Legge da config/collezioni.txt: solo directory elencate ed esistenti."""
    if not CONFIG_COLLEZIONI.exists():
        return []
    nomi = [line.strip() for line in CONFIG_COLLEZIONI.read_text().splitlines() if line.strip()]
    return sorted(d for d in (COLLEZIONI_ROOT / n for n in nomi) if d.is_dir())


def _build_file_set() -> set[str]:
    """Path dei .md relativi a COLLEZIONI_ROOT (es. "Codici/x.md").

    Stesso formato di prima del move sotto collezioni/: il parquet
    non cambia contratto al prossimo build.
    """
    files: set[str] = set()
    for col_dir in _collezioni_legislative():
        for f in col_dir.glob("*.md"):
            files.add(str(f.relative_to(COLLEZIONI_ROOT)))
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
                # identità (#88): serve a scegliere l'espressione corrente quando
                # lo stesso atto ha più versioni nel corpus
                "is_current": bool(row.get("is_current", False)),
            }
    return lookup


def estrai_link(body: str) -> list[str]:
    """Estrae i path dei link ../ da un body markdown, decodificati."""
    links = RE_LINK.findall(body)
    return [urllib.parse.unquote(link) + ".md" for link in links]


def estrai_link_con_contesto(body: str) -> list[tuple[str, str]]:
    """Estrae (path_decodificato, contesto) per ogni link ../ nel body.

    Usa RE_LINK per i path (stessa semantica di findall, non-overlapping)
    e poi localizza ogni occorrenza per catturare il contesto ±_CTX_MAX char.

    Il contesto è lo snippet di testo attorno al link, usato come evidence
    nei riferimenti del grafo.

    Returns:
        Lista di (path_decodificato, contesto) — una riga per occorrenza,
        non deduplicata (il caller fa il counting per peso).
    """
    results: list[tuple[str, str]] = []
    # Trova tutte le posizioni dei link con RE_LINK (non-overlapping, come findall)
    for m in RE_LINK.finditer(body):
        path_raw = m.group(1)
        path_decoded = urllib.parse.unquote(path_raw) + ".md"
        # Contesto: ±_CTX_MAX char attorno al match, con bound di sicurezza
        start = max(0, m.start() - _CTX_MAX)
        end = min(len(body), m.end() + _CTX_MAX)
        raw_ctx = body[start:end]
        # Normalizza whitespace
        contesto = re.sub(r'\s+', ' ', raw_ctx).strip()
        results.append((path_decoded, contesto))
    return results


def risolvi_path(link_decoded: str, current_relpath: Path) -> Path | None:
    """Risolve un link relativo ../ in path relativo a COLLEZIONI_ROOT.

    I path del corpus sono sorelle sotto collezioni/ (es.
    ``DL proroghe/x.md`` → link ``../Codici/y.md`` → ``Codici/y.md``).

    Args:
        link_decoded: path decodificato (es. 'Codici/y.md')
        current_relpath: path del file corrente relativo a COLLEZIONI_ROOT

    Returns:
        Path relativo a COLLEZIONI_ROOT oppure None se non risolvibile.
    """
    parent = current_relpath.parent
    if str(parent) == ".":
        return None  # file in root collezioni, ../ salirebbe sopra
    resolved = (parent.parent / link_decoded)
    # Normalizza senza risolvere symlink/FS: solo rimozione di . e ..
    parts: list[str] = []
    for part in resolved.parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)
    if not parts:
        return None
    return Path(*parts)


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
    # alias (slug, anno+numero, codici): vedi lab_tools/urn.py
    return expand_index(zip(df["urn"], df["filename"]))


def _chiave_arco(a: dict) -> tuple[str, str, str]:
    """Chiave dell'arco = PK del clean (fonte_source_path, bersaglio_source_path,
    origine), derivata **esattamente** come in
    `datasets/riferimenti/sql/clean.sql`.

    Attenzione al caso **regex non risolto**: `bersaglio_path` è vuoto e la PK
    usa `bersaglio_filename` (il link grezzo). Usare `bersaglio_path` nudo
    fonderebbe tutti gli unresolved di un file in una sola chiave.
    """
    fonte_fn = a.get("fonte_filename") or ""
    bersaglio_fn = a.get("bersaglio_filename") or ""
    fonte_col = a.get("fonte_collezione") or ""
    bersaglio_path = a.get("bersaglio_path") or ""

    if "/" in fonte_fn:
        fonte_source_path = fonte_fn
    elif fonte_col:
        fonte_source_path = f"{fonte_col}/{fonte_fn}"
    else:
        fonte_source_path = fonte_fn

    if bersaglio_path:
        bersaglio_source_path = bersaglio_path
    elif "/" in bersaglio_fn:
        bersaglio_source_path = bersaglio_fn
    elif fonte_col:
        bersaglio_source_path = f"{fonte_col}/{bersaglio_fn}"
    else:
        bersaglio_source_path = bersaglio_fn

    return (fonte_source_path, bersaglio_source_path, a.get("origine") or "")


def _dedup_archi(archi: list[dict]) -> list[dict]:
    """Un arco per chiave (vedi `_chiave_arco`), `peso` sommato.

    L'alias URN (`lab_tools/urn.py`) risolve forme diverse della stessa
    citazione sullo stesso file: senza dedup due righe AKN produrrebbero lo
    stesso arco e la PK del clean fallirebbe.
    """
    distinti: dict[tuple[str, str, str], dict] = {}
    for a in archi:
        k = _chiave_arco(a)
        if k in distinti:
            distinti[k]["peso"] += a["peso"]
        else:
            distinti[k] = a
    return list(distinti.values())


def _verifica_pk_unica(archi: list[dict]) -> None:
    """Solleva se la PK del clean non è unica.

    Usata **dopo** `_dedup_archi`: è un'invariante di costruzione, non una
    guardia sui dati grezzi (una guardia sui grezzi fallirebbe per condizioni
    legittime, es. link regex non risolti).
    """
    chiavi = [_chiave_arco(a) for a in archi]
    if len(chiavi) != len(set(chiavi)):
        raise AssertionError(
            f"dedup incompleto: {len(chiavi) - len(set(chiavi))} archi duplicati sulla PK"
        )


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
    n_target_ok = 0
    # contatori per regola + invariante: ogni riga di input finisce in una classe
    conteggi: Counter[str] = Counter()
    for _, row in cit.iterrows():
        f_urn, t_urn = row.get("fonte_urn"), row.get("target_urn")
        f_fn = urn_lookup(urn_to_fn, f_urn)
        t_fn = urn_lookup(urn_to_fn, t_urn)
        if t_fn:
            n_target_ok += 1
        if not f_fn or not t_fn:
            n_skip += 1
            conteggi[
                "skip:entrambe" if not f_fn and not t_fn else ("skip:fonte" if not f_fn else "skip:bersaglio")
            ] += 1
            continue
        conteggi[f"bersaglio:{urn_regola(urn_to_fn, t_urn)}"] += 1
        conteggi[f"fonte:{urn_regola(urn_to_fn, f_urn)}"] += 1
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
                # AKN citations: evidence dal campo origin ('ref'), non da contesto testuale
                "contesto": f"akn:{row.get('origin', 'ref')}",
            }
        )
    # invariante: ogni riga di input è classificata (2 voci se risolta: fonte e
    # bersaglio; 1 se scartata). Se non torna, c'è un ramo non contato.
    classificate = sum(conteggi.values())
    if classificate != len(cit) + len(archi):
        raise ValueError(
            f"conteggi AKN incoerenti: {classificate} != {len(cit)} input + {len(archi)} archi"
        )
    # invariante di copertura: se `urn.lookup` regredisse, gli archi risolti
    # crollerebbero rispetto ai bersagli presenti nell'indice.
    if n_target_ok and len(archi) < 0.95 * n_target_ok:
        raise ValueError(
            f"invariante AKN: {len(archi)} archi risolti su {n_target_ok} bersagli "
            f"nell'indice (soglia 95%) — possibile regressione di urn.lookup"
        )
    per_regola = Counter(
        {k.split(":", 1)[1]: v for k, v in conteggi.items() if k.startswith("bersaglio:")}
    )
    print(f"  AKN citations in corpus: {len(archi)} (skip esterne: {n_skip})")
    print(f"  AKN per regola (bersaglio): {dict(per_regola.most_common())}")
    print(f"  AKN skip: {dict((k, v) for k, v in conteggi.items() if k.startswith('skip:'))}")

    # Dedup per coppia risolta (fonte, bersaglio, origine): l'alias URN
    # (lab_tools/urn.py) fa risolvere forme diverse della stessa citazione sullo
    # stesso file, quindi due righe AKN possono produrre lo stesso arco.
    distinti = _dedup_archi(archi)
    if len(distinti) != len(archi):
        print(f"  AKN archi collassati (stessa coppia via alias URN): {len(archi) - len(distinti)}")
        print(f"  AKN archi distinti: {len(distinti)}")
    return distinti


def _risolvi_bersaglio(
    link_decoded: str,
    relpath: Path,
    file_set: set[str],
    indice_identita: dict[str, str],
) -> tuple[str | None, str, bool, bool]:
    """Risolvi un link per path e, se serve, per identità.

    Il fetch aggiorna gli snapshot e **cambia il filename** (`_ORIGINALE_` →
    `_VIGENZA_2026-02-25_`): un link al nome vecchio non è nel `file_set`. In
    quel caso si ripiega su `data_codice`, che è 1:1 con l'atto.

    Returns:
        (bersaglio_path, bersaglio_filename, risolto, via_identita)
    """
    resolved = risolvi_path(link_decoded, relpath)
    bersaglio_path = str(resolved) if resolved is not None else None

    if bersaglio_path and bersaglio_path in file_set:
        return bersaglio_path, Path(bersaglio_path).name, True, False

    cod = data_codice(link_decoded) or data_codice(bersaglio_path or "")
    candidato = indice_identita.get(cod) if cod else None
    if candidato:
        return candidato, Path(candidato).name, True, True

    fn = Path(bersaglio_path).name if bersaglio_path else link_decoded
    return bersaglio_path, fn, False, False


def _verifica_invarianti(archi: list[dict], file_set: set[str]) -> None:
    """Gate sulla risoluzione: blocca il run se il corpus è degradato.

    Non basta stampare le metriche: 11 → 44.079 link non risolti è passato
    silenzioso per un intero build. Questi controlli falliscono con i numeri
    nel messaggio (stessa forma del contract check di CI).
    """
    basenames = {Path(p).name for p in file_set}

    regex = [a for a in archi if a.get("origine") == "regex"]
    non_risolti = [a for a in regex if not a.get("risolto")]
    bersagli_non_risolti = {a.get("bersaglio_filename") for a in non_risolti}
    if len(bersagli_non_risolti) > MAX_REGEX_BERSAGLI_NON_RISOLTI:
        raise ValueError(
            f"invariante: {len(bersagli_non_risolti)} bersagli regex non risolti "
            f"({len(non_risolti)} link, max {MAX_REGEX_BERSAGLI_NON_RISOLTI} bersagli) "
            f"— possibile churn di filename: i link puntano a nomi vecchi "
            f"(vedi _risolvi_bersaglio)"
        )
    if bersagli_non_risolti:
        esempi = ", ".join(sorted(bersagli_non_risolti)[:6])
        print(
            f"  ⚠ bersagli non risolti (atti assenti dal corpus): "
            f"{len(bersagli_non_risolti)} ({len(non_risolti)} link) — {esempi}"
        )

    fantasmi = [
        a for a in archi if a.get("risolto") and a.get("bersaglio_filename") not in basenames
    ]
    if fantasmi:
        raise ValueError(
            f"invariante: {len(fantasmi)} archi risolti su bersagli inesistenti "
            f"(es. {fantasmi[0].get('bersaglio_filename')})"
        )

    fonti_fantasma = [
        a
        for a in archi
        if a.get("risolto")
        and a.get("fonte_filename") not in file_set
        and a.get("fonte_filename") not in basenames
    ]
    if fonti_fantasma:
        raise ValueError(
            f"invariante: {len(fonti_fantasma)} archi con fonte inesistente "
            f"(es. {fonti_fantasma[0].get('fonte_filename')})"
        )


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)

    print("Costruzione file set...")
    file_set = _build_file_set()
    print(f"  {len(file_set)} file .md trovati")

    print("Caricamento normativa.parquet...")
    normativa = _load_normativa_lookup()
    print(f"  {len(normativa)} atti caricati")

    # Indice identità: data_codice -> espressione corrente. Serve al fallback
    # quando il link punta a un filename che il fetch ha rinominato.
    correnti = {fn for fn, meta in normativa.items() if meta.get("is_current")}
    indice_identita = build_indice_identita(file_set, correnti)
    print(f"  indice identità: {len(indice_identita)} atti (data_codice)")

    print("Estrazione link dai body...")
    archi: list[dict] = []
    n_fallback_identita = 0
    for col_dir in _collezioni_legislative():
        nome_collezione = col_dir.name
        for f in sorted(col_dir.glob("*.md")):
            relpath = f.relative_to(COLLEZIONI_ROOT)
            try:
                raw = f.read_text("utf-8", errors="replace")
            except Exception:
                continue

            links_ctx = estrai_link_con_contesto(raw)
            if not links_ctx:
                continue

            # Conta occorrenze per link unico + raccogli il contesto
            # (primo contesto trovato per ogni link unico, come evidence)
            peso_counter: dict[str, int] = {}
            contesto_first: dict[str, str] = {}
            for link_decoded, contesto in links_ctx:
                peso_counter[link_decoded] = peso_counter.get(link_decoded, 0) + 1
                if link_decoded not in contesto_first and contesto:
                    contesto_first[link_decoded] = contesto

            for link_decoded, peso in peso_counter.items():
                bersaglio_path, bersaglio_fn, risolto, via_identita = _risolvi_bersaglio(
                    link_decoded, relpath, file_set, indice_identita
                )
                if via_identita:
                    n_fallback_identita += 1

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
                    "contesto": contesto_first.get(link_decoded, ""),
                }
                archi.append(arco)

    print("Union AKN (citation strutturate)...")
    urn_to_fn = _load_urn_to_filename()
    archi.extend(_archi_da_akn_relations(normativa, urn_to_fn))

    # Un arco per chiave = PK del clean (fonte_source_path, bersaglio_source_path,
    # origine). Il dedup AKN copre la causa nota (alias URN); qui si applica
    # all'**unione** (regex + AKN) perché anche due link regex diversi possono
    # risolvere allo stesso bersaglio. `peso` sommato. Così la PK regge per
    # costruzione, invece di far fallire la build su una condizione di dato.
    n_prima = len(archi)
    archi = _dedup_archi(archi)
    if len(archi) != n_prima:
        print(f"  archi collassati sull'unione (PK clean): {n_prima - len(archi)}")
    _verifica_pk_unica(archi)

    if n_fallback_identita:
        print(f"  risolti per identità (data_codice): {n_fallback_identita}")
    _verifica_invarianti(archi, file_set)

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
