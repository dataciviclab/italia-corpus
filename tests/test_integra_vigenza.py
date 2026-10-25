"""Test per lab_tools.integra_vigenza — status autorevole (join codice+anno+numero)."""

import pandas as pd
from lab_tools.integra_vigenza import (
    FONTE_NORMATTIVA,
    FONTE_UNKNOWN,
    apply_status,
)


def _norm(rows):
    return pd.DataFrame(
        rows,
        columns=[
            "codice_redazionale", "anno_atto", "numero", "collezione",
            "stato", "vigente",
        ],
    )


def _status(rows):
    return pd.DataFrame(
        rows, columns=["codice_redazionale", "anno", "numero", "stato"]
    )


def test_match_normattiva():
    out = apply_status(
        _norm([("A", 2000, "1", "X", "vigente", True)]),
        _status([("A", "2000", "1", "abrogato")]),
    )
    assert out.loc[0, "stato"] == "abrogato"
    assert out.loc[0, "vigenza_fonte"] == FONTE_NORMATTIVA
    assert not bool(out.loc[0, "vigente"])


def test_no_match_unknown():
    out = apply_status(
        _norm([("A", 2000, "1", "X", "vigente", True)]),
        _status([("B", "2001", "2", "abrogato")]),
    )
    assert out.loc[0, "stato"] == "vigente"
    assert out.loc[0, "vigenza_fonte"] == FONTE_UNKNOWN


def test_decaduto_da_collezione():
    """Collezione 'DL decaduti' → decaduto (la ricerca li dà abrogati)."""
    out = apply_status(
        _norm([("051U0207", 1951, "207", "DL decaduti", "vigente", True)]),
        _status([("051U0207", "1951", "207", "abrogato")]),
    )
    assert out.loc[0, "stato"] == "decaduto"
    assert out.loc[0, "vigenza_fonte"] == FONTE_NORMATTIVA


def test_chiave_codice_non_univoco():
    """Due atti con lo stesso codice ma numero diverso → status distinti."""
    out = apply_status(
        _norm([
            ("096G0493", 1996, "466", "X", "vigente", True),
            ("096G0493", 1996, "555", "X", "vigente", True),
        ]),
        _status([
            ("096G0493", "1996", "466", "abrogato"),
            ("096G0493", "1996", "555", "vigente"),
        ]),
    )
    by_num = out.set_index("numero")
    assert by_num.loc["466", "stato"] == "abrogato"
    assert by_num.loc["555", "stato"] == "vigente"
