"""Tests for extract_pnrr_refs.py — PNRR reference extraction."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lab_tools.extract_pnrr_refs import extract_pnrr_refs


class TestExtractPnrrRefs:
    def test_missione_componente_investimento(self):
        text = "In attuazione della Missione 1, Componente 2, Investimento 1.7 del PNRR"
        refs = extract_pnrr_refs(text)
        assert len(refs) >= 1
        r = refs[0]
        assert r["missione"] == 1
        assert r["componente"] == 2
        assert r["investimento"] == "1.7"

    def test_missione_senza_investimento(self):
        text = "nell'ambito della Missione 5, componente 2 del PNRR"
        refs = extract_pnrr_refs(text)
        assert len(refs) >= 1
        assert refs[0]["missione"] == 5
        assert refs[0]["componente"] == 2
        assert refs[0]["investimento"] is None

    def test_shorthand_mnci(self):
        text = "M1C2-I1.7"
        refs = extract_pnrr_refs(text)
        assert len(refs) >= 1
        shorthand = [r for r in refs if r["tipo"] == "shorthand"]
        assert len(shorthand) >= 1
        r = shorthand[0]
        assert r["missione"] == 1
        assert r["componente"] == 2
        assert r["investimento"] == "1.7"

    def test_milestone(self):
        text = "raggiungimento del milestone M6C1-4"
        refs = extract_pnrr_refs(text)
        assert len(refs) >= 1
        assert refs[0]["missione"] == 6
        assert refs[0]["componente"] == 1

    def test_no_pnrr(self):
        text = "Questo testo non contiene riferimenti PNRR"
        refs = extract_pnrr_refs(text)
        assert len(refs) == 0

    def test_multiple_refs(self):
        text = """
        In attuazione della Missione 1, Componente 1 del PNRR,
        nonche' della Missione 2, Componente 2, Investimento 1.4 del PNRR
        """
        refs = extract_pnrr_refs(text)
        assert len(refs) >= 2
        missioni = {r["missione"] for r in refs}
        assert 1 in missioni
        assert 2 in missioni

    def test_case_insensitive(self):
        text = "missione 3, componente 1 del pnrr"
        refs = extract_pnrr_refs(text)
        assert len(refs) >= 1
        assert refs[0]["missione"] == 3
