"""Test per lab_tools.mcp_server — usa monkeypatch per rg e CORPUS."""

import subprocess
from pathlib import Path

import pytest

from lab_tools import mcp_server


def _fake_rg_available(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/rg" if cmd == "rg" else None)


def _fake_corpus(tmp_path: Path, monkeypatch):
    """Crea CORPUS finto con config/collezioni.txt e una collezione valida."""
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
    monkeypatch.setattr(mcp_server, "CONFIG_COLLEZIONI", tmp_path / "config" / "collezioni.txt")
    monkeypatch.setattr(mcp_server, "CORPUS", tmp_path)


class TestListCollections:
    def test_formato(self):
        """list_collections() restituisce output formattato."""
        result = mcp_server.list_collections()
        assert result.startswith("## Collezioni")

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


class TestLegalSearch:
    def test_nessun_risultato(self, monkeypatch, tmp_path):
        """Query senza match: messaggio dedicato."""
        _fake_corpus(tmp_path, monkeypatch)
        _fake_rg_available(monkeypatch)
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **kw: subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        )
        result = mcp_server.legal_search("___inesistente___", 1)
        assert "Nessun risultato" in result

    def test_con_risultati(self, monkeypatch, tmp_path):
        """Query con match: restituisce risultati formattati."""
        _fake_corpus(tmp_path, monkeypatch)
        _fake_rg_available(monkeypatch)
        md = tmp_path / "Decreti Legislativi" / "test.md"
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **kw: subprocess.CompletedProcess(
                [], 0, stdout=str(md) + "\n", stderr=""
            ),
        )
        result = mcp_server.legal_search("direttiva", 1)
        assert "1 risult" in result  # matcha sia "1 risultato" che "1 risultati"
        assert "test.md" in result

    def test_collezione_errata(self):
        """Collezione inesistente: errore prima del check rg."""
        result = mcp_server.legal_search("test", 1, collezione="inesistente")
        assert "non trovata" in result
        assert "list_collections" in result

    def test_collezione_valida(self, monkeypatch, tmp_path):
        """Collezione valida: cerca senza errori."""
        _fake_corpus(tmp_path, monkeypatch)
        _fake_rg_available(monkeypatch)
        md = tmp_path / "Decreti Legislativi" / "test.md"
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **kw: subprocess.CompletedProcess(
                [], 0, stdout=str(md) + "\n", stderr=""
            ),
        )
        result = mcp_server.legal_search("direttiva", 1, collezione="Decreti Legislativi")
        assert "non trovata" not in result
        assert "risultati" in result
