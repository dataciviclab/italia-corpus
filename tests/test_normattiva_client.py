"""Test per lab_tools.normattiva_client."""

from unittest.mock import MagicMock, patch

import pytest
from lab_tools.normattiva_client import (
    CLASSE_ABROGATO,
    download_collection,
    extract_zip,
    fetch_act_by_urn,
    fetch_predefined_collections,
    filter_collections,
    itera_atti_per_classe,
    merge_collections_by_name,
    ricerca_avanzata,
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

    @patch("lab_tools.normattiva_client.time.sleep")
    @patch("lab_tools.normattiva_client.requests.get")
    def test_returns_none_on_http_error(self, mock_get, mock_sleep, tmp_path):
        resp = MagicMock(status_code=500)
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        resp.iter_content = MagicMock(return_value=[])
        mock_get.return_value = resp

        collection = {"nomeCollezione": "Fail", "formatoCollezione": "V"}
        result = download_collection(collection, tmp_path)
        assert result is None
        mock_sleep.assert_called()  # retry logic ran, but slept mocked


# ── fetch_act_by_urn ────────────────────────────────────────────────


class TestFetchActByUrn:

    @patch("lab_tools.normattiva_client.requests.post")
    def test_returns_atto(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {"atto": {"titolo": "Legge X"}}},
            raise_for_status=lambda: None,
        )
        assert fetch_act_by_urn("urn:nir:stato:legge:2000-01-01;1")["titolo"] == "Legge X"

    @patch("lab_tools.normattiva_client.requests.post")
    def test_falls_back_to_lista(self, mock_post):
        """Regressione: alcuni atti tornano in data.lista, non in data.atto."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": {
                    "atto": None,
                    "lista": [{"titolo": "Legge lista 1"}, {"titolo": "Legge lista 2"}],
                    "message": "ricerca effettuata con successo",
                }
            },
            raise_for_status=lambda: None,
        )
        assert fetch_act_by_urn("urn:nir:stato:legge:1999-12-16;479")["titolo"] == "Legge lista 1"

    @patch("lab_tools.normattiva_client.requests.post")
    def test_404_returns_none(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=404,
            json=lambda: {"message": "atto non trovato"},
        )
        assert fetch_act_by_urn("urn:nir:stato:legge:1942-03-24;369") is None

    @patch("lab_tools.normattiva_client.requests.post")
    def test_empty_lista_returns_none(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": {"atto": None, "lista": []}, "message": "vuoto"},
            raise_for_status=lambda: None,
        )
        assert fetch_act_by_urn("urn:nir:stato:legge:2000-01-01;1") is None


# ── ricerca_avanzata / itera_atti_per_classe ────────────────────────


class TestRicercaAvanzata:

    @patch("lab_tools.normattiva_client.requests.post")
    def test_returns_page(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "listaAtti": [{"codiceRedazionale": "051U0207"}],
                "numeroAttiTrovati": 123092,
                "numeroPagine": 124,
            },
            raise_for_status=lambda: None,
        )
        res = ricerca_avanzata(CLASSE_ABROGATO, page=1, page_size=1000)
        assert res["numero_atti"] == 123092
        assert res["numero_pagine"] == 124
        assert res["atti"][0]["codiceRedazionale"] == "051U0207"

    @patch("lab_tools.normattiva_client.requests.post")
    def test_payload_top_level(self, mock_post):
        """classeProvvedimento e paginazione sono campi top-level."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"listaAtti": [], "numeroAttiTrovati": 0, "numeroPagine": 0},
            raise_for_status=lambda: None,
        )
        ricerca_avanzata("3", page=2, page_size=500)
        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["classeProvvedimento"] == "3"
        assert payload["paginazione"] == {
            "paginaCorrente": 2, "numeroElementiPerPagina": 500,
        }

    @patch("lab_tools.normattiva_client.requests.post")
    def test_message_returns_none(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"message": "La pagina richiesta è stata bloccata"},
            raise_for_status=lambda: None,
        )
        assert ricerca_avanzata("3") is None

    @patch("lab_tools.normattiva_client.time.sleep")
    @patch("lab_tools.normattiva_client.requests.post")
    def test_retry_su_403(self, mock_post, mock_sleep):
        """WAF: 403 → retry (con backoff), poi successo."""
        blocked = MagicMock(status_code=403, json=lambda: {"message": "bloccato"})
        ok = MagicMock(
            status_code=200,
            json=lambda: {"listaAtti": [], "numeroAttiTrovati": 0, "numeroPagine": 0},
            raise_for_status=lambda: None,
        )
        mock_post.side_effect = [blocked, ok]
        res = ricerca_avanzata("3")
        assert res is not None
        assert mock_post.call_count == 2
        mock_sleep.assert_called()


class TestIteraAttiPerClasse:

    @patch("lab_tools.normattiva_client.time.sleep")
    @patch("lab_tools.normattiva_client.ricerca_avanzata")
    def test_pagina_e_rispetta_pace(self, mock_ric, mock_sleep):
        mock_ric.side_effect = [
            {"atti": [{"codiceRedazionale": "A"}], "numero_atti": 2, "numero_pagine": 2},
            {"atti": [{"codiceRedazionale": "B"}], "numero_atti": 2, "numero_pagine": 2},
        ]
        out = list(itera_atti_per_classe("3"))
        assert [a["codiceRedazionale"] for a in out] == ["A", "B"]
        assert mock_ric.call_count == 2
        mock_sleep.assert_called_once()  # pacing solo tra le pagine

    @patch("lab_tools.normattiva_client.ricerca_avanzata")
    def test_stop_su_errore(self, mock_ric):
        mock_ric.return_value = None
        assert list(itera_atti_per_classe("3")) == []

