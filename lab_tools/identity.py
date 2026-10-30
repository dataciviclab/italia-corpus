"""Identità dell'atto: `data_codice` e scelta dell'espressione corrente.

Il nome file del corpus è `AAAA-MM-GG_CODICE_<espressione>_V<n>.md`:

    2003-08-07_003G0227_ORIGINALE_V0.md
    2003-08-07_003G0227_VIGENZA_2026-02-25_V0.md

Il prefisso **`data_codice`** (`2003-08-07_003G0227`) è stabile ed è 1:1 con
l'atto; il resto cambia quando la fonte aggiorna uno snapshot. Per questo i
link per filename invecchiano dopo un fetch e la risoluzione deve poter
ripiegare sull'identità invece di perdere l'arco.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

_VIGENZA_RE = re.compile(r"_VIGENZA_(\d{4}-\d{2}-\d{2})_")
_DATA_CODICE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}_[A-Z0-9]+)_")


def versione_da_filename(filename: str) -> tuple[str, str | None]:
    """(versione, snapshot_data) dal nome file.

    `..._VIGENZA_2025-06-12_V0.md` → ("VIGENZA", "2025-06-12")
    `..._ORIGINALE_V0.md` → ("ORIGINALE", None)

    Una forma sconosciuta restituisce `("", None)` ed è segnalata da chi la usa
    (non silenziosa, così un cambio di naming della fonte non passa inosservato).
    """
    m = _VIGENZA_RE.search(filename)
    if m:
        return "VIGENZA", m.group(1)
    if "_ORIGINALE_" in filename:
        return "ORIGINALE", None
    return "", None


def data_codice(filename: str) -> str | None:
    """Prefisso stabile `AAAA-MM-GG_CODICE` del filename, o None.

    `2003-08-07_003G0227_VIGENZA_2026-02-25_V0.md` → `2003-08-07_003G0227`
    """
    if not filename:
        return None
    m = _DATA_CODICE_RE.match(Path(filename).name)
    return m.group(1) if m else None


def scegli_espressione(candidates: list[str], correnti: set[str]) -> str | None:
    """L'espressione corrente fra le versioni dello stesso atto.

    Ordine: `is_current` → VIGENZA con snapshot più recente → ORIGINALE →
    lessicale. `correnti` contiene i **basename** con `is_current = true`.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    correnti_pool = [c for c in candidates if Path(c).name in correnti]
    pool = correnti_pool or candidates
    if len(pool) == 1:
        return pool[0]

    def _key(c: str) -> tuple[int, int, str]:
        versione, snapshot = versione_da_filename(Path(c).name)
        # VIGENZA prima, snapshot DESC (negato), poi lessicale
        return (
            0 if versione == "VIGENZA" else 1,
            -(int(snapshot.replace("-", "")) if snapshot else 0),
            Path(c).name,
        )

    return sorted(pool, key=_key)[0]


def build_indice_identita(
    relpaths: Iterable[str], correnti: set[str]
) -> dict[str, str]:
    """`data_codice -> relpath` dell'espressione corrente.

    Args:
        relpaths: path relativi a `collezioni/` (es. `"Decreti Legislativi/x.md"`).
        correnti: basename con `is_current = true` (può essere vuoto: si ricade
            sulla regola deterministica VIGENZA/ORIGINALE).

    Returns:
        Mappa delle sole identità con almeno una candidata.
    """
    gruppi: dict[str, list[str]] = {}
    for rel in relpaths:
        cod = data_codice(rel)
        if cod:
            gruppi.setdefault(cod, []).append(rel)

    out: dict[str, str] = {}
    for cod, candidate in gruppi.items():
        scelto = scegli_espressione(candidate, correnti)
        if scelto:
            out[cod] = scelto
    return out
