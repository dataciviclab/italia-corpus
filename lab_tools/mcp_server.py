"""Server MCP italia-corpus — cerca con ripgrep nel corpus normativo.
Output strutturato (list[dict]) per agenti AI, con supporto AND multi-termine
(documentale, non per riga), paginazione offset e tool per recupero full text.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

from lab_connectors.mcp import create_mcp_server, guard_timed

from lab_tools._frontmatter import read_frontmatter

CORPUS = Path(__file__).resolve().parent.parent
CONFIG_COLLEZIONI = CORPUS / "config" / "collezioni.txt"
NORMATIVA_PARQUET = CORPUS / "data" / "derived" / "normativa.parquet"
RIFERIMENTI_PARQUET = CORPUS / "data" / "derived" / "riferimenti.parquet"

_QUERY_MAX_WORDS = 8
_MAX_LIMIT = 100
_RG_LIST_MATCHES = 3

# Campi di qualità da normativa.parquet da esporre nei risultati MCP
_QUALITY_FIELDS = ("stato", "qualita_score", "orfano", "n_citazioni", "duplicato", "materia", "sunsetting_score")


# ─── helpers interni ──────────────────────────────────────────────


def _leggi_collezioni() -> set[str]:
    """Legge l'elenco delle collezioni vive da config/collezioni.txt."""
    if not CONFIG_COLLEZIONI.exists():
        return set()
    return {line.strip() for line in CONFIG_COLLEZIONI.read_text().splitlines() if line.strip()}


@lru_cache(maxsize=1)
def _load_quality_lookup() -> dict[str, dict[str, Any]]:
    """Carica normativa.parquet e costruisce lookup filename → campi qualità.

    Cacheata: il parquet cambia solo con il CI (giornaliero).
    Se pandas o il parquet non sono disponibili, ritorna dict vuoto.
    """
    if not NORMATIVA_PARQUET.exists():
        return {}
    try:
        import pandas as pd
    except ImportError:
        return {}
    try:
        df = pd.read_parquet(NORMATIVA_PARQUET)
    except Exception:
        return {}
    lookup: dict[str, dict[str, Any]] = {}
    cols = [c for c in _QUALITY_FIELDS if c in df.columns]
    if "filename" not in df.columns:
        return {}
    for _, row in df.iterrows():
        fn = row.get("filename", "")
        if fn:
            lookup[fn] = {c: row.get(c) for c in cols}
    return lookup


@lru_cache(maxsize=1)
def _load_graph_lookup() -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """Carica riferimenti.parquet e costruisce indici bidirezionali.

    Indicizza per basename (senza path) per coerenza con quality lookup.

    Returns:
        (outgoing, incoming):
        - outgoing: fonte_basename → lista {bersaglio_filename, bersaglio_collezione,
          bersaglio_tipo, bersaglio_anno, peso}
        - incoming: bersaglio_basename → lista {fonte_filename, fonte_collezione,
          fonte_tipo, fonte_anno, peso}
    """
    if not RIFERIMENTI_PARQUET.exists():
        return {}, {}
    try:
        import pandas as pd
    except ImportError:
        return {}, {}
    try:
        df = pd.read_parquet(RIFERIMENTI_PARQUET)
    except Exception:
        return {}, {}

    df = df[df["risolto"] == True]  # noqa: E712

    outgoing: dict[str, list[dict]] = {}
    incoming: dict[str, list[dict]] = {}

    for _, row in df.iterrows():
        # Indicizza per basename (senza path di collezione)
        ff = Path(str(row.get("fonte_filename", ""))).name
        bf = Path(str(row.get("bersaglio_filename", ""))).name
        if not ff or not bf:
            continue
        peso = int(row.get("peso", 1))

        if ff not in outgoing:
            outgoing[ff] = []
        outgoing[ff].append({
            "filename": bf,
            "collezione": row.get("bersaglio_collezione", ""),
            "tipo": row.get("bersaglio_tipo", ""),
            "anno": int(row.get("bersaglio_anno", 0) or 0),
            "peso": peso,
        })

        if bf not in incoming:
            incoming[bf] = []
        incoming[bf].append({
            "filename": ff,
            "collezione": row.get("fonte_collezione", ""),
            "tipo": row.get("fonte_tipo", ""),
            "anno": int(row.get("fonte_anno", 0) or 0),
            "peso": peso,
        })

    # Raggruppa per target e somma pesi
    def _aggregate(edges: list[dict]) -> list[dict]:
        by_target: dict[str, dict] = {}
        for e in edges:
            fn = e["filename"]
            if fn not in by_target:
                by_target[fn] = {**e, "peso_totale": 0}
            by_target[fn]["peso_totale"] += e["peso"]
        return sorted(by_target.values(), key=lambda x: -x["peso_totale"])

    outgoing_agg = {k: _aggregate(v) for k, v in outgoing.items()}
    incoming_agg = {k: _aggregate(v) for k, v in incoming.items()}
    return outgoing_agg, incoming_agg


