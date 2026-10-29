"""Test per `lab_tools.identity`: `data_codice` e scelta dell'espressione."""

from __future__ import annotations

from lab_tools.identity import (
    build_indice_identita,
    data_codice,
    scegli_espressione,
    versione_da_filename,
)


class TestDataCodice:
    def test_originale(self):
        assert data_codice("2003-08-07_003G0227_ORIGINALE_V0.md") == "2003-08-07_003G0227"

    def test_vigenza(self):
        assert (
            data_codice("2003-08-07_003G0227_VIGENZA_2026-02-25_V0.md")
            == "2003-08-07_003G0227"
        )

    def test_con_path(self):
        assert (
            data_codice("Decreti Legislativi/2003-08-07_003G0227_VIGENZA_2026-02-25_V0.md")
            == "2003-08-07_003G0227"
        )

    def test_non_riconosciuto(self):
        assert data_codice("x.md") is None
        assert data_codice("") is None
        assert data_codice("2003-08-07.md") is None


class TestVersioneDaFilename:
    def test_vigenza(self):
        assert versione_da_filename("a_VIGENZA_2025-06-12_V0.md") == ("VIGENZA", "2025-06-12")

    def test_originale(self):
        assert versione_da_filename("a_ORIGINALE_V0.md") == ("ORIGINALE", None)

    def test_sconosciuto(self):
        assert versione_da_filename("a_V0.md") == ("", None)


class TestScegliEspressione:
    def test_vuoto(self):
        assert scegli_espressione([], set()) is None

    def test_unico(self):
        unico = "Decreti Legislativi/a_ORIGINALE_V0.md"
        assert scegli_espressione([unico], set()) == unico

    def test_is_current_vince_su_vigenza(self):
        """Il consolidato vecchio è VIGENZA ma non è la riga corrente."""
        originale = "D/a_ORIGINALE_V0.md"
        vigenza_old = "D/a_VIGENZA_2025-01-01_V0.md"
        correnti = {"a_ORIGINALE_V0.md"}
        assert scegli_espressione([originale, vigenza_old], correnti) == originale

    def test_senza_is_current_prende_vigenza_piu_recente(self):
        vecchia = "D/a_VIGENZA_2025-06-11_V0.md"
        recente = "D/a_VIGENZA_2025-10-14_V0.md"
        assert scegli_espressione([vecchia, recente], set()) == recente

    def test_originale_piu_vigenza_prende_vigenza(self):
        originale = "D/a_ORIGINALE_V0.md"
        vigenza = "D/a_VIGENZA_2025-01-01_V0.md"
        assert scegli_espressione([originale, vigenza], set()) == vigenza

    def test_deterministico(self):
        cand = ["D/a_VIGENZA_2025-01-01_V0.md", "D/b_VIGENZA_2025-01-01_V0.md"]
        assert scegli_espressione(cand, set()) == scegli_espressione(
            list(reversed(cand)), set()
        )


class TestBuildIndiceIdentita:
    def test_mappa_espressione_corrente(self):
        relpaths = [
            "D/2003-08-07_003G0227_ORIGINALE_V0.md",
            "D/2003-08-07_003G0227_VIGENZA_2026-02-25_V0.md",
            "D/1999-01-01_099G0001_ORIGINALE_V0.md",
        ]
        idx = build_indice_identita(
            relpaths, {"2003-08-07_003G0227_VIGENZA_2026-02-25_V0.md"}
        )
        assert idx["2003-08-07_003G0227"] == (
            "D/2003-08-07_003G0227_VIGENZA_2026-02-25_V0.md"
        )
        assert idx["1999-01-01_099G0001"] == "D/1999-01-01_099G0001_ORIGINALE_V0.md"

    def test_ignora_nomi_senza_data_codice(self):
        idx = build_indice_identita(["D/foo.md", "D/2003-08-07_003G0227_ORIGINALE_V0.md"], set())
        assert "foo" not in idx
        assert len(idx) == 1
