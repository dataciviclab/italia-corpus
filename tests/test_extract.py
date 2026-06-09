"""Test per lab_tools.extract.extract() con fixture reali e sintetiche."""

from pathlib import Path

import pytest

from lab_tools.extract import extract

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_con_celex():
    """File completo: tipo, data, numero, oggetto (fallback), entrata vigore, CELEX."""
    result = extract(FIXTURES / "con_celex.md")
    assert result is not None
    assert result["tipo"] == "DECRETO LEGISLATIVO"
    assert result["data"] == "2020-03-15"
    assert result["numero"] == "45"
    # L'oggetto vero non matcha RE_OGGETTO (firma assente), fallback al filename
    assert result["oggetto"] == "con_celex"
    assert result["entrata_vigore"] == "2020-04-01"
    assert result["celex"] == "32018L1234"
    assert result["anno_atto"] == 2020
    # anno_dir recuperato dal CELEX (32018L1234 → 2018)
    assert result["anno_dir"] == 2018
    assert result["ritardo"] == 2


def test_senza_celex():
    """File senza CELEX né entrata vigore: campi vuoti."""
    result = extract(FIXTURES / "senza_celex.md")
    assert result is not None
    assert result["tipo"] == "LEGGE"
    assert result["data"] == "2021-01-10"
    assert result["numero"] == "1"
    assert result["celex"] == ""
    assert result["entrata_vigore"] == ""
    assert result["anno_dir"] == 0
    assert result["ritardo"] is None


def test_base64():
    """File con nome data_nome: solo CELEX, campi ridotti (no tipo/numero)."""
    result = extract(FIXTURES / "2020-06-01_test_base64.md")
    assert result is not None
    assert result["tipo"] == "BASE64"
    assert result["data"] == ""
    assert result["numero"] == ""
    assert "test_base64" in result["oggetto"]
    assert result["celex"] == "32018L1234;32019L2121"
    assert result["entrata_vigore"] == ""


def test_file_inesistente():
    """File inesistente solleva FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        extract(FIXTURES / "inesistente.md")


def test_nessun_match():
    """File senza pattern riconoscibili: extract torna None."""
    dummy = FIXTURES / "_dummy_no_match.md"
    dummy.write_text("Contenuto senza struttura riconoscibile.", encoding="utf-8")
    try:
        assert extract(dummy) is None
    finally:
        dummy.unlink()
