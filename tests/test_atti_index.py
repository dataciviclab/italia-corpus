"""Test per lab_tools.atti_index — indice del catalogo Normattiva."""

from __future__ import annotations

import pytest
from lab_tools.atti_index import (
    build_rows,
    collega_corpus,
    deduplica,
    indice_corpus,
    riepilogo,
)


def _atto(**kw) -> dict:
    base = {
        "codiceRedazionale": "24G00100",
        "dataGU": "2024-07-10",
        "denominazioneAtto": "DECRETO-LEGGE",
        "annoProvvedimento": "2024",
        "numeroProvvedimento": "100",
        "dataEmanazione": "2024-07-09T00:00:00Z",
        "numeroGU": "160",
        "titoloAtto": "[Disposizioni urgenti in materia di prova. (24G00100)  ]",
        "descrizioneAtto": "DECRETO-LEGGE 9 luglio 2024, n. 100",
    }
    base.update(kw)
    return base


class TestBuildRows:
    @pytest.mark.pure_unit
    def test_mappa_classe_e_stato(self):
        rows = build_rows([("3", [_atto()]), ("1", [_atto(codiceRedazionale="24G00200")])])
        assert [r["stato"] for r in rows] == ["abrogato", "non_abrogato"]
        assert [r["classe"] for r in rows] == ["3", "1"]

    @pytest.mark.pure_unit
    @pytest.mark.parametrize("campo", ["codiceRedazionale", "dataGU"])
    def test_scarta_senza_identita(self, campo):
        rows = build_rows([("1", [_atto(**{campo: ""})])])
        assert rows == []

    @pytest.mark.pure_unit
    def test_normalizza_titolo_e_date(self):
        rows = build_rows([("1", [_atto(titoloAtto="x" * 500)]), ("1", [_atto(codiceRedazionale="24G00201")])])
        assert len(rows[0]["titolo"]) == 300
        assert rows[0]["data_emanazione"] == "2024-07-09"
        assert rows[1]["data_emanazione"] == "2024-07-09"


class TestDeduplica:
    @pytest.mark.policy
    def test_classe_abrogato_vince(self):
        """Un DL aggiornato (classe 2) e poi abrogato (classe 3) → una riga, 3."""
        rows = build_rows(
            [
                ("2", [_atto(codiceRedazionale="26G00061")]),
                ("3", [_atto(codiceRedazionale="26G00061")]),
            ]
        )
        uniche, scartate = deduplica(rows)
        assert scartate == 1
        assert len(uniche) == 1
        assert uniche[0]["classe"] == "3"
        assert uniche[0]["stato"] == "abrogato"

    @pytest.mark.pure_unit
    def test_chiave_diversa_resta(self):
        rows = build_rows(
            [
                ("1", [_atto(codiceRedazionale="26G00061", dataGU="2026-04-03")]),
                ("1", [_atto(codiceRedazionale="26G00061", dataGU="2026-04-04")]),
            ]
        )
        uniche, scartate = deduplica(rows)
        assert (len(uniche), scartate) == (2, 0)


class TestIndiceCorpus:
    @pytest.mark.pure_unit
    def test_chiave_data_gu_da_filename(self):
        idx = indice_corpus(
            [
                {
                    "filename": "2024-07-10_24G00100_VIGENZA_2025-01-01_V0.md",
                    "urn": "urn:nir:stato:decreto.legge:2024-07-09;100",
                }
            ]
        )
        assert idx[("24G00100", "2024-07-10")]["urn"].endswith(";100")

    @pytest.mark.pure_unit
    def test_filename_senza_data_codice_ignorato(self):
        assert indice_corpus([{"filename": "senza-prefisso.md", "urn": "urn:x"}]) == {}


