"""Server MCP italia-corpus — cerca con ripgrep nel corpus normativo."""
from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

from mcp.server.fastmcp import FastMCP

CORPUS = Path(__file__).resolve().parent.parent


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
def legal_search(query: str, limit: int = 10) -> str:
    if not shutil.which("rg"):
        return "ripgrep (rg) non trovato."
    limit = min(limit, 50)
    try:
        out = subprocess.run(
            ["rg", "-l", "-m", "1", "--glob", "*.md", "--", query, str(CORPUS)],
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
    lines = [f"### Ricerca: «{query}» — {len(files)} risultati"]
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
    skip = {".git", "data", "lab_tools", "tests", "notebooks"}
    dirs = [
        d.name for d in sorted(CORPUS.iterdir())
        if d.is_dir() and d.name not in skip and not d.name.startswith(".")
    ]
    return "## Collezioni\n" + "\n".join(f"- {d}" for d in dirs)


def main():
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
