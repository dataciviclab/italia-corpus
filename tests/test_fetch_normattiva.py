"""Test per lab_tools.fetch_normattiva."""

from pathlib import Path
from unittest.mock import patch

from lab_tools.fetch_normattiva import (
    _build_urn_index,
    _collection_subdir,
    _file_da_sostituire,
    _load_collezioni,
    _read_xml,
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
        import shutil
        import tempfile

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
        import shutil
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        try:
            idx = _build_urn_index(tmp)
            assert idx == {}
        finally:
            shutil.rmtree(tmp)


# ── _update_urn_index ──────────────────────────────────────────────


class TestUpdateUrnIndex:

    def test_adds_new_entries(self):
        import shutil
        import tempfile

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


def _make_corpus_with_md(tmp_path: Path, collection_name: str) -> Path:
    """Crea un corpus fittizio con un .md preesistente."""
    corpus = tmp_path / "corpus"
    col_dir = corpus / collection_name
    col_dir.mkdir(parents=True, exist_ok=True)
    existing = col_dir / "existing.md"
    existing.write_text(
        "---\ntipo: LEGGE\nnumero: 999\ndata: 2020-01-01\n"
        "titolo: Esistente\nurn: urn:nir:stato:legge:2020-01-01;999\n"
        "codice_redazionale: 020G00999\nvigente: true\n---\n\nContenuto esistente.",
        encoding="utf-8",
    )
    return corpus


class TestProcessCollection:

    @patch("lab_tools.fetch_normattiva.download_collection")
    def test_process_collection(self, mock_download, tmp_path):
        """Test integrato: download mock + unzip reale + parsing."""
        import zipfile

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

    @patch("lab_tools.fetch_normattiva.download_collection")
    def test_download_none_preserves_existing_md(self, mock_download, tmp_path):
        """Se download fallisce, i .md esistenti devono restare intatti."""
        mock_download.return_value = None
        corpus = _make_corpus_with_md(tmp_path, "Test Col")
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        collection = {"nomeCollezione": "Test Col", "formatoCollezione": "V"}
        urn_index = {}

        count = process_collection(collection, work_dir, corpus, urn_index)
        assert count == 0

        # I .md esistenti devono essere ancora lì
        md_files = list((corpus / "Test Col").glob("*.md"))
        assert len(md_files) == 1
        assert md_files[0].name == "existing.md"
        assert "Contenuto esistente." in md_files[0].read_text(encoding="utf-8")

    @patch("lab_tools.fetch_normattiva.download_collection")
    def test_empty_zip_preserves_existing_md(self, mock_download, tmp_path):
        """Se lo ZIP non contiene XML, i .md esistenti devono restare intatti."""
        import zipfile

        # ZIP valido ma vuoto (nessun XML)
        zip_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("readme.txt", "no xml here")

        mock_download.return_value = zip_path
        corpus = _make_corpus_with_md(tmp_path, "Test Col")
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        collection = {"nomeCollezione": "Test Col", "formatoCollezione": "V"}
        urn_index = {}

        count = process_collection(collection, work_dir, corpus, urn_index)
        assert count == 0

        # I .md esistenti devono essere ancora lì
        md_files = list((corpus / "Test Col").glob("*.md"))
        assert len(md_files) == 1
        assert md_files[0].name == "existing.md"


class TestReadXml:
    def test_xml_plain(self, tmp_path):
        xml = '<?xml version="1.0"?><akn/>'
        p = tmp_path / "a.xml"
        p.write_text(xml, encoding="utf-8")
        assert _read_xml(p) == xml

    def test_xml_base64(self, tmp_path):
        """Alcuni atti grossi arrivano base64 dentro lo ZIP (Codice civile)."""
        import base64

        xml = '<?xml version="1.0"?><akn>x</akn>'
        p = tmp_path / "a.xml"
        p.write_bytes(base64.b64encode(xml.encode("utf-8")))
        assert _read_xml(p) == xml

    def test_xml_con_bom_resta_plain(self, tmp_path):
        p = tmp_path / "a.xml"
        p.write_bytes(b'\xef\xbb\xbf<akn/>')
        assert _read_xml(p) == '\ufeff<akn/>'


class TestFileDaSostituire:
    """Swap per atto: si cancellano solo i file presenti nella nuova sorgente."""

    def test_stesso_atto_rename(self):
        vecchi = ["1942-04-04_042U0262_ORIGINALE_V0.md"]
        nuovi = ["1942-04-04_042U0262_VIGENZA_2026-04-29_V0.md"]
        assert _file_da_sostituire(vecchi, nuovi) == set(vecchi)

    def test_atto_assente_non_si_cancella(self):
        """Conversione fallita: il vecchio file deve restare."""
        vecchi = ["1942-04-04_042U0262_ORIGINALE_V0.md", "2003-08-07_003G0227_ORIGINALE_V0.md"]
        nuovi = ["2003-08-07_003G0227_VIGENZA_2026-02-25_V0.md"]
        assert _file_da_sostituire(vecchi, nuovi) == {"2003-08-07_003G0227_ORIGINALE_V0.md"}

    def test_nuova_sorgente_senza_atti_noti(self):
        vecchi = ["1942-04-04_042U0262_ORIGINALE_V0.md"]
        assert _file_da_sostituire(vecchi, []) == set()

    def test_snapshot_aggiornato(self):
        vecchi = ["2003-08-07_003G0227_VIGENZA_2025-06-12_V0.md"]
        nuovi = ["2003-08-07_003G0227_VIGENZA_2026-02-25_V0.md"]
        assert _file_da_sostituire(vecchi, nuovi) == set(vecchi)


class TestProcessCollectionNonCancella:
    """Un XML base64 troncato non deve cancellare il testo buono."""

    def test_base64_troncato_mantiene_il_vecchio(self, tmp_path):
        from unittest.mock import patch

        xml = tmp_path / "1942-04-04_042U0262_VIGENZA_2026-04-29_V0.xml"
        xml.write_text("PD94bWwgdmVyc2lvbj0iMS4w", encoding="utf-8")  # troncato

        dest = tmp_path / "collezioni" / "Codici"
        dest.mkdir(parents=True)
        vecchio = dest / "1942-04-04_042U0262_ORIGINALE_V0.md"
        vecchio.write_text("testo buono", encoding="utf-8")

        with (
            patch("lab_tools.fetch_normattiva.download_collection", return_value=tmp_path / "z.zip"),
            patch("lab_tools.fetch_normattiva.extract_zip", return_value=[xml]),
        ):
            count = process_collection(
                {"nomeCollezione": "Codici"}, tmp_path, tmp_path / "collezioni", {}
            )

        assert count == 0
        assert vecchio.exists()
        assert vecchio.read_text(encoding="utf-8") == "testo buono"
