"""Test per lab_tools.estrai_citazioni_costituzionali."""

from lab_tools.estrai_citazioni_costituzionali import _estrai_citazioni


class TestEstraiCitazioni:
    """Test per _estrai_citazioni(): estrazione riferimenti a Costituzione."""

    def test_senza_citazione(self):
        assert _estrai_citazioni("Testo senza riferimenti.") == []

    def test_art_della_costituzione(self):
        res = _estrai_citazioni("Visto l'art. 76 della Costituzione")
        assert len(res) == 1
        assert res[0][0] == 76

    def test_articolo_della_costituzione(self):
        res = _estrai_citazioni("Visto l'articolo 117 della Costituzione")
        assert len(res) == 1
        assert res[0][0] == 117

    def test_articoli_multipli(self):
        """'articoli 76 e 87 della Costituzione' -> prende il primo (76)."""
        res = _estrai_citazioni("Visti gli articoli 76 e 87 della Costituzione")
        assert len(res) == 2
        assert res[0][0] == 76
        assert res[1][0] == 87

    def test_articoli_tre(self):
        """'articoli 76, 87 e 117' -> prende tutti."""
        res = _estrai_citazioni("Visti gli articoli 76, 87 e 117 della Costituzione")
        assert len(res) == 3
        assert [r[0] for r in res] == [76, 87, 117]

    def test_multiple_occorrenze(self):
        body = "Visto l'art. 76 della Costituzione. Visto l'art. 117 della Costituzione."
        res = _estrai_citazioni(body)
        assert len(res) == 2
        assert res[0][0] == 76
        assert res[1][0] == 117

    def test_fuori_range(self):
        """Articoli fuori range 1-139 vengono scartati."""
        res = _estrai_citazioni("Visto l'art. 999 della Costituzione")
        assert res == []

    def test_contesto_popolato(self):
        res = _estrai_citazioni("Visto l'art. 32 della Costituzione in materia di salute")
        assert len(res) == 1
        _, contesto = res[0]
        assert "art. 32" in contesto
        assert "salute" in contesto

    def test_no_falsi_articolo(self):
        """'art. 1' senza 'della Costituzione' non deve matchare."""
        res = _estrai_citazioni("Visto l'art. 1 della legge n. 241/1990")
        assert res == []

    def test_da_fixture_con_celex(self):
        """Il fixture con_celex.md cita art. 76 e 87 della Costituzione."""
        from pathlib import Path
        text = (Path(__file__).resolve().parent / "fixtures" / "con_celex.md").read_text("utf-8")
        res = _estrai_citazioni(text)
        assert len(res) == 2
        arts = {r[0] for r in res}
        assert 76 in arts
        assert 87 in arts

    def test_da_fixture_frontmatter(self):
        """Il fixture con_celex_fm.md cita art. 76 e 87 della Costituzione."""
        from pathlib import Path
        text = (Path(__file__).resolve().parent / "fixtures" / "con_celex_fm.md").read_text("utf-8")
        res = _estrai_citazioni(text)
        assert len(res) == 2
        arts = {r[0] for r in res}
        assert 76 in arts
        assert 87 in arts
