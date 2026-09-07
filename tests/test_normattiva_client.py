"""Test per lab_tools.normattiva_client."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lab_tools.normattiva_client import (
    download_collection,
    extract_zip,
    fetch_predefined_collections,
    filter_collections,
    merge_collections_by_name,
)


# ── fetch_predefined_collections ────────────────────────────────────


class TestFetchPredefinedCollections:

    @patch("lab_tools.normattiva_client.requests.get")
    def test_returns_list(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{"nomeCollezione": "A", "formatoCollezione": "V"}],
            raise_for_status=lambda: None,
        )
        result = fetch_predefined_collections()
        assert result == [{"nomeCollezione": "A", "formatoCollezione": "V"}]

    @patch("lab_tools.normattiva_client.requests.get")
    def test_raises_on_non_list(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"error": "bad"},
            raise_for_status=lambda: None,
        )
        with pytest.raises(TypeError):
            fetch_predefined_collections()


# ── merge_collections_by_name ───────────────────────────────────────


class TestMergeCollectionsByName:

    def test_priority_v_over_o(self):
        rows = [
            {"nomeCollezione": "A", "formatoCollezione": "O"},
            {"nomeCollezione": "A", "formatoCollezione": "V"},
        ]
        result = merge_collections_by_name(rows)
        assert len(result) == 1
        assert result[0]["formatoCollezione"] == "V"

    def test_priority_o_over_m(self):
        rows = [
            {"nomeCollezione": "B", "formatoCollezione": "M"},
            {"nomeCollezione": "B", "formatoCollezione": "O"},
        ]
        result = merge_collections_by_name(rows)
        assert len(result) == 1
        assert result[0]["formatoCollezione"] == "O"

    def test_preserves_order(self):
        rows = [
            {"nomeCollezione": "B", "formatoCollezione": "V"},
            {"nomeCollezione": "A", "formatoCollezione": "V"},
        ]
        result = merge_collections_by_name(rows)
        assert [r["nomeCollezione"] for r in result] == ["B", "A"]

    def test_skips_empty_name(self):
        rows = [
            {"nomeCollezione": "", "formatoCollezione": "V"},
            {"nomeCollezione": "A", "formatoCollezione": "V"},
        ]
        result = merge_collections_by_name(rows)
        assert len(result) == 1

    def test_single_collection(self):
        rows = [{"nomeCollezione": "X", "formatoCollezione": "V"}]
        result = merge_collections_by_name(rows)
        assert len(result) == 1
        assert result[0]["nomeCollezione"] == "X"


# ── filter_collections ──────────────────────────────────────────────


class TestFilterCollections:

    def _c(self, name: str, fmt: str) -> dict:
        return {"nomeCollezione": name, "formatoCollezione": fmt}

    def test_only_vigenti(self):
        cols = [self._c("A", "V"), self._c("B", "O"), self._c("C", "V")]
        result = filter_collections(cols)
        assert [r["nomeCollezione"] for r in result] == ["A", "C"]

    def test_filter_by_names(self):
        cols = [self._c("A", "V"), self._c("B", "V"), self._c("C", "V")]
        result = filter_collections(cols, only_names=["A", "C"])
        assert [r["nomeCollezione"] for r in result] == ["A", "C"]

    def test_filter_by_names_nonexistent(self):
        cols = [self._c("A", "V")]
        result = filter_collections(cols, only_names=["Z"])
        assert result == []


# ── extract_zip ─────────────────────────────────────────────────────


class TestExtractZip:

    def test_extracts_xml(self, tmp_path):
        import zipfile

        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("dir/file1.xml", "<root/>")
            zf.writestr("dir/file2.xml", "<root/>")
            zf.writestr("dir/readme.txt", "skip")

        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        xml_files = extract_zip(zip_path, extract_dir)
        assert len(xml_files) == 2
        assert all(f.suffix == ".xml" for f in xml_files)


# ── download_collection ─────────────────────────────────────────────


class TestDownloadCollection:

    @patch("lab_tools.normattiva_client.requests.get")
    def test_success(self, mock_get, tmp_path):
        import zipfile

        zip_path = tmp_path / "dummy.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("test.xml", "<root/>")
        zip_bytes = zip_path.read_bytes()

        resp = MagicMock(status_code=200)
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        resp.iter_content = MagicMock(return_value=[zip_bytes])
        mock_get.return_value = resp

        collection = {"nomeCollezione": "Test", "formatoCollezione": "V"}
        result = download_collection(collection, tmp_path)
        assert result is not None
        assert result.exists()

    @patch("lab_tools.normattiva_client.requests.get")
    def test_returns_none_on_http_error(self, mock_get, tmp_path):
        resp = MagicMock(status_code=500)
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        resp.iter_content = MagicMock(return_value=[])
        mock_get.return_value = resp

        collection = {"nomeCollezione": "Fail", "formatoCollezione": "V"}
        result = download_collection(collection, tmp_path)
        assert result is None
