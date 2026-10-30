"""Test per lab_tools.collezioni_probe — formati delle collezioni Normattiva."""

from __future__ import annotations

import pytest
from lab_tools.collezioni_probe import (
    STATO_CONGELATA,
    STATO_FUORI_CONFIG,
    STATO_NON_PINNATA,
    STATO_OK,
    costruisci_report,
    raggruppa,
)


def _riga(nome: str, fmt: str, atti: int = 10, creata: str = "2026-10-30") -> dict:
    return {
        "nomeCollezione": nome,
        "formatoCollezione": fmt,
        "numeroAtti": atti,
        "dataCreazione": creata,
    }


class TestRaggruppa:
    @pytest.mark.pure_unit
    def test_tiene_tutti_i_formati(self):
        out = raggruppa([_riga("Codici", "O", 40), _riga("Codici", "V", 41)])
        assert sorted(out["Codici"]) == ["O", "V"]
        assert out["Codici"]["V"]["numero_atti"] == 41

    @pytest.mark.pure_unit
    def test_scarta_righe_senza_nome_o_formato(self):
        assert raggruppa([_riga("", "O"), _riga("Codici", "")]) == {}


class TestCostruisciReport:
    @pytest.fixture
    def config(self):
        return ["Codici", "Decreti Legislativi", "Fuori API"]

    @pytest.mark.policy
    def test_stati(self, config):
        raggruppate = raggruppa(
            [
                _riga("Codici", "O"),                   # pin V assente → congelata
                _riga("Decreti Legislativi", "V"),      # pin V presente → ok
                _riga("Regolamenti ministeriali", "V"),  # non in config → fuori
                _riga("Regi decreti", "O"),             # non in config → fuori
            ]
        )
        report = costruisci_report(
            raggruppate, {"Codici": "V", "Decreti Legislativi": "V"}, config
        )
        stato = {c["nome"]: c["stato"] for c in report["collezioni"]}
        assert stato["Codici"] == STATO_CONGELATA
        assert stato["Decreti Legislativi"] == STATO_OK
        assert stato["Regi decreti"] == STATO_FUORI_CONFIG
        # "Fuori API" è in config ma non nella risposta della fonte
        assert stato["Fuori API"] == STATO_CONGELATA
        assert report["sintesi"]["congelate"] == 2

    @pytest.mark.policy
    def test_contatore_probe_consecutivi(self, config):
        raggruppate = raggruppa([_riga("Codici", "O")])
        precedente = {
            "collezioni": [
                {"nome": "Codici", "stato": STATO_CONGELATA, "senza_pin_da": 4, "formati": ["O"]}
            ]
        }
        report = costruisci_report(raggruppate, {"Codici": "V"}, config, precedente)
        codici = next(c for c in report["collezioni"] if c["nome"] == "Codici")
        assert codici["senza_pin_da"] == 5

    @pytest.mark.policy
    def test_sblocco_registrato(self, config):
        raggruppate = raggruppa([_riga("Codici", "O"), _riga("Codici", "V")])
        precedente = {
            "collezioni": [
                {"nome": "Codici", "stato": STATO_CONGELATA, "senza_pin_da": 3, "formati": ["O"]}
            ]
        }
        report = costruisci_report(raggruppate, {"Codici": "V"}, config, precedente)
        codici = next(c for c in report["collezioni"] if c["nome"] == "Codici")
        assert codici["stato"] == STATO_OK
        assert codici["senza_pin_da"] == 0
        assert any("V comparso" in c for c in report["cambiamenti"])
        assert any("sbloccata" in c for c in report["cambiamenti"])

    @pytest.mark.policy
    def test_collezione_sparita_dall_api(self, config):
        report = costruisci_report({}, {"Codici": "V"}, config)
        nomi = {c["nome"] for c in report["collezioni"]}
        assert {"Codici", "Decreti Legislativi"} <= nomi
        assert any("assente dalla risposta API" in c for c in report["cambiamenti"])

    @pytest.mark.pure_unit
    def test_primo_probe_senza_confronto(self, config):
        raggruppate = raggruppa([_riga("Codici", "V")])
        report = costruisci_report(raggruppate, {"Codici": "V"}, ["Codici"], None)
        assert report["cambiamenti"] == []
        codici = next(c for c in report["collezioni"] if c["nome"] == "Codici")
        assert codici["stato"] == STATO_OK

    def test_non_pinnata(self):
        raggruppate = raggruppa([_riga("DPCM", "M")])
        report = costruisci_report(raggruppate, {}, ["DPCM"])
        assert report["collezioni"][0]["stato"] == STATO_NON_PINNATA
