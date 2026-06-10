"""Test per lab_tools.mcp_server — monkeypatch per rg, CORPUS e output JSON."""

import json
import subprocess
from pathlib import Path

import pytest

from lab_tools import mcp_server


# ─── fixture helpers ──────────────────────────────────────────────


def _fake_corpus(tmp_path: Path, monkeypatch):
    """Crea CORPUS finto con config/collezioni.txt, collezione e file .md."""
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "collezioni.txt").write_text(
        "Decreti Legislativi\n", encoding="utf-8"
    )
    col = tmp_path / "Decreti Legislativi"
    col.mkdir(parents=True)
    (col / "test.md").write_text(
        "DECRETO LEGISLATIVO 15 marzo 2020 n. 45\nAttuazione direttiva CELEX:32018L1234",
        encoding="utf-8",
    )
    (col / "altro.md").write_text(
        "LEGGE 10 gennaio 2021 n. 1\nDisposizioni in materia ambientale",
        encoding="utf-8",
    )
    monkeypatch.setattr(mcp_server, "CONFIG_COLLEZIONI", tmp_path / "config" / "collezioni.txt")
    monkeypatch.setattr(mcp_server, "CORPUS", tmp_path)


def _mock_rg_version_ok(monkeypatch):
    """Mocka rg --version come disponibile con PCRE2."""

    def fake_run(args, **kw):
        if args and args[0] == "rg" and "--version" in args:
            return subprocess.CompletedProcess(
                args, 0,
                stdout="ripgrep 14.1.0\nfeatures:+pcre2\n",
                stderr="",
            )
        # Ricerca: restituisci JSON vuoto (nessun match)
        return subprocess.CompletedProcess(
            args, 0, stdout="", stderr="",
        )

    monkeypatch.setattr("subprocess.run", fake_run)


def _mock_rg_json_result(monkeypatch, files: list[Path], query: str = "test"):
    """Mocka rg per ricerca a due fasi (rg -l poi rg --json).

    La prima chiamata (rg -l) restituisce lista file.
    La seconda chiamata (rg --json) restituisce eventi JSON per ogni file.
    Gestisce anche rg --version (chiamata iniziale di _rg_disponibile).
    """
    call_count: list[int] = [0]

    def fake_run(args, **kw):
        call_count[0] += 1
        args_str = " ".join(str(a) for a in args) if args else ""

        # Version check (prima o durante)
        if "--version" in args_str:
            return subprocess.CompletedProcess(
                args, 0,
                stdout="ripgrep 14.1.0\nfeatures:+pcre2\n",
                stderr="",
            )

        # Fase 1: rg -l (lista file)
        if "-l" in args_str and "--json" not in args_str:
            stdout = "\n".join(str(fp) for fp in files)
            return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

        # Fase 2: rg --json (snippet)
        if "--json" in args_str:
            lines = []
            for fp in files:
                # Solo i file che sono tra gli argomenti dopo "--"
                fp_str = str(fp)
                if fp_str not in args_str:
                    continue
                lines.append(json.dumps({
                    "type": "begin",
                    "data": {"path": {"text": fp_str}},
                }))
                lines.append(json.dumps({
                    "type": "match",
                    "data": {
                        "path": {"text": fp_str},
                        "lines": {"text": f"riga con {query}\n"},
                        "line_number": 1,
                        "submatches": [{"match": {"text": query}, "start": 0, "end": len(query)}],
                    },
                }))
                lines.append(json.dumps({
                    "type": "end",
                    "data": {"path": {"text": fp_str}},
                }))
            lines.append(json.dumps({
                "type": "summary",
                "data": {"elapsed_total": {"secs": 0, "nanos": 1000}},
            }))
            return subprocess.CompletedProcess(args, 0, stdout="\n".join(lines), stderr="")

        # Fallback: output vuoto
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)


# ─── Test _build_pattern ─────────────────────────────────────────


