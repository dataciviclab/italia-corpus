"""Test per lab_tools.mcp_server — monkeypatch per rg, CORPUS e output JSON."""

import json
import subprocess
from pathlib import Path

import pytest

from lab_tools import mcp_server


# ─── fixture helpers ──────────────────────────────────────────────


def _fake_rg_available(monkeypatch):
    """Mocka shutil.which("rg") per ambienti senza rg (es. CI)."""
    monkeypatch.setattr(
        "shutil.which", lambda cmd: "/usr/bin/rg" if cmd == "rg" else None,
    )


def _fake_corpus(tmp_path: Path, monkeypatch):
    """Crea CORPUS finto con config/collezioni.txt, collezione e file .md."""
    _fake_rg_available(monkeypatch)
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


def _mock_rg_json_result(monkeypatch, files: list[Path], query: str = "test"):
    """Mocka rg per ricerca a due fasi con AND multi-termine.

    Chiamate attese:
      1. rg --version (da _rg_disponibile — non più, ora solo shutil.which)
      2. rg -l (FASE 1: una o più chiamate, una per termine)
      3. rg --json (FASE 2: snippet)
    """
    # _rg_disponibile ora usa solo shutil.which, non chiama rg --version.
    # Mock chiamata generica.
    call_count: list[int] = [0]

    def fake_run(args, **kw):
        call_count[0] += 1
        args_str = " ".join(str(a) for a in args) if args else ""

        # Fase 1: rg -l (lista file) — restituisce path dei file
        if "-l" in args_str and "--json" not in args_str:
            stdout = "\n".join(str(fp) for fp in files)
            return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

        # Fase 2: rg --json (snippet)
        if "--json" in args_str:
            lines = []
            for fp in files:
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


def _mock_rg_list_files(monkeypatch, files_by_term: dict[str, list[Path]]):
    """Mocka rg -l per AND multi-termine: ogni termine ha una lista file diversa.

    files_by_term: {termine: [lista file che lo contengono]}
    Usato per testare che l'intersezione funzioni correttamente.
    """
    _fake_rg_available(monkeypatch)

    def fake_run(args, **kw):
        args_str = " ".join(str(a) for a in args) if args else ""
        # -l ma non --json = fase lista
        if "-l" in args_str and "--json" not in args_str:
            # Trova quale termine è stato passato (dopo --)
            for term, term_files in files_by_term.items():
                if term in args_str:
                    stdout = "\n".join(str(fp) for fp in term_files)
                    return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        # --json = fase snippet (usa primo termine come fallback)
        if "--json" in args_str:
            first_term = next(iter(files_by_term.keys()), "test")
            first_files = files_by_term.get(first_term, [])
            lines = []
            for fp in first_files:
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
                        "lines": {"text": f"riga con {first_term}\n"},
                        "line_number": 1,
                        "submatches": [{"match": {"text": first_term}, "start": 0, "end": len(first_term)}],
                    },
                }))
                lines.append(json.dumps({"type": "end", "data": {"path": {"text": fp_str}}}))
            lines.append(json.dumps({"type": "summary", "data": {}}))
            return subprocess.CompletedProcess(args, 0, stdout="\n".join(lines), stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)


# ─── Test _parse_query ────────────────────────────────────────────


class TestParseQuery:
    @pytest.mark.pure_unit
    def test_singola_parola(self):
        """Singola parola → un termine, non frase."""
        terms, is_phrase = mcp_server._parse_query("ambiente")
        assert terms == ["ambiente"]
        assert is_phrase is False

    @pytest.mark.pure_unit
    def test_and_multi_termine(self):
        """Multi-parola → lista termini, non frase."""
        terms, is_phrase = mcp_server._parse_query("ambiente energia")
        assert terms == ["ambiente", "energia"]
        assert is_phrase is False

    @pytest.mark.pure_unit
    def test_frase_esatta_virgolette(self):
        """Query tra virgolette → frase esatta, termini singolo."""
        terms, is_phrase = mcp_server._parse_query('"decreto legislativo"')
        assert terms == ["decreto legislativo"]
        assert is_phrase is True

    @pytest.mark.pure_unit
    def test_query_vuota(self):
        """Query vuota → lista vuota."""
        terms, is_phrase = mcp_server._parse_query("")
        assert terms == []
        assert is_phrase is False

    @pytest.mark.pure_unit
    def test_trim_spazi(self):
        """Spazi iniziali/finali vengono trimmati."""
        terms, is_phrase = mcp_server._parse_query("  comune  ")
        assert terms == ["comune"]