def _file_metadata(file: str) -> dict[str, Any]:
    """Estrae metadati da un file .md tramite frontmatter YAML.

    Tutti i file del corpus hanno frontmatter con tipo, data, urn,
    codice_redazionale, vigente.

    Returns:
        Dict con title, tipo, data, urn, codice_redazionale, vigente.
    """
    fm = read_frontmatter(file)
    if not fm:
        return {"title": Path(file).stem}

    title = fm.get("titolo") or ""
    return {
        "title": title[:200] if title else Path(file).stem,
        "tipo": fm.get("tipo", ""),
        "data": str(fm.get("data", "")),
        "urn": fm.get("urn", ""),
        "codice_redazionale": fm.get("codice_redazionale", ""),
        "vigente": bool(fm.get("vigente", True)),
    }


def _collezione_da_path(rel_path: str) -> str:
    """Estrae il nome della collezione dal path relativo al corpus."""
    parts = Path(rel_path).parts
    return parts[0] if parts else ""


def _rg_disponibile() -> bool:
    """True se rg è installato."""
    return shutil.which("rg") is not None


def _parse_query(query: str) -> tuple[list[str], bool]:
    """Parsa una query di ricerca.

    Returns:
        (termini, is_phrase):
        - ``"ambiente energia"`` → ``(["ambiente", "energia"], False)``
        - ``'"decreto legislativo"'`` → ``(["decreto legislativo"], True)``
        - ``"decreto"`` → ``(["decreto"], False)``
        - ``""`` → ``([], False)``
    """
    q = query.strip()
    if not q:
        return [], False
    # Frase esplicita tra virgolette
    if (q.startswith('"') and q.endswith('"')) or \
       (q.startswith("'") and q.endswith("'")):
        return [q[1:-1]], True
    parole = [w for w in q.split() if w]
    if len(parole) > _QUERY_MAX_WORDS:
        parole = parole[:_QUERY_MAX_WORDS]
    return parole, False


# ─── motore di ricerca strutturato ────────────────────────────────