class TestBuildPattern:
    @pytest.mark.pure_unit
    def test_singola_parola(self):
        """Singola parola → letterale escaped."""
        pat, pcre2 = mcp_server._build_pattern("ambiente")
        assert pat == "ambiente"
        assert pcre2 is False

    @pytest.mark.pure_unit
    def test_and_multi_termine(self):
        """Multi-parola → pattern lookahead AND."""
        pat, pcre2 = mcp_server._build_pattern("ambiente energia")
        assert pcre2 is True
        assert "(?=.*\\bambiente\\b)" in pat
        assert "(?=.*\\benergia\\b)" in pat

    @pytest.mark.pure_unit
    def test_frase_esatta_virgolette(self):
        """Query tra virgolette → letterale (frase esatta, senza lookahead)."""
        pat, pcre2 = mcp_server._build_pattern('"decreto legislativo"')
        assert pat == "decreto legislativo"
        assert pcre2 is False

    @pytest.mark.pure_unit
    def test_query_vuota(self):
        """Query vuota → pattern vuoto."""
        pat, _ = mcp_server._build_pattern("")
        assert pat == ""

    @pytest.mark.pure_unit
    def test_parole_corte(self):
        """Parole < 3 caratteri: senza word boundary."""
        pat, pcre2 = mcp_server._build_pattern("ex art")
        assert pcre2 is True
        assert "\\bex\\b" not in pat  # no word boundary per 'ex' (2 char)
        assert "\\bart\\b" in pat  # word boundary per 'art' (3 char)


# ─── Test _search_corpus ─────────────────────────────────────────


class TestSearchCorpus:
    @pytest.mark.contract
    def test_struttura_output(self, monkeypatch, tmp_path):
        """Risultati con chiavi attese."""
        _fake_corpus(tmp_path, monkeypatch)
        _mock_rg_json_result(
            monkeypatch,
            [tmp_path / "Decreti Legislativi" / "test.md"],
        )
        results = mcp_server._search_corpus("direttiva", limit=10)
        assert len(results) == 1
        r = results[0]
        for key in ("title", "collection", "filename", "path", "snippet", "match_count"):
            assert key in r, f"chiave mancante: {key}"
        assert r["collection"] == "Decreti Legislativi"
        assert r["filename"] == "test.md"
        assert isinstance(r["match_count"], int)

    @pytest.mark.contract
    def test_paginazione_offset(self, monkeypatch, tmp_path):
        """Offset funziona: salta i primi N risultati."""
        _fake_corpus(tmp_path, monkeypatch)
        files = [
            tmp_path / "Decreti Legislativi" / "test.md",
            tmp_path / "Decreti Legislativi" / "altro.md",
        ]
        _mock_rg_json_result(monkeypatch, files)
        results_0 = mcp_server._search_corpus("direttiva", limit=10, offset=0)
        results_1 = mcp_server._search_corpus("direttiva", limit=10, offset=1)
        assert len(results_0) == 2
        assert len(results_1) == 1
        assert results_0[0]["filename"] != results_1[0]["filename"]

    @pytest.mark.contract
    def test_collezione_valida(self, monkeypatch, tmp_path):
        """Filtra per collezione: cerca solo in quella."""
        _fake_corpus(tmp_path, monkeypatch)
        _mock_rg_json_result(
            monkeypatch,
            [tmp_path / "Decreti Legislativi" / "test.md"],
        )
        results = mcp_server._search_corpus(
            "direttiva", limit=10, collezione="Decreti Legislativi"
        )
        assert len(results) == 1

    @pytest.mark.contract
    def test_collezione_errata(self, monkeypatch, tmp_path):
        """Collezione inesistente → ValueError."""
        _fake_corpus(tmp_path, monkeypatch)
        _mock_rg_json_result(monkeypatch, [])
        with pytest.raises(ValueError, match="non trovata"):
            mcp_server._search_corpus(
                "test", limit=10, collezione="inesistente"
            )

    @pytest.mark.contract
    def test_nessun_risultato(self, monkeypatch, tmp_path):
        """Query senza match → lista vuota."""
        _fake_corpus(tmp_path, monkeypatch)
        _mock_rg_json_result(monkeypatch, [])
        results = mcp_server._search_corpus("___inesistente___")
        assert results == []

    @pytest.mark.pure_unit
    def test_limit_max(self):
        """limit è capped a _MAX_LIMIT (100)."""
        # Test indiretto: _search_corpus passa min(limit, _MAX_LIMIT)
        assert mcp_server._MAX_LIMIT == 100


# ─── Test legal_search (tool MCP) ────────────────────────────────


