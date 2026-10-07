"""Test per lab_tools.classifica_tematich — classificatore tematico."""


from lab_tools.classifica_tematich import _classifica_oggetto


class TestClassificaOggetto:
    """Test per _classifica_oggetto(): keyword → materia."""

    def test_fisco(self):
        assert _classifica_oggetto("Disposizioni in materia fiscale e tributaria") == "fisco"

    def test_ambientale(self):
        assert _classifica_oggetto("Norme per la tutela dell'ambiente e dei rifiuti") == "ambientale"

    def test_lavoro(self):
        assert _classifica_oggetto("Disciplina dei rapporti di lavoro e sicurezza sul lavoro") == "lavoro"

    def test_sanita(self):
        assert _classifica_oggetto("Disposizioni in materia sanitaria e farmaceutica") == "sanita"

    def test_strutturale_conversione(self):
        assert _classifica_oggetto("Conversione in legge del decreto-legge n. 123") == "strutturale"

    def test_strutturale_delega(self):
        assert _classifica_oggetto("Delega al Governo per il recepimento delle direttive") == "strutturale"

    def test_giustizia(self):
        assert _classifica_oggetto("Disposizioni in materia di procedura penale") == "giustizia"

    def test_affari_esteri(self):
        assert _classifica_oggetto("Ratifica ed esecuzione dell'Accordo tra Italia e Francia") == "affari-esteri"

    def test_altro_non_classificato(self):
        assert _classifica_oggetto("Titolo senza keyword riconoscibili") == "altro"

    def test_oggetto_vuoto(self):
        assert _classifica_oggetto("") == "altro"

    def test_oggetto_none(self):
        assert _classifica_oggetto(None) == "altro"

    def test_case_insensitive(self):
        assert _classifica_oggetto("DISPOSIZIONI IN MATERIA FISCALE") == "fisco"
