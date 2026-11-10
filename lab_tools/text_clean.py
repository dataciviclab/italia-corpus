"""Pulizia del markup per i contesti di evidenza.

Le evidenze del grafo (`riferimenti.contesto`, `abrogations_raw.context`)
sono finestre di testo markdown. Senza pulizia contengono i target dei link
(`[art. 1](../Leggi/2012-..._VIGENZA_2025-...md)`), che non sono prosa e non
sono verificabili. La sostituzione **mantiene la lunghezza**: così una
finestra calcolata sul body originale può essere tagliata sulla copia pulita
senza shiftare le posizioni.
"""

from __future__ import annotations

import re

# `[label](target)` → `label`.
RE_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# URL e URN nudi, anche quando la finestra inizia dentro un target.
RE_URL_URN = re.compile(r"\??(?:https?://|urn:nir:)\S+")


def pulisci_markup(text: str) -> str:
    """Sostituisce link/URL con il loro testo o con spazi, a pari lunghezza."""

    def _label(m: re.Match) -> str:
        label = m.group(1)
        return label + " " * (len(m.group(0)) - len(label))

    out = RE_MD_LINK.sub(_label, text)
    return RE_URL_URN.sub(lambda m: " " * len(m.group(0)), out)
