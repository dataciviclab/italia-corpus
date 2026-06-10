"""Server MCP italia-corpus — cerca con ripgrep nel corpus normativo.
Output strutturato (list[dict]) per agenti AI, con supporto AND multi-termine,
paginazione offset e tool per recupero full text.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

CORPUS = Path(__file__).resolve().parent.parent
CONFIG_COLLEZIONI = CORPUS / "config" / "collezioni.txt"

# Soglia oltre cui rg non viene chiamato per singola parola ("rumorosa")
_QUERY_MAX_WORDS = 8
_MAX_LIMIT = 100


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
    # Il path relativo è "Collezione/filename.md" o "sotto/collezione/filename.md"
    parts = Path(rel_path).parts
    return parts[0] if parts else ""


def _build_pattern(query: str) -> tuple[str, bool]:
    """Costruisce il pattern per rg.

    Args:
        query: stringa di ricerca (libera o tra virgolette)

    Returns:
        (pattern, use_pcre2): pattern da passare a rg e flag PCRE2
    """
    query = query.strip()
    if not query:
        return "", False

    # Frase esplicita tra virgolette → letterale
    if (query.startswith('"') and query.endswith('"')) or \
       (query.startswith("'") and query.endswith("'")):
        return query[1:-1], False

    parole = query.split()
    n = len(parole)

    # Singola parola → letterale (nessuna regex)
    if n <= 1:
        return re.escape(query), False

    # Multi-parola → AND con lookahead PCRE2
    # Parole corte (< 3 char) senza word boundary
    parts = []
    for w in parole[: _QUERY_MAX_WORDS]:
        escaped = re.escape(w)
        if len(w) >= 3 and w.isalpha():
            parts.append(f"(?=.*\\b{escaped}\\b)")
        else:
            parts.append(f"(?=.*{escaped})")
    return "^" + "".join(parts) + ".*", True


def _rg_disponibile() -> tuple[bool, bool]:
    """(disponibile, supporta_pcre2)"""
    rg = shutil.which("rg")
    if not rg:
        return False, False
    # Verifica supporto PCRE2
    try:
        out = subprocess.run([rg, "--version"], capture_output=True, text=True)
        return True, "PCRE2" in out.stdout or "pcre2" in out.stdout
    except Exception:
        return True, False


# ─── motore di ricerca strutturato ────────────────────────────────

# Massimo match per file in fase di lista (rg -m). Con -m 1 basta per
# capire se un file matcha. Per lo snippet si fa in fase separata.
_RG_LIST_MATCHES = 3


def _run_rg(cmd: list[str], timeout: int = 60) -> str:
    """Esegue rg e restituisce stdout. Solleva eccezioni strutturate."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise TimeoutError("Ricerca troppo lunga (60s timeout).")
    if result.returncode not in (0, 1):
        raise RuntimeError(f"rg error (exit {result.returncode}): {result.stderr[:500]}")
    return result.stdout


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
                # Solo primo match: linea + numero
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
    1. ``rg -l`` per lista file (leggero, output minimo)
    2. ``rg --json`` solo sui file da mostrare (offset/limit applicati prima)
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
        search_targets = [str(CORPUS / collezione)]
    else:
        search_targets = [str(CORPUS)]

    # ── verifica rg ──
    rg_dispo, rg_pcre2 = _rg_disponibile()
    if not rg_dispo:
        raise RuntimeError("ripgrep (rg) non trovato. Installa rg per usare la ricerca.")

    # ── costruisci pattern ──
    pattern, use_pcre2 = _build_pattern(query)
    if not pattern:
        return []

    # ── helper per costruire comando rg ──
    def _cmd(extra: list[str]) -> list[str]:
        cmd = ["rg", "-i", "--glob", "*.md"]
        if use_pcre2 and rg_pcre2:
            cmd.extend(["-P", pattern])
        elif use_pcre2 and not rg_pcre2:
            # Fallback AND: cerca con prima parola (AND approssimato)
            cmd.extend(["-F", query.split()[0]])
        else:
            cmd.extend(["-F", pattern])
        cmd.extend(extra)
        return cmd

    # ── FASE 1: lista file con rg -l ──
    stdout = _run_rg(
        _cmd(["-l", "-m", str(_RG_LIST_MATCHES), "--"] + search_targets)
    )
    if not stdout.strip():
        return []

    all_files = [
        ln.strip() for ln in stdout.split("\n")
        if ln.strip() and Path(ln.strip()).suffix == ".md"
    ]
    if not all_files:
        return []

    # ── applica offset / limit ──
    page_files = all_files[offset: offset + limit]
    if not page_files:
        return []

    # ── FASE 2: snippet JSON solo per i file da mostrare ──
    cmd_snippet = _cmd(
        ["--json", "-m", "1", "--context", "1", "--"] + page_files
    )
    stdout_snippet = _run_rg(cmd_snippet)
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
        "Query multi-parola fa AND tra i termini. "
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
        query: Termini di ricerca. Multi-parola = AND.
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
        # FastMCP propaga eccezioni come error tool
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
    filepath = CORPUS / collezione / filename
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
