"""Test per lab_tools.fetch_urn_acts — materia sugli atti fuori collezione."""

from __future__ import annotations

import pandas as pd
import pytest
from lab_tools.fetch_urn_acts import arricchisci_materia


def _df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class TestArricchisciMateria:
    def test_usa_sotto_titolo(self):
        """L'oggetto dell'atto sta in `sotto_titolo`, non nel `titolo` (intestazione)."""
        df = _df([
            {
                "urn": "urn:nir:stato:legge:1999-12-16;479",
                "titolo": "LEGGE 16 dicembre 1999, n. 479",
                "sotto_titolo": "Modifiche alle disposizioni sul procedimento davanti al tribunale",
            }
        ])
        out = arricchisci_materia(df)
        assert out["materia"].iloc[0] == "giustizia"

    def test_fallback_su_titolo(self):
        df = _df([{"urn": "u", "titolo": "Legge in materia fiscale", "sotto_titolo": ""}])
        assert arricchisci_materia(df)["materia"].iloc[0] == "fisco"

    @pytest.mark.parametrize("vuoto", [None, float("nan"), "   "])
    def test_fallback_su_titolo_se_sotto_titolo_vuoto(self, vuoto):
        """`sotto_titolo` assente/vuoto/NaN → si classifica il `titolo`.

        Con NaN il vecchio `str(s)` produceva "nan" (truthy) → finiva in `altro`.
        """
        df = _df([{"urn": "u", "titolo": "Legge in materia fiscale", "sotto_titolo": vuoto}])
        assert arricchisci_materia(df)["materia"].iloc[0] == "fisco"

    def test_titolo_nan_non_esplode(self):
        df = _df([{"urn": "u", "titolo": float("nan"), "sotto_titolo": float("nan")}])
        assert arricchisci_materia(df)["materia"].iloc[0] == "altro"

    def test_sotto_titolo_con_a_capo_e_doppi_spazi(self):
        """I sotto-titoli arrivano con a capo e spazi doppi: le keyword composte
        devono comunque matchare (collapse whitespace in `_normalizza`)."""
        df = _df([
            {
                "urn": "u",
                "titolo": "LEGGE 1 gennaio 2000, n. 1",
                "sotto_titolo": "Disposizioni  in materia di\nsicurezza sul lavoro   nei cantieri",
            }
        ])
        assert arricchisci_materia(df)["materia"].iloc[0] == "lavoro"

    def test_materia_sempre_valorizzata(self):
        """Nessuna riga senza materia: altrimenti l'atto è invisibile al filtro
        `materia` a valle (legal-graph / MCP)."""
        df = _df([
            {
                "urn": "a",
                "titolo": "LEGGE 7 agosto 1990, n. 241",
                "sotto_titolo": "Nuove norme in materia di procedimento amministrativo",
            },
            {
                "urn": "b",
                "titolo": "LEGGE 22 maggio 1978, n. 194",
                "sotto_titolo": "Norme per la tutela sociale della maternita'",
            },
            {"urn": "c", "titolo": "LEGGE 1 gennaio 2000, n. 1", "sotto_titolo": ""},
        ])
        out = arricchisci_materia(df)
        assert out["materia"].notna().all()
        assert (out["materia"].str.len() > 0).all()

    def test_colonne_assenti_non_esplode(self):
        df = _df([{"urn": "a"}])
        assert arricchisci_materia(df)["materia"].iloc[0] == "altro"

    @pytest.mark.parametrize(
        ("sotto_titolo", "atteso"),
        [
            ("Nuove norme in materia di rifiuti e bonifica dei siti inquinati", "ambientale"),
            ("Disposizioni in materia di imposte sui redditi", "fisco"),
            ("Riordino della disciplina degli istituti di previdenza", "previdenza"),
        ],
    )
    def test_casi_noti(self, sotto_titolo, atteso):
        df = _df([{"urn": "u", "titolo": "", "sotto_titolo": sotto_titolo}])
        assert arricchisci_materia(df)["materia"].iloc[0] == atteso
