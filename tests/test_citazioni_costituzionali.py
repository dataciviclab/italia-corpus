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


class TestRegressioni:
    """Regression test per fix: niente falsi positivi da leggi ordinarie."""

    def test_legge_ordinaria_prima(self):
        """'art. 1 della legge n. 241/1990 e l'art. 76 della Costituzione' → solo 76."""
        body = "Visto l'art. 1 della legge n. 241/1990 e l'art. 76 della Costituzione"
        res = _estrai_citazioni(body)
        arts = {r[0] for r in res}
        assert 76 in arts
        assert 1 not in arts

    def test_decreto_prima(self):
        """'art. 3 del decreto. Visto l'art. 117 della Costituzione' → solo 117."""
        body = "Ai sensi dell'art. 3 del decreto. Visto l'art. 117 della Costituzione"
        res = _estrai_citazioni(body)
        arts = {r[0] for r in res}
        assert 117 in arts
        assert 3 not in arts

    def test_legge_dopo(self):
        """'art. 117 della Costituzione e art. 3 della legge' → solo 117."""
        body = "Visto l'art. 117 della Costituzione e l'art. 3 della legge n. 241"
        res = _estrai_citazioni(body)
        arts = {r[0] for r in res}
        assert 117 in arts
        assert 3 not in arts

    def test_articoli_ordinari_intromessi(self):
        """'degli articoli 2, 3 e 4 del decreto e degli articoli 76 e 87 della Cost.'"""
        body = "a norma degli articoli 2, 3 e 4 del decreto e degli articoli 76 e 87 della Costituzione"
        res = _estrai_citazioni(body)
        arts = {r[0] for r in res}
        assert 76 in arts
        assert 87 in arts
        assert 2 not in arts
        assert 3 not in arts
        assert 4 not in arts

    def test_markdown_link_non_contamina(self):
        """Numeri dentro URL markdown non devono contaminare l'estrazione.

        Esempio reale: [87 della Costituzione](https://...const#art_76)
        Il link contiene 1947-12-27, const#art_76, N2Ls — non devono essere
        estratti come articoli costituzionali.
        """
        body = (
            "...Visti gli articoli 76 e 87 della Costituzione"
            "(https://www.normattiva.it/"
            "uri-res/N2Ls?urn:nir:stato:costituzione:1947-12-27;const#art_76)"
        )
        res = _estrai_citazioni(body)
        arts = {r[0] for r in res}
        assert 76 in arts, f"76 non trovato in {arts}"
        assert 87 in arts, f"87 non trovato in {arts}"
        # Numeri dal link URL non devono apparire
        assert 2 not in arts, f"falso positivo 2 in {arts}"
        assert 12 not in arts, f"falso positivo 12 in {arts}"
        assert 27 not in arts, f"falso positivo 27 in {arts}"


class TestFoldInRiferimenti:
    """La citazione costituzionale diventa un arco di `riferimenti` (#rewiring)."""

    def _records(self):
        return [
            {
                "fonte_filename": "Leggi/2020-01-02_20G00001_VIGENZA_2026-01-01_V0.md",
                "fonte_collezione": "Leggi",
                "fonte_anno": 2020,
                "fonte_tipo": "LEGGE",
                "articolo": 117,
                "contesto": "Visto l'articolo 117 della Costituzione",
            }
        ]

    def test_arco_con_bersaglio_id(self):
        from lab_tools.grafo_riferimenti import _archi_citazioni

        normativa = {
            "2020-01-02_20G00001_VIGENZA_2026-01-01_V0.md": {
                "urn": "urn:nir:stato:legge:2020-01-02;1",
                "materia": "istituzioni",
                "stato": "vigente",
                "anno_atto": 2020,
            }
        }
        archi = _archi_citazioni(self._records(), normativa)
        assert len(archi) == 1
        a = archi[0]
        assert a["bersaglio_id"] == "costituzione:art:117"
        assert a["bersaglio_urn"] == ""
        assert a["origine"] == "costituzione"
        assert a["rel_type"] == "cita_costituzione"
        assert a["fonte_urn"] == "urn:nir:stato:legge:2020-01-02;1"
        assert a["risolto"] is True

    def test_pk_distingue_articoli(self):
        """Senza bersaglio_id nella chiave, tutti gli articoli collasserebbero."""
        from lab_tools.grafo_riferimenti import _archi_citazioni, _chiave_arco

        archi = _archi_citazioni(self._records(), {})
        k117 = _chiave_arco(archi[0])
        altro = {**archi[0], "bersaglio_id": "costituzione:art:118"}
        assert k117 != _chiave_arco(altro)
        assert k117[1] == "costituzione:art:117"

    def test_articolo_non_numerico_scartato(self):
        from lab_tools.grafo_riferimenti import _archi_citazioni

        assert _archi_citazioni([{"fonte_filename": "x.md", "articolo": "n/d"}], {}) == []