class TestLegalSearchTool:
    @pytest.mark.contract
    def test_output_strutturato(self, monkeypatch, tmp_path):
        """legal_search restituisce list[dict]."""
        _fake_corpus(tmp_path, monkeypatch)
        _mock_rg_json_result(
            monkeypatch,
            [tmp_path / "Decreti Legislativi" / "test.md"],
        )
        result = mcp_server.legal_search("direttiva", limit=10)
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], dict)

    @pytest.mark.contract
    def test_limit_default(self, monkeypatch, tmp_path):
        """Default limit=10."""
        _fake_corpus(tmp_path, monkeypatch)
        _mock_rg_json_result(monkeypatch, [])
        result = mcp_server.legal_search("test")
        assert isinstance(result, list)

    @pytest.mark.contract
    def test_collezione_errata_raise(self, monkeypatch, tmp_path):
        """Collezione inesistente → RuntimeError."""
        _fake_corpus(tmp_path, monkeypatch)
        _mock_rg_json_result(monkeypatch, [])
        with pytest.raises(RuntimeError, match="non trovata"):
            mcp_server.legal_search("test", collezione="inesistente")

    @pytest.mark.contract
    def test_con_offset(self, monkeypatch, tmp_path):
        """Parametro offset passato a _search_corpus."""
        _fake_corpus(tmp_path, monkeypatch)
        files = [
            tmp_path / "Decreti Legislativi" / "test.md",
            tmp_path / "Decreti Legislativi" / "altro.md",
        ]
        _mock_rg_json_result(monkeypatch, files)
        r0 = mcp_server.legal_search("direttiva", limit=10, offset=0)
        r1 = mcp_server.legal_search("direttiva", limit=10, offset=1)
        assert len(r0) == 2
        assert len(r1) == 1

    @pytest.mark.pure_unit
    def test_nessun_risultato_lista_vuota(self, monkeypatch, tmp_path):
        """Nessun match → lista vuota, non messaggio stringa."""
        _fake_corpus(tmp_path, monkeypatch)
        _mock_rg_json_result(monkeypatch, [])
        result = mcp_server.legal_search("xxx_inesistente_xxx")
        assert result == []


# ─── Test legal_get_document ─────────────────────────────────────


class TestLegalGetDocument:
    @pytest.mark.contract
    def test_documento_trovato(self, monkeypatch, tmp_path):
        """Restituisce contenuto del file."""
        _fake_corpus(tmp_path, monkeypatch)
        content = mcp_server.legal_get_document(
            "Decreti Legislativi", "test.md", max_chars=500
        )
        assert "DECRETO LEGISLATIVO" in content
        assert "CELEX" in content

    @pytest.mark.contract
    def test_collezione_errata(self, monkeypatch, tmp_path):
        """Collezione inesistente → ValueError."""
        _fake_corpus(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="non trovata"):
            mcp_server.legal_get_document("Inesistente", "test.md")

    @pytest.mark.contract
    def test_file_inesistente(self, monkeypatch, tmp_path):
        """File inesistente → ValueError."""
        _fake_corpus(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="non trovato"):
            mcp_server.legal_get_document("Decreti Legislativi", "mancante.md")

    @pytest.mark.contract
    def test_troncamento(self, monkeypatch, tmp_path):
        """max_chars tronca il contenuto."""
        _fake_corpus(tmp_path, monkeypatch)
        content = mcp_server.legal_get_document(
            "Decreti Legislativi", "test.md", max_chars=20
        )
        assert len(content) < 100
        assert "troncato" in content


# ─── Test list_collections (invariato) ────────────────────────────


class TestListCollections:
    @pytest.mark.contract
    def test_formato(self):
        """list_collections() restituisce output formattato."""
        result = mcp_server.list_collections()
        assert result.startswith("## Collezioni")

    @pytest.mark.contract
    def test_con_skip(self, monkeypatch, tmp_path):
        """Solo le collezioni in config appaiono nell'output."""
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "collezioni.txt").write_text(
            "Decreti Legislativi\nDL e leggi di conversione\n", encoding="utf-8"
        )
        for d in ("Decreti Legislativi", "DL e leggi di conversione", ".git", "data"):
            (tmp_path / d).mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(mcp_server, "CONFIG_COLLEZIONI", tmp_path / "config" / "collezioni.txt")
        monkeypatch.setattr(mcp_server, "CORPUS", tmp_path)
        result = mcp_server.list_collections()
        assert "Decreti Legislativi" in result
        assert "DL e leggi di conversione" in result
        assert ".git" not in result
        assert "data" not in result
