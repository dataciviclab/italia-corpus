"""Test per lab_tools.integra_vigenza — precedenza fonti e vigenza_fonte."""

import pandas as pd
from lab_tools.integra_vigenza import (
    FONTE_AKN,
    FONTE_REGEX,
    FONTE_TOMBSTONE,
    FONTE_UNKNOWN,
    apply_vigenza,
)

AKN_TARGET = "urn:nir:stato:decreto.legislativo:2016-04-18;50"


def _df(**over):
    base = {
        "urn": ["urn:nir:stato:legge:2000-01-01;1"],
        "filename": ["2000-01-01_000G0001_ORIGINALE_V0.md"],
        "stato": ["vigente"],
        "n_abrogazioni": [0],
    }
    base.update(over)
    return pd.DataFrame(base)


def _row(df, i=0):
    return df.iloc[i]


def test_akn_target_override():
    """Target di repeal/substitution → abrogato, fonte=akn."""
    out = apply_vigenza(_df(urn=[AKN_TARGET], stato=["vigente"]), {AKN_TARGET})
    assert _row(out)["stato"] == "abrogato"
    assert _row(out)["vigenza_fonte"] == FONTE_AKN
    assert not bool(_row(out)["vigente"])


def test_decaduto_prevale_su_akn():
    """Tombstone 'decaduto' resta decaduto anche se target AKN."""
    out = apply_vigenza(_df(urn=[AKN_TARGET], stato=["decaduto"]), {AKN_TARGET})
    assert _row(out)["stato"] == "decaduto"
    assert _row(out)["vigenza_fonte"] == FONTE_TOMBSTONE


def test_abrogato_tombstone_invariato():
    """Tombstone 'abrogato' non viene toccato; fonte=tombstone."""
    out = apply_vigenza(_df(stato=["abrogato"]), set())
    assert _row(out)["stato"] == "abrogato"
    assert _row(out)["vigenza_fonte"] == FONTE_TOMBSTONE


def test_regex_solo_candidato():
    """Segnale regex senza AKN: stato NON modificato, fonte=regex."""
    out = apply_vigenza(
        _df(filename=["2000-01-01_000G0001_ORIGINALE_V0.md"],
            stato=["vigente"], n_abrogazioni=[3]),
        set(),
    )
    assert _row(out)["stato"] == "vigente"
    assert _row(out)["vigenza_fonte"] == FONTE_REGEX


def test_vigenza_snapshot_senza_segnale():
    """Snapshot VIGENZA senza segnale → tombstone (affidabile)."""
    out = apply_vigenza(
        _df(filename=["2000-01-01_000G0001_VIGENZA_2025-06-12_V0.md"],
            stato=["vigente"], n_abrogazioni=[0]),
        set(),
    )
    assert _row(out)["stato"] == "vigente"
    assert _row(out)["vigenza_fonte"] == FONTE_TOMBSTONE


def test_originale_senza_segnale_unknown():
    """Snapshot ORIGINALE senza segnale → unknown (non verificato)."""
    out = apply_vigenza(
        _df(filename=["2000-01-01_000G0001_ORIGINALE_V0.md"],
            stato=["vigente"], n_abrogazioni=[0]),
        set(),
    )
    assert _row(out)["stato"] == "vigente"
    assert _row(out)["vigenza_fonte"] == FONTE_UNKNOWN


def test_colonna_vigente_coerente():
    """`vigente` rispecchia sempre `stato`."""
    out = apply_vigenza(
        _df(urn=[AKN_TARGET], stato=["vigente"], n_abrogazioni=[0]),
        {AKN_TARGET},
    )
    assert (out["vigente"] == (out["stato"] == "vigente")).all()


def test_senza_colonna_n_abrogazioni():
    """Senza n_abrogazioni non ci sono candidati regex."""
    df = pd.DataFrame({
        "urn": ["urn:nir:stato:legge:2000-01-01;1"],
        "filename": ["2000-01-01_000G0001_ORIGINALE_V0.md"],
        "stato": ["vigente"],
    })
    out = apply_vigenza(df, set())
    assert _row(out)["vigenza_fonte"] == FONTE_UNKNOWN