def _run_rg(cmd: list[str], timeout: int = 60) -> str:
    """Esegue rg e restituisce stdout. Solleva eccezioni strutturate."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise TimeoutError("Ricerca troppo lunga (60s timeout).")
    if result.returncode not in (0, 1):
        raise RuntimeError(f"rg error (exit {result.returncode}): {result.stderr[:500]}")
    return result.stdout


def _rg_list_files(term: str, search_path: str) -> set[str]:
    """Cerca file con rg -l per un termine letterale.

    Restituisce set di path assoluti dei file .md che contengono il termine.
    """
    cmd = [
        "rg", "-l", "-i", "-F", "-m", str(_RG_LIST_MATCHES),
        "--glob", "*.md", "--", term, search_path,
    ]
    stdout = _run_rg(cmd)
    if not stdout.strip():
        return set()
    return {ln.strip() for ln in stdout.split("\n")
            if ln.strip() and Path(ln.strip()).suffix == ".md"}


def _parse_rg_json(stdout: str) -> dict[str, dict]:
    """Parsa output JSON Lines di rg e raggruppa per file.

    Returns:
        dict: path_file -> {path, match_count, snippet}
    """
    per_file: dict[str, dict] = {}
    cur_file: str | None = None
    snippet_parts: list[str] = []
    match_count = 0

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue

        ev_type = ev.get("type")
        ev_data = ev.get("data", {})

        if ev_type == "begin":
            fp = ev_data.get("path", {}).get("text", "")
            if fp:
                cur_file = fp
                snippet_parts = []
                match_count = 0

        elif ev_type == "match" and cur_file:
            match_count += 1
            if len(snippet_parts) == 0:
                ln = ev_data.get("line_number", 0)
                txt = ev_data.get("lines", {}).get("text", "").rstrip()
                snippet_parts.append(f"Riga {ln}: {txt}")

        elif ev_type == "context" and cur_file and match_count == 1:
            txt = ev_data.get("lines", {}).get("text", "").rstrip()
            if txt:
                snippet_parts.append(f"  {txt}")

        elif ev_type == "end" and cur_file:
            snippet = " | ".join(snippet_parts[:5])[:400] if snippet_parts else ""
            per_file[cur_file] = {
                "path": cur_file,
                "match_count": match_count,
                "snippet": snippet,
            }
            cur_file = None

    return per_file


def _search_corpus(
    query: str,
    *,
    limit: int = 10,
    offset: int = 0,
    collezione: str = "",
    stato: str = "",
    min_score: int = 0,
    materia: str = "",
    max_sunsetting: int = -1,
) -> list[dict[str, Any]]:
    """Cerca nel corpus e restituisce risultati strutturati.

    Due fasi per efficienza:
    1. ``rg -l`` per lista file — per AND multi-termine fa una ``rg -l``
       per termine e interseca i risultati (AND documentale).
    2. ``rg --json`` solo sui file da mostrare (offset/limit applicati prima).

    I risultati sono arricchiti con i campi di qualità da normativa.parquet
    (stato, qualita_score, orfano, n_citazioni, duplicato) quando disponibili.
    """
    limit = min(limit, _MAX_LIMIT)
    offset = max(offset, 0)

    # ── risolvi path ──
    if collezione:
        if collezione not in _leggi_collezioni():
            raise ValueError(
                f"Collezione '{collezione}' non trovata. "
                f"Usa list_collections per l'elenco."
            )
        search_path = str(CORPUS / collezione)
    else:
        search_path = str(CORPUS)

    # ── verifica rg ──
    if not _rg_disponibile():
        raise RuntimeError("ripgrep (rg) non trovato. Installa rg per usare la ricerca.")

    # ── parsifica query ──
    terms, is_phrase = _parse_query(query)
    if not terms:
        return []

    # ── FASE 1: lista file ──
    if is_phrase or len(terms) == 1:
        all_files_set = _rg_list_files(terms[0], search_path)
    else:
        # AND documentale: rg -l per ogni termine, interseca
        all_files_set: set[str] | None = None
        for t in terms:
            t_files = _rg_list_files(t, search_path)
            if all_files_set is None:
                all_files_set = t_files
            else:
                all_files_set &= t_files
            if not all_files_set:
                return []

    if not all_files_set:
        return []

    all_files = sorted(all_files_set)

    # ── filtri qualità (su tutti i file, prima della paginazione) ──
    quality = _load_quality_lookup()
    if stato or min_score > 0 or materia or max_sunsetting >= 0:
        filtered: list[str] = []
        for fp in all_files:
            fn = Path(fp).name
            q = quality.get(fn, {})
            if stato and q.get("stato", "") != stato:
                continue
            if min_score and q.get("qualita_score", 0) < min_score:
                continue
            if materia and q.get("materia", "") != materia:
                continue
            if max_sunsetting >= 0 and q.get("sunsetting_score", 0) > max_sunsetting:
                continue
            filtered.append(fp)
        all_files = filtered
        if not all_files:
            return []

    page_files = all_files[offset: offset + limit]
    if not page_files:
        return []

    # ── FASE 2: snippet JSON solo per i file da mostrare ──
    snippet_term = query if (is_phrase or len(terms) == 1) else terms[0]
    cmd = [
        "rg", "--json", "-i", "-F", "-m", "1", "--context", "1",
        "--glob", "*.md", "--", snippet_term,
    ] + page_files
    stdout_snippet = _run_rg(cmd)
    per_file = _parse_rg_json(stdout_snippet) if stdout_snippet.strip() else {}

    # ── assembla output ──
    results: list[dict[str, Any]] = []
    for fp in page_files:
        info = per_file.get(fp, {"path": fp, "match_count": 0, "snippet": ""})
        rel = Path(fp).relative_to(CORPUS)
        meta = _file_metadata(fp)
        fn = rel.name
        q = quality.get(fn, {})

        result: dict[str, Any] = {
            "title": meta["title"],
            "collection": _collezione_da_path(str(rel)),
            "filename": fn,
            "path": str(rel),
            "snippet": info["snippet"],
            "match_count": info["match_count"],
        }
        # Arricchisci con campi frontmatter se disponibili
        for key in ("tipo", "data", "urn", "codice_redazionale", "vigente"):
            if key in meta:
                val = meta[key]
                if isinstance(val, bool) or val:
                    result[key] = val

        # Sovrascrivi vigente con il valore affidabile dal parquet
        if "stato" in q:
            result["stato"] = q["stato"]
            result["vigente"] = q["stato"] == "vigente"

        # Aggiungi campi di qualità dal parquet
        for key in _QUALITY_FIELDS:
            if key in q and q[key] is not None:
                val = q[key]
                # Converte numpy types in Python nativi
                if hasattr(val, "item"):
                    val = val.item()
                result[key] = val

        results.append(result)

    return results


# ─── strumenti MCP ────────────────────────────────────────────────


mcp = create_mcp_server(
    name="italia-corpus",
    instructions=(
        "Server MCP italia-corpus — cerca con ripgrep nel corpus normativo. "
        "Output strutturato (list[dict]) per agenti AI, con supporto AND multi-termine "
        "(documentale, non per riga), paginazione offset e tool per recupero full text."
    ),
)


@mcp.tool(
    name="italia-corpus_legal_search",
    description=(
        "Cerca nella legislazione italiana (~22.000 atti da Normattiva) con ripgrep. "
        "Query multi-parola fa AND documentale tra i termini. "
        "Usa virgolette per frase esatta. "
        "I risultati includono stato (vigente/abrogato/decaduto), qualita_score (0-100), "
        "orfano, n_citazioni, duplicato, materia e sunsetting_score. "
        "Filtri: stato='vigente', min_score, materia, max_sunsetting."
    ),
    structured_output=True,
)
def legal_search(
    query: str,
    limit: int = 10,
    offset: int = 0,
    collezione: str = "",
    stato: str = "",
    min_score: int = 0,
    materia: str = "",
    max_sunsetting: int = -1,
) -> list[dict[str, Any]]:
    """Cerca nel corpus normativo. Ritorna risultati strutturati.

    Args:
        query: Termini di ricerca. Multi-parola = AND documentale.
               Usa "virgolette" per frase esatta.
        limit: Max risultati (default 10, max 100).
        offset: Scorri risultati per paginazione (default 0).
        collezione: Filtra per collezione (opzionale).
        stato: Filtra per stato normativo: 'vigente', 'abrogato', 'decaduto' (opzionale).
        min_score: Filtra per qualità minima 0-100 (opzionale, default 0 = nessun filtro).
        materia: Filtra per materia tematica: 'fisco', 'ambientale', 'lavoro', etc. (opzionale).
        max_sunsetting: Escludi atti con sunsetting_score oltre questo valore (opzionale, -1 = nessun filtro).

    Returns:
        Lista di dict con title, collection, filename, path, snippet, match_count,
        tipo, data, urn, codice_redazionale, stato, vigente, qualita_score,
        orfano, n_citazioni, duplicato, materia, sunsetting_score.
    """
    return guard_timed(
        _search_corpus, "italia-corpus_legal_search",
        query, limit=limit, offset=offset, collezione=collezione,
        stato=stato, min_score=min_score, materia=materia,
        max_sunsetting=max_sunsetting,
    )


@mcp.tool(
    name="italia-corpus_legal_get_document",
    description="Recupera il testo completo di un atto dal corpus, per collezione e filename.",
    structured_output=True,
)
def legal_get_document(
    collezione: str,
    filename: str,
    max_chars: int = 5000,
) -> str:
    """Restituisce il contenuto integrale (parziale) di un atto.

    Args:
        collezione: Nome della collezione (es. "Decreti Legislativi").
        filename: Nome del file .md (es. "test.md").
        max_chars: Max caratteri da restituire (default 5000, max 50000).

    Returns:
        Contenuto del file in markdown, troncato a max_chars.
    """
    return guard_timed(
        _impl_get_document, "italia-corpus_legal_get_document",
        collezione, filename, max_chars,
    )


def _impl_get_document(collezione: str, filename: str, max_chars: int) -> str:
    """Implementazione pura di legal_get_document."""
    max_chars = min(max_chars, 50000)
    if collezione not in _leggi_collezioni():
        raise ValueError(
            f"Collezione '{collezione}' non trovata. "
            f"Usa list_collections per l'elenco."
        )

    # ── security: blocca path traversal ──
    # 1. solo basename (nessun path separator)
    if filename != Path(filename).name:
        raise ValueError(f"filename non valido: {filename}")
    # 2. solo file .md
    if not filename.endswith(".md"):
        raise ValueError(f"filename deve terminare con .md: {filename}")

    filepath = (CORPUS / collezione / filename).resolve()
    base_path = (CORPUS / collezione).resolve()

    # 3. verifica che sia dentro CORPUS/collezione
    # Usa relative_to invece di startswith per evitare bypass
    # tipo "Col_evil" che inizia con "Col".
    try:
        filepath.relative_to(base_path)
    except ValueError:
        raise ValueError(f"Accesso negato: {filename}")

    if not filepath.exists() or not filepath.is_file():
        raise ValueError(
            f"File '{filename}' non trovato in '{collezione}'."
        )
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        raise RuntimeError(f"Errore lettura file: {e}") from e

    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n... [troncato a {max_chars} caratteri]"
    return text


@mcp.tool(
    name="italia-corpus_list_collections",
    description="Elenca le directory (collezioni) del corpus disponibili per la ricerca.",
    structured_output=True,
)
def list_collections() -> str:
    """Elenca le 20 collezioni legislative disponibili."""
    return guard_timed(_impl_list_collections, "italia-corpus_list_collections")


def _impl_list_collections() -> str:
    """Implementazione pura di list_collections."""
    nomi = sorted(_leggi_collezioni())
    if not nomi:
        return "## Collezioni\n_(nessuna — esegui il checkout delle collezioni)_"
    return "## Collezioni\n" + "\n".join(f"- {d}" for d in nomi)


@mcp.tool(
    name="italia-corpus_legal_crossref",
    description=(
        "Cross-reference normativo: dato un atto, mostra cosa cita (outgoing) "
        "e chi lo cita (incoming) dal grafo dei riferimenti. "
        "Accetta filename completo o parziale (substring match). "
        "Output: metadati atto + top N citazioni in uscita e in ingresso."
    ),
    structured_output=True,
)
def legal_crossref(
    filename: str,
    limit: int = 10,
) -> dict[str, Any]:
    """Cross-reference di un atto normativo.

    Args:
        filename: Filename completo o substring del file .md
                  (es. "001G0219" o "D.Lgs 231" o il filename completo).
        limit: Max citazioni per direzione (default 10, max 50).

    Returns:
        Dict con:
        - atto: metadati (filename, collezione, tipo, stato, materia, qualita_score, etc.)
        - outgoing: cosa cita l'atto (top N per peso)
        - incoming: chi cita l'atto (top N per peso)
        - summary: conteggi riassuntivi
    """
    return guard_timed(
        _impl_crossref, "italia-corpus_legal_crossref",
        filename, limit,
    )


def _impl_crossref(filename: str, limit: int) -> dict[str, Any]:
    """Implementazione pura di legal_crossref."""
    limit = min(limit, 50)
    query = filename.strip().lower()
    if not query:
        raise ValueError("filename non può essere vuoto.")

    quality = _load_quality_lookup()
    outgoing_all, incoming_all = _load_graph_lookup()

    # ── trova l'atto: match esatto o substring ──
    matched_fn: str | None = None
    if filename in quality:
        matched_fn = filename
    else:
        # substring match su filename
        candidates = [fn for fn in quality if query in fn.lower()]
        if len(candidates) == 1:
            matched_fn = candidates[0]
        elif len(candidates) > 1:
            # Se più match, prova a fermarti al primo con stato vigente
            for c in candidates:
                if quality[c].get("stato") == "vigente":
                    matched_fn = c
                    break
            if matched_fn is None:
                matched_fn = candidates[0]
        else:
            # Cerca anche per codice_redazionale o parte dell'oggetto
            for fn, q in quality.items():
                # Il codice redazionale è spesso nel filename
                if query in fn.lower():
                    matched_fn = fn
                    break

    if matched_fn is None:
        raise ValueError(
            f"Atto '{filename}' non trovato. "
            f"Usa legal_search per cercare, poi passa il filename risultante."
        )

    q = quality.get(matched_fn, {})

    # ── metadati atto ──
    atto = {
        "filename": matched_fn,
        "stato": q.get("stato", ""),
        "materia": q.get("materia", ""),
        "qualita_score": q.get("qualita_score", 0),
        "orfano": q.get("orfano", False),
        "n_citazioni": q.get("n_citazioni", 0),
        "duplicato": q.get("duplicato", False),
        "vigente": q.get("stato") == "vigente",
    }

    # ── outgoing: cosa cita ──
    out_edges = outgoing_all.get(matched_fn, [])[:limit]
    outgoing = []
    for e in out_edges:
        out_q = quality.get(e["filename"], {})
        outgoing.append({
            "filename": e["filename"],
            "collezione": e["collezione"],
            "tipo": e["tipo"],
            "anno": e["anno"],
            "peso_totale": e["peso_totale"],
            "stato": out_q.get("stato", ""),
            "materia": out_q.get("materia", ""),
        })

    # ── incoming: chi cita ──
    in_edges = incoming_all.get(matched_fn, [])[:limit]
    incoming = []
    for e in in_edges:
        in_q = quality.get(e["filename"], {})
        incoming.append({
            "filename": e["filename"],
            "collezione": e["collezione"],
            "tipo": e["tipo"],
            "anno": e["anno"],
            "peso_totale": e["peso_totale"],
            "stato": in_q.get("stato", ""),
            "materia": in_q.get("materia", ""),
        })

    # ── summary ──
    all_out = outgoing_all.get(matched_fn, [])
    all_in = incoming_all.get(matched_fn, [])
    summary = {
        "outgoing_total": len(all_out),
        "incoming_total": len(all_in),
        "outgoing_peso_totale": sum(e["peso_totale"] for e in all_out),
        "incoming_peso_totale": sum(e["peso_totale"] for e in all_in),
        "outgoing_mostrati": len(outgoing),
        "incoming_mostrati": len(incoming),
    }

    return {
        "atto": atto,
        "outgoing": outgoing,
        "incoming": incoming,
        "summary": summary,
    }


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
