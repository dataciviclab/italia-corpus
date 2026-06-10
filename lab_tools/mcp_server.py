"""Server MCP italia-corpus — cerca con ripgrep nel corpus normativo."""
from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

from mcp.server.fastmcp import FastMCP

CORPUS = Path(__file__).resolve().parent.parent
CONFIG_COLLEZIONI = CORPUS / "config" / "collezioni.txt"


def _leggi_collezioni() -> set[str]:
    """Legge l'elenco delle collezioni vive da config/collezioni.txt."""
    if not CONFIG_COLLEZIONI.exists():
        return set()
    return {l.strip() for l in CONFIG_COLLEZIONI.read_text().splitlines() if l.strip()}


def _pick_title(file: str) -> str:
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


server = FastMCP("italia-corpus")


@server.tool(
    name="italia-corpus_legal_search",
    description="Cerca nella legislazione italiana (~25.000 atti da Normattiva, collezioni vigenti) con ripgrep.",
)
def legal_search(query: str, limit: int = 10, collezione: str = "") -> str:
    limit = min(limit, 50)
    if collezione:
        col_path = CORPUS / collezione
        if not col_path.is_dir() or collezione not in _leggi_collezioni():
            return f"Collezione '{collezione}' non trovata. Usa list_collections per l'elenco."
        search_path = str(col_path)
    else:
        search_path = str(CORPUS)
    if not shutil.which("rg"):
        return "ripgrep (rg) non trovato."
    try:
        out = subprocess.run(
            ["rg", "-l", "-m", "1", "-i", "--glob", "*.md", "--", query, search_path],
            capture_output=True, text=True, timeout=60,
        ).stdout
        files = [f for f in out.strip().split("\n") if f.strip()][:limit]
        if not files:
            return f"Nessun risultato per: {query}"
    except subprocess.TimeoutExpired:
        return "Ricerca troppo lunga."
    except Exception as e:
        return f"Errore: {e}"
    if not files:
        return f"Nessun risultato per: {query}"
    prefix = f" (collezione: {collezione})" if collezione else ""
    lines = [f"### Ricerca: «{query}»{prefix} — {len(files)} risultati"]
    for fp in files:
        with open(fp, encoding="utf-8", errors="replace") as f:
            title = _pick_title(fp)
        rel = Path(fp).relative_to(CORPUS)
        try:
            ctx = subprocess.run(
                ["rg", "-m", "1", "--context", "1", "--", query, fp],
                capture_output=True, text=True, timeout=10,
            ).stdout.strip()[:300]
        except Exception:
            ctx = ""
        lines.append(f"\n**{title}**")
        lines.append(f"  > `{rel.parent}`")
        if ctx:
            lines.append(f"  > {ctx}")
    return "\n".join(lines)


@server.tool(
    name="italia-corpus_list_collections",
    description="Elenca le directory (collezioni) del corpus.",
)
def list_collections() -> str:
    nomi = sorted(_leggi_collezioni())
    if not nomi:
        return "## Collezioni\n_(nessuna — esegui il checkout delle collezioni)_"
    return "## Collezioni\n" + "\n".join(f"- {d}" for d in nomi)


def main():
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
