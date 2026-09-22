"""Tests for extract_abrogations.py — abrogation extraction."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lab_tools.extract_abrogations import extract_from_file, ATTO_REF, SKIP_PAT


class TestAttoRef:
    def test_legge(self):
        m = ATTO_REF.search("la legge 31 dicembre 2023, n. 207")
        assert m is not None
        assert m.group(1) == "2023"
        assert m.group(2) == "207"

    def test_decreto_legislativo(self):
        m = ATTO_REF.search("decreto legislativo 15 novembre 1993, n. 507")
        assert m is not None
        assert m.group(1) == "1993"
        assert m.group(2) == "507"

    def test_decreto_legge(self):
        m = ATTO_REF.search("decreto-legge 25 marzo 2020, n. 19")
        assert m is not None
        assert m.group(1) == "2020"
        assert m.group(2) == "19"

    def test_no_match(self):
        m = ATTO_REF.search("questo testo non ha riferimenti a leggi")
        assert m is None


class TestSkipPat:
    def test_skip_contrarie(self):
        assert SKIP_PAT.search("disposizioni contrarie")

    def test_skip_incompatibili(self):
        assert SKIP_PAT.search("norme incompatibili")

    def test_no_skip_valid(self):
        assert not SKIP_PAT.search("è abrogato il decreto legislativo")


class TestExtractFromFile:
    def test_abrogation_found(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text(
            "Art. 5. E' abrogato il decreto legislativo 15 novembre 1993, n. 507.\n"
            "Art. 6. Resta in vigore."
        )
        results = extract_from_file(f)
        assert len(results) == 1
        assert results[0]["abrogated_year"] == 1993
        assert results[0]["abrogated_number"] == 507

    def test_blanket_abrogation_skipped(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("Sono abrogate le disposizioni contrarie al presente decreto.\n")
        results = extract_from_file(f)
        assert len(results) == 0

    def test_no_abrogation(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("Questo testo non contiene abrogazioni.\n")
        results = extract_from_file(f)
        assert len(results) == 0

    def test_multiple_abrogations(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text(
            "E' abrogato l'articolo 3 della legge 31 dicembre 2023, n. 207.\n"
            "E' abrogato il decreto legislativo 15 novembre 1993, n. 507.\n"
        )
        results = extract_from_file(f)
        assert len(results) == 2
        years = {r["abrogated_year"] for r in results}
        assert 2023 in years
        assert 1993 in years
