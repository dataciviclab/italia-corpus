"""Invarianti del contratto config ↔ filesystem."""

from __future__ import annotations

from lab_tools._paths import COLLEZIONI_ROOT, load_collezioni, load_pin


def test_ogni_collezione_del_config_ha_una_directory():
    """Il config elenca 20 collezioni e ognuna esiste su disco.

    Questo test avrebbe intercettato `Codici|V` trattato come nome directory
    da `extract`/`grafo`/`estrai_citazioni` (collezioni escluse, ~4.400 atti).
    """
    nomi = load_collezioni()
    assert len(nomi) == 20
    assert all((COLLEZIONI_ROOT / n).is_dir() for n in nomi)


def test_pin_formato_solo_su_richiesta():
    pin = load_pin()
    assert pin.get("Codici") == "V"
    assert all(v in {"O", "M", "V"} for v in pin.values())
