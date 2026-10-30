"""Test per il conteggio citazioni per atto (`arricchisci_normativa`)."""

from __future__ import annotations

import pandas as pd
import pytest
from lab_tools.arricchisci_normativa import _calcola_orfano, _conta_citazioni_per_atto


def _norm(righe: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "filename": r["filename"],
                "urn": r.get("urn", ""),
                "is_current": r.get("is_current", True),
            }
            for r in righe
        ]
    )


def _rif(coppie: list[tuple[str, str]], risolto: bool = True) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"fonte_filename": f, "bersaglio_filename": b, "risolto": risolto}
            for f, b in coppie
        ]
    )


class TestContaCitazioniPerAtto:
    def test_espressione_singola(self):
        norm = _norm([{"filename": "a.md", "urn": "urn:a"}])
        rif = _rif([("x.md", "a.md"), ("y.md", "a.md")])
        df = _conta_citazioni_per_atto(norm, rif)
        assert int(df["n_citazioni"].sum()) == 2
        assert int(df.loc[0, "n_citazioni"]) == 2

    def test_pluriversione_somma_sulla_corrente(self):
        """Citazioni su ORIGINALE (3) e VIGENZA (2): la corrente vale 5."""
        norm = _norm(
            [
                {"filename": "a_ORIGINALE_V0.md", "urn": "urn:a", "is_current": False},
                {"filename": "a_VIGENZA_2026-01-01_V0.md", "urn": "urn:a", "is_current": True},
            ]
        )
        rif = _rif(
            [
                ("x.md", "a_ORIGINALE_V0.md"),
                ("y.md", "a_ORIGINALE_V0.md"),
                ("z.md", "a_ORIGINALE_V0.md"),
                ("w.md", "a_VIGENZA_2026-01-01_V0.md"),
                ("v.md", "a_VIGENZA_2026-01-01_V0.md"),
            ]
        )
        df = _conta_citazioni_per_atto(norm, rif)
        corr = df[df["is_current"]].iloc[0]
        orig = df[~df["is_current"]].iloc[0]
        assert int(corr["n_citazioni"]) == 5
        assert int(orig["n_citazioni"]) == 0
        assert int(df["n_citazioni"].sum()) == 5

    def test_ignora_non_risolti(self):
        norm = _norm([{"filename": "a.md", "urn": "urn:a"}])
        rif = _rif([("x.md", "a.md"), ("y.md", "a.md")])
        rif.loc[1, "risolto"] = False
        df = _conta_citazioni_per_atto(norm, rif)
        assert int(df["n_citazioni"].sum()) == 1

    def test_riga_senza_urn_usa_il_filename(self):
        norm = _norm([{"filename": "a.md", "urn": ""}])
        rif = _rif([("x.md", "a.md")])
        df = _conta_citazioni_per_atto(norm, rif)
        assert int(df.loc[0, "n_citazioni"]) == 1

    def test_invariante_somma_conservata(self):
        norm = _norm(
            [
                {"filename": "a_ORIGINALE_V0.md", "urn": "urn:a", "is_current": False},
                {"filename": "a_VIGENZA_V0.md", "urn": "urn:a", "is_current": True},
                {"filename": "b.md", "urn": "urn:b"},
            ]
        )
        rif = _rif(
            [("x.md", "a_ORIGINALE_V0.md"), ("y.md", "a_VIGENZA_V0.md"), ("z.md", "b.md")]
        )
        df = _conta_citazioni_per_atto(norm, rif)
        assert int(df["n_citazioni"].sum()) == len(rif)

    def test_invariante_fallisce_se_un_bersaglio_manca(self):
        """Un edge verso un filename assente romperebbe la somma: deve fallire."""
        norm = _norm([{"filename": "a.md", "urn": "urn:a"}])
        rif = _rif([("x.md", "a.md"), ("y.md", "manca.md")])
        with pytest.raises(ValueError, match="invariante"):
            _conta_citazioni_per_atto(norm, rif)


class TestOrfanoAttoLevel:
    @staticmethod
    def _df(righe):
        import pandas as pd

        return pd.DataFrame(righe)

    def test_orfano_solo_sulla_corrente(self):
        df = self._df(
            [
                {"filename": "a_ORIG", "urn": "urn:a", "is_current": False, "riferimenti_interni": 0, "n_citazioni": 0},
                {"filename": "a_VIG", "urn": "urn:a", "is_current": True, "riferimenti_interni": 0, "n_citazioni": 0},
            ]
        )
        out = _calcola_orfano(df)
        assert out.loc[out["is_current"], "orfano"].tolist() == [True]
        assert out.loc[~out["is_current"], "orfano"].tolist() == [False]

    def test_citato_non_e_orfano(self):
        df = self._df(
            [{"filename": "a.md", "urn": "urn:a", "is_current": True, "riferimenti_interni": 0, "n_citazioni": 3}]
        )
        assert not _calcola_orfano(df).loc[0, "orfano"]

    def test_link_su_altra_espressione_basta(self):
        df = self._df(
            [
                {"filename": "a_ORIG", "urn": "urn:a", "is_current": False, "riferimenti_interni": 5, "n_citazioni": 0},
                {"filename": "a_VIG", "urn": "urn:a", "is_current": True, "riferimenti_interni": 0, "n_citazioni": 0},
            ]
        )
        out = _calcola_orfano(df)
        assert not out.loc[out["is_current"], "orfano"].any()

    def test_urn_vuoto_per_filename(self):
        df = self._df(
            [{"filename": "a.md", "urn": "", "is_current": True, "riferimenti_interni": 0, "n_citazioni": 0}]
        )
        assert _calcola_orfano(df).loc[0, "orfano"]
