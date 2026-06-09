"""Test per lab_tools.mcp_server — verifica base senza dipendere da rg."""

from pathlib import Path

import pytest

from lab_tools.mcp_server import list_collections, legal_search

CORPUS = Path(__file__).resolve().parent.parent


def test_list_collections_formato():
    """list_collections() restituisce output formattato correttamente."""
    result = list_collections()
    assert result.startswith("## Collezioni")
    # Almeno una riga per collezione (in locale) o solo header (in CI)
    assert result.count("\n") >= 1


def test_legal_search_nessun_risultato():
    """Query senza match: messaggio dedicato."""
    result = legal_search("___query_che_non_matcha_mai_12345___", 1)
    assert "Nessun risultato" in result


def test_legal_search_collezione_errata():
    """Collezione inesistente: messaggio di errore."""
    result = legal_search("test", 1, collezione="inesistente")
    assert "non trovata" in result
    assert "list_collections" in result


def test_legal_search_con_collezione():
    """Collezione esistente: non deve dare errore."""
    collezioni_reali = [
        d.name for d in CORPUS.iterdir()
        if d.is_dir() and not d.name.startswith(".")
        and d.name not in (".git", "data", "lab_tools", "tests", "notebooks")
    ]
    if not collezioni_reali:
        pytest.skip("Nessuna collezione reale nel working tree (sparse checkout)")
    result = legal_search("direttiva", 1, collezione=collezioni_reali[0])
    assert "non trovata" not in result
