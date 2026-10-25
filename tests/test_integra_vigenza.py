"""Test per lab_tools.integra_vigenza — status autorevole (join codice + data GU)."""

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


def test_fallback_codice():
    """GU diversa ma codice univoco in status → match per codice."""
    out = apply_status(
        _norm([("094G0143", "1994-04-22_094G0143_VIGENZA_V0.md", "X", "vigente", True)]),
        _status([("094G0143", "1994-02-21", "abrogato")]),
    )
    assert out.loc[0, "stato"] == "abrogato"
    assert out.loc[0, "vigenza_fonte"] == FONTE_NORMATTIVA


def test_decaduto_da_collezione():
    out = apply_status(
        _norm([("051U0207", "1951-04-09_051U0207_VIGENZA_V0.md",
                "DL decaduti", "vigente", True)]),
        _status([("051U0207", "1951-04-09", "abrogato")]),
    )
    assert out.loc[0, "stato"] == "decaduto"
    assert out.loc[0, "vigenza_fonte"] == FONTE_NORMATTIVA


def test_fallback_codice_non_applicato_se_ambiguo():
    """Due righe per codice (GU diverse) → fallback codice NON applicato."""
    out = apply_status(
        _norm([("046U0039", "1946-03-01_046U0039_ORIGINALE_V0.md", "X", "vigente", True)]),
        _status([
            ("046U0039", "1946-02-28", "abrogato"),
            ("046U0039", "1946-08-06", "abrogato"),
        ]),
    )
    # codice ambiguo → niente fallback; GU non combacia → vigente per esclusione
    assert out.loc[0, "stato"] == "vigente"
    assert out.loc[0, "vigenza_fonte"] == FONTE_ESCLUSIONE
