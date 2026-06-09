"""Test per lab_tools.extract.extract() e funzioni ausiliarie."""

from pathlib import Path

import pytest

from lab_tools.extract import extract, _anno_da_celex, _dedup

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_con_celex():
    """File completo: tipo, data, numero, oggetto (fallback), entrata vigore, CELEX,
    anno_dir da CELEX, collezione."""
    result = extract(FIXTURES / "con_celex.md")
    assert result is not None
    assert result["tipo"] == "DECRETO LEGISLATIVO"
    assert result["data"] == "2020-03-15"
    assert result["numero"] == "45"
    assert result["oggetto"] == "con_celex"
    assert result["entrata_vigore"] == "2020-04-01"
    assert result["celex"] == "32018L1234"
    assert result["anno_atto"] == 2020
    assert result["anno_dir"] == 2018
    assert result["ritardo"] == 2
    assert result["collezione"] == ""


def test_collezione_esplicita():
    """Parametro collezione passato a extract()."""
    result = extract(FIXTURES / "con_celex.md", collezione="Test")
    assert result is not None
    assert result["collezione"] == "Test"


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


def test_anno_da_celex_piu_recente():
    """_anno_da_celex sceglie il CELEX L/R più recente, non il primo ordinato."""
    assert _anno_da_celex("31950L2008;32015L2193;31990R1234") == 2015
    assert _anno_da_celex("32015L2193;31950L2008") == 2015
    assert _anno_da_celex("31950L2008") == 1950


def test_anno_da_celex_senza_l():
    """CELEX senza tipo L o R: nessun anno (es. trattati)."""
    assert _anno_da_celex("12008E") is None
    assert _anno_da_celex("") is None
    assert _anno_da_celex(None) is None


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


class TestDedup:
    """Test per _dedup(): merge collezioni, skip duplicati."""

    def _r(self, filename: str, collezione: str) -> dict:
        return {"collezione": collezione, "filename": filename, "tipo": "LEGGE",
                "data": "2020-01-01", "numero": "1"}

    def test_merge_collezioni_diverse(self):
        """Due occorrenze stesso filename, collezioni diverse → merge."""
        records = [self._r("test.md", "Collezione A"), self._r("test.md", "Collezione B")]
        result = _dedup(records)
        assert len(result) == 1
        assert "Collezione A;Collezione B" == result[0]["collezione"]

    def test_stessa_collezione(self):
        """Due occorrenze stesso filename, stessa collezione → skip."""
        records = [self._r("test.md", "Collezione A"), self._r("test.md", "Collezione A")]
        result = _dedup(records)
        assert len(result) == 1
        assert result[0]["collezione"] == "Collezione A"

    def test_filename_diversi(self):
        """Filename diversi → nessun merge."""
        records = [self._r("a.md", "Collezione A"), self._r("b.md", "Collezione B")]
        result = _dedup(records)
        assert len(result) == 2
