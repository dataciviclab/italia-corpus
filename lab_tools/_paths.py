"""Path canonici del corpus italia-corpus.

Le collezioni legislative vivono sotto ``collezioni/`` (contratto
project.yml: ``collezioni/**/*.md``). Usare queste costanti invece di
ricostruire i path a mano — è un contratto cross-repo (MCP, CI,
legal-graph, extract).
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Nome directory parent delle collezioni legislative
COLLEZIONI_DIRNAME = "collezioni"

# Root assoluta delle collezioni (REPO/collezioni)
COLLEZIONI_ROOT = REPO / COLLEZIONI_DIRNAME

CONFIG_COLLEZIONI = REPO / "config" / "collezioni.txt"
OUTDIR = REPO / "data" / "derived"


def _leggi_config_collezioni(path: Path | None = None) -> list[tuple[str, str]]:
    """(nome, formato) da `config/collezioni.txt`.

    Ignora commenti (`#`) e righe vuote. Formato opzionale: `Nome` o `Nome|V`.
    """
    p = path or CONFIG_COLLEZIONI
    if not p.exists():
        return []
    righe: list[tuple[str, str]] = []
    for line in p.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        nome, _, fmt = line.partition("|")
        nome = nome.strip()
        if nome:
            righe.append((nome, fmt.strip().upper()))
    return righe


def load_collezioni(path: Path | None = None) -> list[str]:
    """Nomi delle collezioni da `config/collezioni.txt` (senza pin di formato)."""
    return [nome for nome, _ in _leggi_config_collezioni(path)]


def load_pin(path: Path | None = None) -> dict[str, str]:
    """Formato richiesto per collezione (`Nome|V` -> {"Nome": "V"})."""
    return {nome: fmt for nome, fmt in _leggi_config_collezioni(path) if fmt}
