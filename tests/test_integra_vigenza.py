"""Test per lab_tools.integra_vigenza — status autorevole (join codice + data GU)."""

import pandas as pd
from lab_tools.integra_vigenza import (
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
    assert not bool(out.loc[0, "vigente"])


def test_no_match_vigente():
    """Assente da status (solo abrogati) → vigente per esclusione."""
    out = apply_status(
        _norm([("A", "2000-01-01_000A0001_ORIGINALE_V0.md", "X", "abrogato", False)]),
        _status([("B", "2001-01-01", "abrogato")]),
    )
    assert out.loc[0, "stato"] == "vigente"
    assert out.loc[0, "vigenza_fonte"] == FONTE_NORMATTIVA


def test_decaduto_da_collezione():
    """Collezione 'DL decaduti' → decaduto (la ricerca li dà abrogati)."""
    out = apply_status(
        _norm([("051U0207", "1951-04-09_051U0207_VIGENZA_2025-07-09_V0.md",
                "DL decaduti", "vigente", True)]),
        _status([("051U0207", "1951-04-09", "abrogato")]),
    )
    assert out.loc[0, "stato"] == "decaduto"
    assert out.loc[0, "vigenza_fonte"] == FONTE_NORMATTIVA


def test_chiave_ambigua_disambiguata_da_data_gu():
    """Regressione: stesso (codice, anno, numero) ma **GU diverse** = atti diversi.

    Il corpus (filename GU 1946-02-28) deve prendere la riga `vigente`, NON
    l'`abrogato` (GU 1946-08-06). Il tie-break "prefer abrogato" era un falso.
    """
    out = apply_status(
        _norm([("046U0039", "1946-02-28_046U0039_VIGENZA_2025-06-11_V0.md",
                "X", "vigente", True)]),
        _status([
            ("046U0039", "1946-02-28", "vigente"),
            ("046U0039", "1946-08-06", "abrogato"),
        ]),
    )
    assert out.loc[0, "stato"] == "vigente"
    assert out.loc[0, "vigenza_fonte"] == FONTE_NORMATTIVA


def test_tie_break_deterministico():
    """Chiave duplicata residua (stesso codice+GU, stato conflittuale) → abrogato."""
    out = apply_status(
        _norm([("26G00061", "2026-01-01_26G00061_V0.md", "X", "vigente", True)]),
        _status([
            ("26G00061", "2026-01-01", "vigente"),
            ("26G00061", "2026-01-01", "abrogato"),
        ]),
    )
    assert out.loc[0, "stato"] == "abrogato"
