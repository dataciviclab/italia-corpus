"""Test per lab_tools.integra_vigenza — status autorevole (join codice + data GU).

Chiave **esatta** (codice_redazionale, data GU): nessun fallback, perché il
codice redazionale è riciclato (stesso codice per atti diversi).
"""

import pandas as pd
from lab_tools.integra_vigenza import (
    FONTE_ESCLUSIONE,
    FONTE_NON_COPERTO,
    FONTE_NORMATTIVA,
    apply_status,
)


def _norm(rows):
    return pd.DataFrame(
        rows,
        columns=[
            "codice_redazionale", "filename", "collezione", "stato", "vigente",
        ],
    )


def _status(rows):
    return pd.DataFrame(
        rows, columns=["codice_redazionale", "data_gu", "stato"]
    )


def test_match_normattiva():
    out = apply_status(
        _norm([("A", "2000-01-01_000A0001_ORIGINALE_V0.md", "X", "vigente", True)]),
        _status([("A", "2000-01-01", "abrogato")]),
    )
    assert out.loc[0, "stato"] == "abrogato"
    assert out.loc[0, "vigenza_fonte"] == FONTE_NORMATTIVA


def test_non_coperto_tombstone_invariato():
    """Non in status ma con tombstone abrogato → resta abrogato (NON vigente)."""
    out = apply_status(
        _norm([("Z", "2000-01-01_Z_VIGENZA_2025-01-01_V0.md", "X", "abrogato", False)]),
        _status([("A", "2000-01-01", "abrogato")]),
    )
    assert out.loc[0, "stato"] == "abrogato"
    assert out.loc[0, "vigenza_fonte"] == FONTE_NON_COPERTO


def test_esclusione_senza_tombstone():
    """Non in status e senza tombstone → vigente per esclusione."""
    out = apply_status(
        _norm([("Z", "2000-01-01_Z_ORIGINALE_V0.md", "X", "vigente", True)]),
        _status([("A", "2000-01-01", "abrogato")]),
    )
    assert out.loc[0, "stato"] == "vigente"
    assert out.loc[0, "vigenza_fonte"] == FONTE_ESCLUSIONE


def test_no_fallback_codice_riciclato():
    """Regressione: codice riciclato (072U0670 = regio decreto 1872 *e* DPR
    670/1972) → GU diversa, NIENTE fallback → vigente (non abrogato)."""
    out = apply_status(
        _norm([("072U0670", "1972-11-20_072U0670_ORIGINALE_V0.md", "X",
                "vigente", True)]),
        _status([("072U0670", "1872-02-12", "abrogato")]),
    )
    assert out.loc[0, "stato"] == "vigente"
    assert out.loc[0, "vigenza_fonte"] == FONTE_ESCLUSIONE


def test_no_fallback_stesso_anno_numero():
    """Regressione: stesso codice+anno+numero ma atto diverso (046U0098 = due
    DLL del 1946) → GU diversa, NIENTE fallback."""
    out = apply_status(
        _norm([("046U0098", "1946-03-23_046U0098_VIGENZA_V0.md", "X",
                "vigente", True)]),
        _status([("046U0098", "1946-09-20", "abrogato")]),
    )
    assert out.loc[0, "stato"] == "vigente"
    assert out.loc[0, "vigenza_fonte"] == FONTE_ESCLUSIONE


def test_propagazione_atto_level():
    """ORIGINALE e VIGENZA della stessa legge → stesso stato (fix #67)."""
    out = apply_status(
        _norm([
            ("A", "2000-01-01_A_VIGENZA_2025-01-01_V0.md", "X", "abrogato", False),
            ("A", "2000-01-01_A_ORIGINALE_V0.md", "X", "vigente", True),
        ]),
        _status([("A", "2000-01-01", "abrogato")]),
    )
    assert set(out["stato"]) == {"abrogato"}


def test_decaduto_da_collezione():
    out = apply_status(
        _norm([("051U0207", "1951-04-09_051U0207_VIGENZA_V0.md",
                "DL decaduti", "vigente", True)]),
        _status([("051U0207", "1951-04-09", "abrogato")]),
    )
    assert out.loc[0, "stato"] == "decaduto"
    assert out.loc[0, "vigenza_fonte"] == FONTE_NORMATTIVA
