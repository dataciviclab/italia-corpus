"""Test per lab_tools.classifica_riferimenti — clausole di lettura."""

from __future__ import annotations

import pytest
from lab_tools.classifica_riferimenti import clausola_di_lettura

# contesto reale (DPR 1092/1985): il link serve a "far leggere", non a citare
REALE = (
    "art. 10, commi 2 e 3, del testo unico approvato con [decreto del "
    "Presidente della Repubblica 28 dicembre 1985, n. 1092](../Testi%20Unici/"
    "1986-05-29_085U1092_VIGENZA_2025-06-17_V0.md), al solo fine di facilitare "
    "la lettura delle disposizioni di cui al presente articolo"
)


class TestClausolaDiLettura:
    @pytest.mark.policy
    def test_clausola_reale(self):
        assert clausola_di_lettura(REALE) is True

    @pytest.mark.pure_unit
    @pytest.mark.parametrize(
        "testo",
        [
            "al solo fine di facilitare la lettura delle disposizioni",
            "AL SOLO FINE DI FACILITARE   LA LETTURA",  # maiuscole + spazi
            "ai soli fini della lettura delle norme",
        ],
    )
    def test_varianti(self, testo):
        assert clausola_di_lettura(testo) is True

    @pytest.mark.pure_unit
    @pytest.mark.parametrize(
        "testo",
        [
            "in attuazione della [legge 7 agosto 1990, n. 241](../x.md)",
            "ai sensi dell'articolo 3 del codice penale",
        ],
    )
    def test_non_clausola(self, testo):
        """Contesto presente senza marker → False (non è una clausola di lettura)."""
        assert clausola_di_lettura(testo) is False

    @pytest.mark.policy
    @pytest.mark.parametrize("testo", [None, "", "   ", "akn:ref"])
    def test_non_classificabile(self, testo):
        """Senza contesto non si inventa una classe."""
        assert clausola_di_lettura(testo) is None
