"""Test per lab_tools.mcp_server — verifica base senza dipendere da rg."""

from pathlib import Path

from lab_tools.mcp_server import list_collections, legal_search

# Path assoluto del corpus (per capire se siamo in CI o locale)
CORPUS = Path(__file__).resolve().parent.parent


def test_list_collections_non_vuota():
    """list_collections() restituisce almeno una collezione."""
    result = list_collections()
    assert "## Collezioni" in result
    assert len(result) > 50


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
    """Collezione esistente: non deve dare errore (anche se nessun risultato)."""
    # Usa una collezione che esiste nel corpus (se presente) o fallisce gentilmente
    collezioni_reali = [d.name for d in CORPUS.iterdir()
                        if d.is_dir() and not d.name.startswith(".")
                        and d.name not in (".git", "data", "lab_tools", "tests", "notebooks")]
    if not collezioni_reali:
        # In CI (sparse checkout) non ci sono collezioni — skip
        return
    result = legal_search("direttiva", 1, collezione=collezioni_reali[0])
    assert "non trovata" not in result
