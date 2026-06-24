"""Test per lab_tools.extract.extract() e funzioni ausiliarie."""

from pathlib import Path

import pytest

from lab_tools.extract import extract, _estrai_riferimento_ue, _dedup

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# ─── file legacy (senza frontmatter, regex fallback) ─────────────


def test_con_celex_body():
    """File legacy (senza frontmatter): estrae tipo/data/numero/entrata_vigore dal body.
    CELEX non estraibile dall'oggetto (nessun riferimento UE nell'oggetto)."""
    result = extract(FIXTURES / "con_celex.md")
    assert result is not None
    assert result["tipo"] == "DECRETO LEGISLATIVO"
    assert result["data"] == "2020-03-15"
    assert result["numero"] == "45"
    assert result["oggetto"] == "con_celex"
    # CELEX non presente nell'oggetto (solo nel body, non più estratto)
    assert result["celex"] == ""
    assert result["anno_atto"] == 2020
    assert result["anno_dir"] == 0
    assert result["ritardo"] is None
    assert result["collezione"] == ""
    # Nuovi campi frontmatter: legacy → None/ignoto
    assert result["vigente"] is None
    assert result["urn"] == ""
    assert result["codice_redazionale"] == ""


def test_collezione_esplicita():
    """Parametro collezione passato a extract()."""
    result = extract(FIXTURES / "con_celex.md", collezione="Test")
    assert result is not None
    assert result["collezione"] == "Test"


def test_senza_celex():
    """File (legacy) senza CELEX né entrata vigore: campi vuoti."""
    result = extract(FIXTURES / "senza_celex.md")
    assert result is not None
    assert result["tipo"] == "LEGGE"
    assert result["data"] == "2021-01-10"
    assert result["numero"] == "1"
    assert result["celex"] == ""
    assert result["anno_dir"] == 0
    assert result["ritardo"] is None
    assert result["vigente"] is None
    assert result["urn"] == ""


# ─── frontmatter YAML (fast path) ────────────────────────────────


def test_con_celex_frontmatter():
    """File con frontmatter: tipo, data, titolo dal frontmatter,
    CELEX costruito dal riferimento UE nell'oggetto."""
    result = extract(FIXTURES / "con_celex_fm.md")
    assert result is not None
    assert result["tipo"] == "DECRETO LEGISLATIVO"
    assert result["data"] == "2020-03-15"
    assert result["numero"] == "45"
    assert "Attuazione direttiva" in result["oggetto"]
    assert result["celex"] == "32018L1234"
    assert result["anno_atto"] == 2020
    assert result["anno_dir"] == 2018
    assert result["ritardo"] == 2
    assert result["vigente"] is True
    assert result["urn"] == "urn:nir:stato:decreto.legislativo:2020-03-15;45"
    assert result["codice_redazionale"] == "020G01234"


# ─── helper unitari ──────────────────────────────────────────────


def test_estrai_riferimento_ue():
    """_estrai_riferimento_ue costruisce CELEX da riferimenti UE nell'oggetto."""
    # Direttiva → L
    assert _estrai_riferimento_ue("Attuazione della direttiva 2019/944") == ("32019L0944", 2019)
    # Regolamento → R
    assert _estrai_riferimento_ue("Attuazione del regolamento (UE) 2023/1113") == ("32023R1113", 2023)
    # Decisione → D
    assert _estrai_riferimento_ue("Attuazione della decisione 2020/135") == ("32020D0135", 2020)
    # Formato con trattino
    assert _estrai_riferimento_ue("Attuazione della direttiva UE 2018-1972") == ("32018L1972", 2018)
    # Senza riferimento
    assert _estrai_riferimento_ue("Disposizioni in materia") == ("", None)
    assert _estrai_riferimento_ue("") == ("", None)
    assert _estrai_riferimento_ue(None) == ("", None)

    # ── Casi problematici dalla review ──

    # regolamento (UE) n. — anno dopo slash
    assert _estrai_riferimento_ue(
        "regolamento (UE) n. 2018/1727"
    ) == ("32018R1727", 2018)

    # regolamento (UE) n. con anno prima dello slash (formato invertito)
    assert _estrai_riferimento_ue(
        "regolamento (UE) n. 1025/2012"
    ) == ("32012R1025", 2012)

    # direttiva di esecuzione
    assert _estrai_riferimento_ue(
        "direttiva di esecuzione 2014/111/UE recante modifica della direttiva 2009/15/CE"
    ) == ("32014L0111", 2014)

    # plurali: prende la prima del gruppo, salta la secondaria
    assert _estrai_riferimento_ue(
        "direttive 2006/17/CE e 2006/86/CE, che attuano la direttiva 2004/23/CE"
    ) == ("32006L0017", 2006)

    # riferimenti multipli: salta 'abroga la decisione ...'
    assert _estrai_riferimento_ue(
        "regolamento (UE) n. 2018/1727 ... che abroga la decisione 2002/187/GAI"
    ) == ("32018R1727", 2018)

    # regolamento delegato
    assert _estrai_riferimento_ue(
        "regolamento delegato (UE) 2023/2631"
    ) == ("32023R2631", 2023)


# ─── edge cases ──────────────────────────────────────────────────


def test_base64_ignorato():
    """Il formato BASE64 (nomi data_nome) non è più gestito — ramo rimosso.
    I file con solo testo libero senza struttura tornano None."""
    dummy = FIXTURES / "_dummy_base64.md"
    dummy.write_text("Testo senza struttura riconoscibile", encoding="utf-8")
    try:
        assert extract(dummy) is None
    finally:
        dummy.unlink()


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
                "data": "2020-01-01", "numero": "1", "vigente": True,
                "urn": "", "codice_redazionale": ""}

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