class TestCollegaCorpus:
    @pytest.mark.pure_unit
    def test_join_esatto_per_codice_e_data(self):
        """Il codice redazionale è riciclato: la data GU disambigua."""
        rows = build_rows(
            [
                ("1", [_atto(codiceRedazionale="72U0670", dataGU="1972-11-10", annoProvvedimento="1972")]),
                ("1", [_atto(codiceRedazionale="72U0670", dataGU="1872-01-01", annoProvvedimento="1872")]),
            ]
        )
        idx = indice_corpus(
            [
                {
                    "filename": "1972-11-10_72U0670_ORIGINALE_V0.md",
                    "urn": "urn:nir:stato:decreto.del.presidente.della.repubblica:1972-10-25;670",
                }
            ]
        )
        ident = collega_corpus(rows, idx, osservazioni_minime=1)

        per_data = {r["data_gu"]: r for r in rows}
        assert per_data["1972-11-10"]["in_corpus"] is True
        assert per_data["1872-01-01"]["in_corpus"] is False
        assert ident["urn_corpus"] == 1

    @pytest.mark.pure_unit
    def test_urn_appresa_da_corpus(self):
        corpus = [
            {
                "filename": "2024-07-10_24G00100_ORIGINALE_V0.md",
                "urn": "urn:nir:stato:decreto.legge:2024-07-09;100",
            }
        ]
        righe = build_rows([("1", [_atto(), _atto(codiceRedazionale="24G00200", numeroProvvedimento="200")])])
        ident = collega_corpus(righe, indice_corpus(corpus), osservazioni_minime=1)

        presente, assente = righe
        assert presente["urn_fonte"] == "corpus"
        # denominazione appresa ("DECRETO-LEGGE" → stato/decreto.legge)
        assert assente["urn"] == "urn:nir:stato:decreto.legge:2024-07-09;200"
        assert assente["urn_fonte"] == "appresa"
        assert ident["urn_appresa"] == 1

    @pytest.mark.pure_unit
    def test_urn_appresa_da_denominazione_univoca(self):
        corpus = [
            {"filename": "2024-07-10_24G00100_ORIGINALE_V0.md", "urn": "urn:nir:stato:decreto:2024-07-09;100"},
        ]
        righe = build_rows(
            [
                ("1", [_atto(codiceRedazionale="24G00100", denominazioneAtto="DECRETO")]),
                ("1", [_atto(codiceRedazionale="24G00999", denominazioneAtto="DECRETO", numeroProvvedimento="999")]),
            ]
        )
        ident = collega_corpus(righe, indice_corpus(corpus), osservazioni_minime=1)
        assert ident["denominazioni_ambigue"] == []
        assert righe[1]["urn"] == "urn:nir:stato:decreto:2024-07-09;999"
        assert righe[1]["urn_fonte"] == "appresa"

    @pytest.mark.pure_unit
    def test_urn_non_inventata_se_denominazione_ambigua(self):
        """La stessa denominazione mappa su due tipi diversi → nessuna URN."""
        corpus = [
            {"filename": "2024-07-10_24G00100_ORIGINALE_V0.md", "urn": "urn:nir:stato:decreto:2024-07-09;100"},
            {
                "filename": "2024-07-11_24G00101_ORIGINALE_V0.md",
                "urn": "urn:nir:stato:decreto.ministeriale:2024-07-10;101",
            },
        ]
        righe = build_rows(
            [
                ("1", [_atto(codiceRedazionale="24G00100", denominazioneAtto="DECRETO")]),
                ("1", [_atto(codiceRedazionale="24G00101", denominazioneAtto="DECRETO", dataGU="2024-07-11")]),
                ("1", [_atto(codiceRedazionale="24G00999", denominazioneAtto="DECRETO", numeroProvvedimento="999")]),
            ]
        )
        ident = collega_corpus(righe, indice_corpus(corpus), osservazioni_minime=1)
        assert ident["denominazioni_ambigue"] == ["DECRETO"]
        assert righe[2]["urn"] is None
        assert righe[2]["urn_fonte"] is None

    @pytest.mark.pure_unit
    def test_urn_assente_senza_denominazione_o_numero(self):
        righe = build_rows(
            [("1", [_atto(codiceRedazionale="99G00001", denominazioneAtto="ALTRO", numeroProvvedimento="")])]
        )
        ident = collega_corpus(righe, {}, osservazioni_minime=1)
        assert righe[0]["urn"] is None
        assert righe[0]["urn_fonte"] is None
        assert ident["urn_assente"] == 1


