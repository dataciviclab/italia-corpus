"""Test per lab_tools.grafo_riferimenti — estrazione link e risoluzione path."""

from pathlib import Path

import pytest

from lab_tools.grafo_riferimenti import estrai_link, risolvi_path

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
    """Test per risolvi_path(): risoluzione path relativi ../ ."""

    def test_risoluzione_semplice(self):
        """../Decreti Legislativi/TU.md da DL Proroghe/x.md."""
        link = "Decreti Legislativi/TU.md"
        current = Path("DL Proroghe") / "x.md"
        result = risolvi_path(link, current)
        assert result is not None
        assert str(result) == "Decreti Legislativi/TU.md"

    def test_risoluzione_subdir(self):
        """../Decreti Legislativi/Sub/Norma.md da DL Proroghe/x.md."""
        link = "Decreti Legislativi/Sub/Norma.md"
        current = Path("DL Proroghe") / "x.md"
        result = risolvi_path(link, current)
        assert result is not None
        assert str(result) == "Decreti Legislativi/Sub/Norma.md"

    def test_risoluzione_root_collezione(self):
        """../Leggi/Legge.md da Decreti Legislativi/x.md."""
        link = "Leggi/Legge.md"
        current = Path("Decreti Legislativi") / "x.md"
        result = risolvi_path(link, current)
        assert result is not None
        assert str(result) == "Leggi/Legge.md"

    def test_risoluzione_file_in_root(self):
        """File in root (raro, ma gestito) -> None per sicurezza."""
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
