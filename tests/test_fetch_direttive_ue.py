"""Test del fetch identità direttive UE (senza rete)."""

from __future__ import annotations

import pandas as pd
from lab_tools.fetch_direttive_ue import build_rows, celex_from_urn


class TestCelexFromUrn:
    def test_forma_senza_punto(self):
        assert celex_from_urn("urn:nir:eu:direttivaue:1989;391") == "31989L0391"

    def test_forma_con_punto(self):
        assert celex_from_urn("urn:nir:eu:direttiva.ue:2019;1937") == "32019L1937"

    def test_numero_a_quattro_cifre(self):
        assert celex_from_urn("urn:nir:eu:direttivaue:1995;46") == "31995L0046"

    def test_urn_non_ue(self):
        assert celex_from_urn("urn:nir:stato:legge:1990-08-07;241") is None

    def test_urn_malformato(self):
        assert celex_from_urn("urn:nir:eu:direttivaue:1989") is None


class TestBuildRows:
    def _targets(self):
        return {
            "31989L0391": {
                "urns": {"urn:nir:eu:direttivaue:1989;391", "urn:nir:eu:direttiva.ue:1989;391"},
                "n_citazioni": 10,
            },
            "32017L2394": {"urns": {"urn:nir:eu:direttivaue:2017;2394"}, "n_citazioni": 2},
        }

    def _works(self):
        return {
            "31989L0391": {
                "work": "http://example.org/work/1",
                "data": "1989-06-12",
                "scadenze": ["1992-12-31", "1993-06-30", "1001-01-01"],
                "in_vigore": True,
            }
        }

    def _titles(self):
        return {
            "http://example.org/work/1": {
                "ita": "Direttiva 89/391/CEE sulla sicurezza",
                "eng": "Directive 89/391/EEC on safety",
            }
        }

    def test_risolto(self):
        df = build_rows(self._targets(), self._works(), self._titles())
        row = df[df["celex"] == "31989L0391"].iloc[0]
        assert row["stato"] == "risolto"
        assert row["n_citazioni"] == 10
        assert row["titolo"] == "Direttiva 89/391/CEE sulla sicurezza"
        assert row["scadenza_recepimento"] == "1992-12-31"
        assert row["n_scadenze"] == 2
        assert "1001" not in row["scadenze"]
        assert row["in_vigore"] is True
        assert row["eli_url"].endswith("/eli/dir/1989/391/oj")
        assert row["urn_varianti"].count("urn:") == 2

    def test_non_risolto(self):
        df = build_rows(self._targets(), self._works(), self._titles())
        row = df[df["celex"] == "32017L2394"].iloc[0]
        assert row["stato"] == "non_risolto"
        assert row["motivo"] == "non_in_cellar"
        assert pd.isna(row["titolo"])
        assert pd.isna(row["eli_url"])

    def test_fallback_titolo_eng(self):
        titles = {"http://example.org/work/1": {"eng": "Only English"}}
        df = build_rows(self._targets(), self._works(), titles)
        row = df[df["celex"] == "31989L0391"].iloc[0]
        assert row["titolo"] == "Only English"

    def test_ordine_per_citazioni(self):
        df = build_rows(self._targets(), self._works(), self._titles())
        assert list(df["celex"]) == ["31989L0391", "32017L2394"]
