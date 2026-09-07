"""Test per lab_tools.fetch_normattiva."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lab_tools.fetch_normattiva import (
    _build_urn_index,
    _collection_subdir,
    _load_collezioni,
    _update_urn_index,
    process_collection,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO = Path(__file__).resolve().parent.parent


# ── _load_collezioni ────────────────────────────────────────────────


class TestLoadCollezioni:

    def test_loads_list_from_file(self, tmp_path):
        config = tmp_path / "config"
        config.mkdir()
        col_file = config / "collezioni.txt"
        col_file.write_text("Leggi costituzionali\nDL e leggi di conversione\n\n", encoding="utf-8")

        with patch("lab_tools.fetch_normattiva.CONFIG_COLLEZIONI", col_file):
            result = _load_collezioni()
        assert result == ["Leggi costituzionali", "DL e leggi di conversione"]

    def test_missing_file_returns_empty(self, tmp_path):
        with patch("lab_tools.fetch_normattiva.CONFIG_COLLEZIONI", tmp_path / "nope.txt"):
            result = _load_collezioni()
        assert result == []


# ── _collection_subdir ──────────────────────────────────────────────


class TestCollectionSubdir:

    def test_preserves_spaces(self):
        assert _collection_subdir("Leggi costituzionali") == "Leggi costituzionali"

    def test_strips_whitespace(self):
        assert _collection_subdir("  DL e leggi  ") == "DL e leggi"


# ── _build_urn_index ───────────────────────────────────────────────


class TestBuildUrnIndex:

    def test_builds_from_corpus(self):
        """Verifica che l'indice URN venga costruito dal corpus esistente."""
        # Usa un corpus fittizio
        import tempfile, shutil

        tmp = Path(tempfile.mkdtemp())
        try:
            col = tmp / "Test"
            col.mkdir()
            md = col / "test.md"
            md.write_text(
                "---\ntipo: LEGGE\nnumero: 1\ndata: 2024-01-01\n"
                "titolo: Test\nurn: urn:nir:stato:legge:2024-01-01;1\n"
                "codice_redazionale: 024G00001\nvigente: true\n---\n\nBody.",
                encoding="utf-8",
            )
            idx = _build_urn_index(tmp)
            assert "urn:nir:stato:legge:2024-01-01;1" in idx
            assert idx["urn:nir:stato:legge:2024-01-01;1"] == "Test/test.md"
        finally:
            shutil.rmtree(tmp)

    def test_empty_corpus(self):
        import tempfile, shutil

        tmp = Path(tempfile.mkdtemp())
        try:
            idx = _build_urn_index(tmp)
            assert idx == {}
        finally:
            shutil.rmtree(tmp)


# ── _update_urn_index ──────────────────────────────────────────────


class TestUpdateUrnIndex:

    def test_adds_new_entries(self):
        import tempfile, shutil

        tmp = Path(tempfile.mkdtemp())
        try:
            md_dir = tmp / "NewCol"
            md_dir.mkdir()
            md = md_dir / "act.md"
            md.write_text(
                "---\ntipo: LEGGE\nurn: urn:nir:stato:legge:2025-01-01;1\n"
                "vigente: true\n---\n\nBody.",
                encoding="utf-8",
            )
            idx = {}
            _update_urn_index(idx, md_dir, tmp)
            assert "urn:nir:stato:legge:2025-01-01;1" in idx
        finally:
            shutil.rmtree(tmp)


# ── process_collection (integration con mock) ──────────────────────


class TestProcessCollection:

    @patch("lab_tools.fetch_normattiva.download_collection")
    def test_process_collection(self, mock_download, tmp_path):
        """Test integrato: download mock + unzip reale + parsing."""
        import zipfile
        import shutil

        # Crea uno ZIP con un XML AKN valido
        akn_xml = """<?xml version="1.0" encoding="UTF-8"?>
<act xmlns="http://docs.oasis-open.org/legaldocml/ns/akn/3.0"
     xmlns:eli="http://data.europa.eu/eli/ontology#">
  <preface>
    <docType>LEGGE</docType>
    <docNumber>1</docNumber>
    <docDate date="2024-06-01">2024-06-01</docDate>
    <docTitle>Legge di test</docTitle>
  </preface>
  <meta>
    <identification>
      <FRBRalias name="urn:nir" value="urn:nir:stato:legge:2024-06-01;1"/>
    </identification>
    <proprietary>
      <eli:id_local>024G00001</eli:id_local>
    </proprietary>
    <lifecycle></lifecycle>
  </meta>
  <body>
    <article>
      <num>Art. 1.</num>
      <p>Disposizioni generali.</p>
    </article>
  </body>
</act>"""

        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("LEGGE_20240601_1/2024-06-01_024G00001.xml", akn_xml)

        # Mock: download restituisce lo ZIP
        mock_download.return_value = zip_path

        # Setup: crea il corpus fittizio
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        collection = {"nomeCollezione": "Test Col", "formatoCollezione": "V"}
        urn_index = {}

        count = process_collection(collection, work_dir, corpus, urn_index)
        assert count == 1

        # Verifica che il .md sia stato creato
        md_files = list((corpus / "Test Col").glob("*.md"))
        assert len(md_files) == 1

        content = md_files[0].read_text(encoding="utf-8")
        assert "tipo: LEGGE" in content
        assert "Art. 1." in content

        # Verifica che l'URN index sia aggiornato
        assert "urn:nir:stato:legge:2024-06-01;1" in urn_index
