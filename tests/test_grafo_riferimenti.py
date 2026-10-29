"""Test per lab_tools.grafo_riferimenti — estrazione link e risoluzione path."""

from pathlib import Path

import pytest
from lab_tools.grafo_riferimenti import (
    _chiave_arco,
    _dedup_archi,
    _verifica_pk_unica,
    estrai_link,
    risolvi_path,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestEstraiLink:
    """Test per estrai_link(): estrazione link ../ dal body markdown."""

    def test_senza_link(self):
        body = "Testo senza link relativi."
        assert estrai_link(body) == []

    def test_link_singolo(self):
        body = "Vedi ../Decreti Legislativi/TU.md per dettagli."
        links = estrai_link(body)
        assert len(links) == 1
        assert "Decreti Legislativi/TU.md" in links[0]

    def test_link_multipli(self):
        body = (
            "Riferimenti: ../DL%20e%20leggi%20di%20conversione/LeggeX.md "
            "e ../Decreti%20Legislativi/DecretoY.md."
        )
        links = estrai_link(body)
        assert len(links) == 2

    def test_url_decode(self):
        body = "Vedi ../DL%20e%20leggi%20di%20conversione/Norma%20importante.md"
        links = estrai_link(body)
        assert len(links) == 1
        assert "DL e leggi di conversione" in links[0]
        assert "Norma importante" in links[0]

    def test_link_con_parentesi(self):
        """Link con %28 %29 (parentesi) nel nome file."""
        body = "Cfr ../Atti%20normativi%20abrogati%20%28in%20originale%29/Testo.md"
        links = estrai_link(body)
        assert len(links) == 1
        assert "Atti normativi abrogati (in originale)" in links[0]

    def test_body_vuoto(self):
        assert estrai_link("") == []

    def test_link_duplicato(self):
        """Stesso link appare due volte -> estrai_link le trova entrambe."""
        body = "Vedi ../Leggi/LeggeX.md. Rivedi ../Leggi/LeggeX.md."
        links = estrai_link(body)
        assert len(links) == 2
        assert links[0] == links[1]

    def test_no_falsi_positivi(self):
        """Link assoluti (http/https) non devono matchare."""
        body = "Vedi https://www.normattiva.it/uri-res/N2Ls e http://example.com"
        assert estrai_link(body) == []


class TestRisolviPath:
    """Test per risolvi_path(): path relativi a COLLEZIONI_ROOT.

    Formato parquet stabile: ``Collezione/file.md`` (sotto collezioni/,
    stessa forma di prima del move).
    """

    def test_risoluzione_semplice(self):
        """../Codici/TU.md da DL Proroghe/x.md."""
        link = "Codici/TU.md"
        current = Path("DL Proroghe") / "x.md"
        result = risolvi_path(link, current)
        assert result is not None
        assert str(result) == "Codici/TU.md"

    def test_risoluzione_subdir(self):
        """../Codici/Sub/Norma.md da DL Proroghe/x.md."""
        link = "Codici/Sub/Norma.md"
        current = Path("DL Proroghe") / "x.md"
        result = risolvi_path(link, current)
        assert result is not None
        assert str(result) == "Codici/Sub/Norma.md"

    def test_risoluzione_root_collezione(self):
        """../Leggi/Legge.md da Decreti Legislativi/x.md."""
        link = "Leggi/Legge.md"
        current = Path("Decreti Legislativi") / "x.md"
        result = risolvi_path(link, current)
        assert result is not None
        assert str(result) == "Leggi/Legge.md"

    def test_risoluzione_file_in_root(self):
        """File in root collezioni (raro) -> None per sicurezza."""
        link = "Altro/file.md"
        current = Path("file_nella_root.md")
        result = risolvi_path(link, current)
        assert result is None


class TestEstraiSuFixture:
    """Test di estrazione su un file fixture reale."""

    def test_fixture_con_celex(self):
        """Il fixture con_celex.md non ha link ../."""
        body = (FIXTURES / "con_celex.md").read_text("utf-8")
        links = estrai_link(body)
        assert links == []

    def test_fixture_frontmatter(self):
        """Il fixture con_celex_fm.md non ha link ../."""
        body = (FIXTURES / "con_celex_fm.md").read_text("utf-8")
        links = estrai_link(body)
        assert links == []


def _arco(fonte, bersaglio_path="", bersaglio_fn="", origine="akn", peso=1, collezione=""):
    """Arco minimo con i campi che compongono la PK del clean."""
    return {
        "fonte_filename": fonte,
        "fonte_collezione": collezione,
        "bersaglio_filename": bersaglio_fn or bersaglio_path,
        "bersaglio_path": bersaglio_path,
        "origine": origine,
        "peso": peso,
    }


class TestChiaveArco:
    """La chiave rispecchia la PK del clean (`clean.sql`)."""

    def test_akn_basename_usa_collezione(self):
        a = _arco("a.md", bersaglio_path="b.md", origine="akn", collezione="Leggi")
        assert _chiave_arco(a) == ("Leggi/a.md", "b.md", "akn")

    def test_regex_relpath(self):
        a = _arco("Leggi/a.md", bersaglio_path="Codici/b.md", origine="regex")
        assert _chiave_arco(a) == ("Leggi/a.md", "Codici/b.md", "regex")

    def test_regex_non_risolto_usa_il_link(self):
        """`bersaglio_path` vuoto → la PK usa `bersaglio_filename` (il link)."""
        a = _arco("Leggi/a.md", bersaglio_path="", bersaglio_fn="Altro/x.md", origine="regex")
        assert _chiave_arco(a) == ("Leggi/a.md", "Altro/x.md", "regex")


class TestDedupArchi:
    """Un arco per chiave; `peso` sommato."""

    def test_stessa_coppia_collassa_e_somma_peso(self):
        archi = [
            _arco("a.md", bersaglio_path="b.md"),
            _arco("a.md", bersaglio_path="b.md"),
        ]
        out = _dedup_archi(archi)
        assert len(out) == 1
        assert out[0]["peso"] == 2

    def test_origine_diversa_non_collassa(self):
        archi = [
            _arco("a.md", bersaglio_path="b.md", origine="akn"),
            _arco("a.md", bersaglio_path="b.md", origine="regex", peso=3),
        ]
        assert len(_dedup_archi(archi)) == 2

    def test_coppie_diverse_restano(self):
        archi = [
            _arco("a.md", bersaglio_path="b.md"),
            _arco("a.md", bersaglio_path="c.md"),
            _arco("x.md", bersaglio_path="b.md"),
        ]
        assert len(_dedup_archi(archi)) == 3

    def test_lista_vuota(self):
        assert _dedup_archi([]) == []


class TestVerificaPkUnica:
    """Invariante: dopo `_dedup_archi` la PK del clean è unica."""

    def test_unica_non_solleva(self):
        archi = [
            _arco("a.md", bersaglio_path="b.md", origine="akn"),
            _arco("a.md", bersaglio_path="b.md", origine="regex"),
            _arco("a.md", bersaglio_path="c.md", origine="akn"),
        ]
        _verifica_pk_unica(archi)  # non solleva

    def test_regex_non_risolti_distinti_non_collassano(self):
        """Regressione: due link non risolti diversi NON sono duplicati."""
        archi = [
            _arco("a.md", bersaglio_path="", bersaglio_fn="Altro/x.md", origine="regex"),
            _arco("a.md", bersaglio_path="", bersaglio_fn="Altro/y.md", origine="regex"),
        ]
        _verifica_pk_unica(archi)  # non solleva

    def test_dedup_rende_unica_anche_l_unione(self):
        """Regex non risolti + AKN alias: dopo il dedup la PK è unica."""
        archi = [
            _arco("a.md", bersaglio_path="", bersaglio_fn="Altro/x.md", origine="regex"),
            _arco("a.md", bersaglio_path="", bersaglio_fn="Altro/y.md", origine="regex"),
            _arco("a.md", bersaglio_path="b.md"),
            _arco("a.md", bersaglio_path="b.md"),
        ]
        _verifica_pk_unica(_dedup_archi(archi))  # non solleva

    def test_duplicato_solleva(self):
        archi = [
            _arco("a.md", bersaglio_path="b.md"),
            _arco("a.md", bersaglio_path="b.md"),
        ]
        with pytest.raises(AssertionError, match="dedup incompleto"):
            _verifica_pk_unica(archi)