class TestSogliaApprendimento:
    @pytest.mark.policy
    def test_denominazione_rara_con_emittente_strutturale(self):
        """Regio decreto-legge: 1 osservazione, ma `stato` è strutturale."""
        righe = build_rows(
            [
                (
                    "1",
                    [
                        _atto(
                            codiceRedazionale="30G00001",
                            denominazioneAtto="REGIO DECRETO-LEGGE",
                            annoProvvedimento="1930",
                            numeroProvvedimento="1",
                            dataEmanazione="1930-01-02T00:00:00Z",
                        )
                    ],
                )
            ]
        )
        indice = {
            ("30G00001", "2024-07-10"): {
                "urn": "urn:nir:stato:regio.decreto.legge:1930-01-02;1",
                "filename": "2024-07-10_30G00001_ORIGINALE_V0.md",
            }
        }
        collega_corpus(righe, indice)
        assert righe[0]["tipo_slug"] == "regio.decreto.legge"
        assert righe[0]["emittente"] == "stato"
        assert righe[0]["urn"] == "urn:nir:stato:regio.decreto.legge:1930-01-02;1"

    @pytest.mark.policy
    @pytest.mark.parametrize("n_maggioranza,mappato", [(19, True), (12, False)])
    def test_maggioranza_richiede_95_per_cento(self, n_maggioranza, mappato):
        """19/20 = 95% mappa; 12/20 = 60% no (denominazione ambigua)."""
        righe = []
        indice = {}
        for i in range(20):
            tipo = "decreto" if i < n_maggioranza else "decreto.ministeriale"
            righe.append(
                {
                    "codice_redazionale": f"00G{i:05d}",
                    "data_gu": "2000-01-01",
                    "denominazione": "DECRETO",
                    "anno": 2000,
                    "numero": str(i),
                    "data_emanazione": "1999-12-31",
                }
            )
            indice[(f"00G{i:05d}", "2000-01-01")] = {
                "urn": f"urn:nir:stato:{tipo}:1999-12-31;{i}",
                "filename": f"2000-01-01_00G{i:05d}_ORIGINALE_V0.md",
            }
        ident = collega_corpus(righe, indice, osservazioni_minime=1)
        assert (ident["denominazioni_ambigue"] == []) == mappato

    @pytest.mark.policy
    def test_poche_osservazioni_tipo_noto_ma_nessuna_urn(self):
        """1 solo decreto di un ministero: il tipo si sa, l'emittente no."""
        righe = [
            {
                "codice_redazionale": "00G00001",
                "data_gu": "2000-01-01",
                "denominazione": "DECRETO",
                "anno": 2000,
                "numero": "1",
                "data_emanazione": "1999-12-31",
                "corpus_urn": "urn:nir:stato:decreto:1999-12-31;1",
            }
        ]
        ident = collega_corpus(righe, {})
        assert ident["tipo_noto"] == 0


class TestRiepilogo:
    @pytest.mark.pure_unit
    def test_conta_corpus_per_decade_e_tipo(self):
        righe = [
            {"anno": 2024, "in_corpus": True, "denominazione": "LEGGE"},
            {"anno": 2024, "in_corpus": False, "denominazione": "LEGGE"},
            {"anno": 1899, "in_corpus": False, "denominazione": "REGIO DECRETO"},
        ]
        rep = riepilogo(righe)
        assert rep["totale"] == 3
        assert rep["in_corpus"] == 1
        assert rep["decadi"][2020] == [2, 1]
        assert rep["decadi"][1890] == [1, 0]
        assert rep["tipi"]["LEGGE"] == [2, 1]