# ─── Test _search_corpus (singolo termine / frase) ───────────────


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
        # Query singola parola
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

    @pytest.mark.contract
    def test_and_multi_termine_intersezione(self, monkeypatch, tmp_path):
        """AND multi-termine: solo file che hanno TUTTI i termini."""
        _fake_corpus(tmp_path, monkeypatch)
        # file1 ha "ambiente", file2 ha "energia", nessuno ha entrambi
        file1 = tmp_path / "Decreti Legislativi" / "test.md"
        file2 = tmp_path / "Decreti Legislativi" / "altro.md"
        _mock_rg_list_files(monkeypatch, {
            "ambiente": [file1],
            "energia": [file2],
        })
        # Nessun file ha entrambi → 0 risultati
        results = mcp_server._search_corpus("ambiente energia", limit=10)
        assert results == []

    @pytest.mark.contract
    def test_and_multi_termine_con_intersezione(self, monkeypatch, tmp_path):
        """AND: file che ha entrambi i termini viene trovato."""
        _fake_corpus(tmp_path, monkeypatch)
        file1 = tmp_path / "Decreti Legislativi" / "test.md"
        file2 = tmp_path / "Decreti Legislativi" / "altro.md"
        # file1 ha entrambi, file2 solo "ambiente"
        _mock_rg_list_files(monkeypatch, {
            "ambiente": [file1, file2],
            "energia": [file1],
        })
        results = mcp_server._search_corpus("ambiente energia", limit=10)
        assert len(results) == 1
        assert results[0]["filename"] == "test.md"

    @pytest.mark.pure_unit
    def test_limit_max(self):
        """limit è capped a _MAX_LIMIT (100)."""
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

    @pytest.mark.contract
    def test_nessun_risultato_lista_vuota(self, monkeypatch, tmp_path):
        """Nessun match → lista vuota, non messaggio stringa."""
        _fake_corpus(tmp_path, monkeypatch)
        _mock_rg_json_result(monkeypatch, [])
        result = mcp_server.legal_search("xxx_inesistente_xxx")
        assert result == []

    @pytest.mark.contract
    def test_ricerca_and_via_tool(self, monkeypatch, tmp_path):
        """AND multi-termine funziona anche via legal_search."""
        _fake_corpus(tmp_path, monkeypatch)
        file1 = tmp_path / "Decreti Legislativi" / "test.md"
        file2 = tmp_path / "Decreti Legislativi" / "altro.md"
        _mock_rg_list_files(monkeypatch, {
            "ambiente": [file1, file2],
            "energia": [file1],
        })
        result = mcp_server.legal_search("ambiente energia", limit=10)
        assert len(result) == 1
        assert result[0]["filename"] == "test.md"


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

    @pytest.mark.contract
    def test_path_traversal_basename(self, monkeypatch, tmp_path):
        """Path traversal con / nel filename → ValueError."""
        _fake_corpus(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="filename non valido"):
            mcp_server.legal_get_document(
                "Decreti Legislativi", "../config/collezioni.txt"
            )

    @pytest.mark.contract
    def test_path_traversal_non_md(self, monkeypatch, tmp_path):
        """File senza .md → ValueError."""
        _fake_corpus(tmp_path, monkeypatch)
        with pytest.raises(ValueError, match="deve terminare con .md"):
            mcp_server.legal_get_document(
                "Decreti Legislativi", "collezioni.txt"
            )

    @pytest.mark.contract
    def test_path_traversal_symlink_prefix_bypass(self, monkeypatch, tmp_path):
        """Symlink con nome che inizia come la collezione (Col_evil bypassa startswith)."""
        _fake_corpus(tmp_path, monkeypatch)
        col = tmp_path / "Decreti Legislativi"
        # File fuori dalla collezione con nome che inizia con "Decreti Legislativi"
        evil = tmp_path / "Decreti Legislativi_evil.md"
        evil.write_text("SECRET", encoding="utf-8")
        link = col / "link.md"
        try:
            link.symlink_to(evil)
        except OSError:
            pytest.skip("symlink non supportato su questo filesystem")
        with pytest.raises(ValueError, match="Accesso negato"):
            mcp_server.legal_get_document("Decreti Legislativi", "link.md")


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
