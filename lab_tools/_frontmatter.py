"""Helper condiviso per parsare YAML frontmatter dai file .md del corpus.

Tutti i 25k+ file nel corpus hanno frontmatter con 7 campi:
  tipo, numero, data, titolo, urn, codice_redazionale, vigente

Questo modulo centralizza il parsing per MCP (mcp_server) e extract.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def parse_frontmatter(text: str) -> dict | None:
    """Parsa YAML frontmatter da un testo markdown.

    Args:
        text: Contenuto del file .md (almeno le prime righe).

    Returns:
        Dict con i campi frontmatter, oppure None se non presente o non valido.
    """
    if not text.startswith("---"):
        return None
    end = text.find("---", 3)
    if end < 0:
        return None
    # Sanitize: strip control characters and Unicode replacement chars that
    # break YAML parsing. These come from Windows-1252 artifacts (\x95, \x9b)
    # in older Italian legislative texts.
    raw = text[3:end]
    sanitized = "".join(
        ch for ch in raw
        if ch not in ("\ufffd",)
        and not (0x00 <= ord(ch) <= 0x1F and ch not in ("\t", "\n", "\r"))
        and not (0x7F <= ord(ch) <= 0x9F)
    )
    try:
        data = yaml.safe_load(sanitized)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def read_frontmatter(filepath: str | Path) -> dict | None:
    """Legge file .md e restituisce solo il frontmatter YAML.

    Args:
        filepath: Path assoluto al file .md.

    Returns:
        Dict frontmatter o None.
    """
    filepath = Path(filepath)
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            content = f.read(4096)  # frontmatter è sempre nelle prime ~20 righe
    except (OSError, UnicodeError):
        return None
    return parse_frontmatter(content)
