"""Pulizia del markup per i contesti di evidenza.

Le evidenze del grafo (`riferimenti.contesto`, `abrogations_raw.context`)
sono finestre di testo markdown. Senza pulizia contengono i target dei link
(`[art. 1](../Leggi/2012-..._VIGENZA_2025-...md)`), che non sono prosa e non
sono verificabili. La sostituzione **mantiene la lunghezza e i newline**:
così una finestra calcolata sul body originale può essere tagliata sulla
copia pulita senza shiftare le posizioni, e l'allineamento per riga di
`extract_abrogations` resta valido anche per i target spezzati su più righe.
"""

from __future__ import annotations

import re

# `[label](target)` → `label`.
RE_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# URL e URN nudi, anche quando la finestra inizia dentro un target.
RE_URL_URN = re.compile(r"\??(?:https?://|urn:nir:)\S+")


def _spazi_like(text: str) -> str:
    """Spazi della stessa lunghezza, preservando `\\n`/`\\r`."""
    return "".join(ch if ch in "\r\n" else " " for ch in text)


def pulisci_markup(text: str) -> str:
    """Sostituisce link/URL con il loro testo o con spazi, a pari lunghezza.

    I newline dentro il match sono conservati: un target spezzato su più
    righe non cambia il numero di righe del testo pulito.
    """

    def _label(m: re.Match) -> str:
        label = m.group(1)
        # `[` + label + `](target)`: si tiene la label, si azzera il resto.
        resto = m.group(0)[1 + len(label):]
        return " " + label + _spazi_like(resto)

    out = RE_MD_LINK.sub(_label, text)
    return RE_URL_URN.sub(lambda m: _spazi_like(m.group(0)), out)
