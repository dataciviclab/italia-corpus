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
