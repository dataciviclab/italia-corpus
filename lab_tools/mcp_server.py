"""Server MCP italia-corpus — cerca con ripgrep nel corpus normativo.
Output strutturato (list[dict]) per agenti AI, con supporto AND multi-termine
(documentale, non per riga), paginazione offset e tool per recupero full text.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

CORPUS = Path(__file__).resolve().parent.parent
CONFIG_COLLEZIONI = CORPUS / "config" / "collezioni.txt"

_QUERY_MAX_WORDS = 8
_MAX_LIMIT = 100
_RG_LIST_MATCHES = 3


# ─── helpers interni ──────────────────────────────────────────────


def _leggi_collezioni() -> set[str]:
    """Legge l'elenco delle collezioni vive da config/collezioni.txt."""
    if not CONFIG_COLLEZIONI.exists():
        return set()
    return {line.strip() for line in CONFIG_COLLEZIONI.read_text().splitlines() if line.strip()}


def _pick_title(file: str) -> str:
    """Estrae il titolo di un atto dalle prime righe del markdown."""
    with open(file, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if i > 10:
                break
            line = line.strip()
            if line and not line.startswith(
                ("Art.", "IL PRESIDENTE", "Entrata", "Visti", "Considerato",
                 "Visto", "Ritenuto", "Sentito", "Udito", "===", "---", "\x0c")
            ):
                return line[:200]
    return Path(file).stem


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
) -> list[dict[str, Any]]:
    """Cerca nel corpus e restituisce risultati strutturati.

    Due fasi per efficienza:
    1. ``rg -l`` per lista file — per AND multi-termine fa una ``rg -l``
       per termine e interseca i risultati (AND documentale).
    2. ``rg --json`` solo sui file da mostrare (offset/limit applicati prima).
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
    page_files = all_files[offset: offset + limit]
    if not page_files:
        return []

    # ── FASE 2: snippet JSON solo per i file da mostrare ──
    # Per snippet usiamo il primo termine (o la frase se è frase esatta)
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
        results.append({
            "title": _pick_title(fp),
            "collection": _collezione_da_path(str(rel)),
            "filename": rel.name,
            "path": str(rel),
            "snippet": info["snippet"],
            "match_count": info["match_count"],
        })

    return results


# ─── strumenti MCP ────────────────────────────────────────────────


server = FastMCP("italia-corpus")


@server.tool(
    name="italia-corpus_legal_search",
    description=(
        "Cerca nella legislazione italiana (~25.000 atti da Normattiva, "
        "collezioni vigenti) con ripgrep. "
        "Query multi-parola fa AND documentale tra i termini. "
        "Usa virgolette per frase esatta. "
        "Restituisce lista strutturata di risultati."
    ),
)
def legal_search(
    query: str,
    limit: int = 10,
    offset: int = 0,
    collezione: str = "",
) -> list[dict[str, Any]]:
    """Cerca nel corpus normativo. Ritorna risultati strutturati.

    Args:
        query: Termini di ricerca. Multi-parola = AND documentale.
               Usa "virgolette" per frase esatta.
        limit: Max risultati (default 10, max 100).
        offset: Scorri risultati per paginazione (default 0).
        collezione: Filtra per collezione (opzionale).

    Returns:
        Lista di dict con title, collection, filename, path, snippet, match_count.
    """
    try:
        return _search_corpus(
            query, limit=limit, offset=offset, collezione=collezione,
        )
    except (ValueError, RuntimeError, TimeoutError) as e:
        raise RuntimeError(str(e)) from e


@server.tool(
    name="italia-corpus_legal_get_document",
    description="Recupera il testo completo di un atto dal corpus, per collezione e filename.",
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
    if not str(filepath).startswith(str(base_path)):
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


@server.tool(
    name="italia-corpus_list_collections",
    description="Elenca le directory (collezioni) del corpus disponibili per la ricerca.",
)
def list_collections() -> str:
    """Elenca le 20 collezioni legislative disponibili."""
    nomi = sorted(_leggi_collezioni())
    if not nomi:
        return "## Collezioni\n_(nessuna — esegui il checkout delle collezioni)_"
    return "## Collezioni\n" + "\n".join(f"- {d}" for d in nomi)


def main():
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
