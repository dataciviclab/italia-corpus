"""Contratto `config/collezioni.txt` ↔ filesystem.

Il workflow `test` fa sparse-checkout di `lab_tools/` e `tests/` soli: i test
sul filesystem reale si saltano lì e girano in `build-dataset`, dove `config/`
e `collezioni/` sono presenti.
"""

from __future__ import annotations

import pytest
from lab_tools._paths import COLLEZIONI_ROOT, CONFIG_COLLEZIONI, load_collezioni, load_pin


def test_parser_ignora_commenti_e_pin(tmp_path):
    f = tmp_path / "collezioni.txt"
    f.write_text("# commento\nCodici|V\nLeggi\n", encoding="utf-8")
    assert load_collezioni(f) == ["Codici", "Leggi"]
    assert load_pin(f) == {"Codici": "V"}


def test_ogni_collezione_del_config_ha_una_directory():
    """Avrebbe intercettato `Codici|V` trattato come nome directory."""
    if not CONFIG_COLLEZIONI.exists() or not COLLEZIONI_ROOT.is_dir():
        pytest.skip("checkout sparso: invariante eseguita in build-dataset")
    nomi = load_collezioni()
    mancanti = [n for n in nomi if not (COLLEZIONI_ROOT / n).is_dir()]
    assert not mancanti, f"collezioni nel config senza directory: {mancanti}"
    assert len(nomi) == 20


def test_pin_formato_solo_su_richiesta():
    if not CONFIG_COLLEZIONI.exists():
        pytest.skip("checkout sparso: invariante eseguita in build-dataset")
    pin = load_pin()
    assert pin.get("Codici") == "V"
    assert all(v in {"O", "M", "V"} for v in pin.values())
