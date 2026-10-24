"""Test per lab_tools.integra_vigenza — precedenza fonti e vigenza_fonte."""

import pandas as pd
import pytest
from lab_tools.integra_vigenza import (
    FONTE_AKN,
    FONTE_REGEX,
    FONTE_UNKNOWN,
    FONTE_VIGENZA_SNAPSHOT,
    akn_abrogation_targets,
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
    out = apply_vigenza(
        _df(filename=["2000-01-01_000G0001_VIGENZA_2025-06-12_V0.md"],
            urn=[AKN_TARGET], stato=["decaduto"]),
        {AKN_TARGET},
    )
    assert _row(out)["stato"] == "decaduto"
    assert _row(out)["vigenza_fonte"] == FONTE_VIGENZA_SNAPSHOT


def test_abrogato_tombstone_invariato():
    """Tombstone 'abrogato' (non-AKN) non viene toccato; fonte=vigenza_snapshot."""
    out = apply_vigenza(
        _df(filename=["2000-01-01_000G0001_VIGENZA_2025-06-12_V0.md"],
            stato=["abrogato"]),
        set(),
    )
    assert _row(out)["stato"] == "abrogato"
    assert _row(out)["vigenza_fonte"] == FONTE_VIGENZA_SNAPSHOT


def test_regex_solo_candidato():
    """Segnale regex senza AKN: stato NON modificato, fonte=regex."""
    out = apply_vigenza(
        _df(filename=["2000-01-01_000G0001_ORIGINALE_V0.md"],
            stato=["vigente"], n_abrogazioni=[3]),
        set(),
    )
    assert _row(out)["stato"] == "vigente"
    assert _row(out)["vigenza_fonte"] == FONTE_REGEX


def test_regex_non_sovrascrive_tombstone():
    """Abrogato da tombstone (non-AKN) con n_abro>0 → vigenza_snapshot, non regex."""
    out = apply_vigenza(
        _df(filename=["2000-01-01_000G0001_VIGENZA_2025-06-12_V0.md"],
            stato=["abrogato"], n_abrogazioni=[5]),
        set(),
    )
    assert _row(out)["stato"] == "abrogato"
    assert _row(out)["vigenza_fonte"] == FONTE_VIGENZA_SNAPSHOT


def test_regex_non_sovrascrive_decaduto_akn():
    """Decaduto + target AKN con n_abro>0 → vigenza_snapshot (decaduto prevale)."""
    out = apply_vigenza(
        _df(filename=["2000-01-01_000G0001_VIGENZA_2025-06-12_V0.md"],
            urn=[AKN_TARGET], stato=["decaduto"], n_abrogazioni=[2]),
        {AKN_TARGET},
    )
    assert _row(out)["stato"] == "decaduto"
    assert _row(out)["vigenza_fonte"] == FONTE_VIGENZA_SNAPSHOT


def test_vigenza_snapshot_senza_segnale():
    """Snapshot VIGENZA senza segnale → vigenza_snapshot (confermato)."""
    out = apply_vigenza(
        _df(filename=["2000-01-01_000G0001_VIGENZA_2025-06-12_V0.md"],
            stato=["vigente"], n_abrogazioni=[0]),
        set(),
    )
    assert _row(out)["stato"] == "vigente"
    assert _row(out)["vigenza_fonte"] == FONTE_VIGENZA_SNAPSHOT


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


def test_idempotente_akn():
    """Rieseguire apply_vigenza non degrada akn → vigenza_snapshot."""
    df = _df(
        filename=["2000-01-01_000G0001_VIGENZA_2025-06-12_V0.md"],
        urn=[AKN_TARGET], stato=["vigente"], n_abrogazioni=[0],
    )
    once = apply_vigenza(df, {AKN_TARGET})
    twice = apply_vigenza(once, {AKN_TARGET})
    assert _row(twice)["stato"] == "abrogato"
    assert _row(twice)["vigenza_fonte"] == FONTE_AKN


def test_akn_schema_inatteso_errore_chiaro(tmp_path):
    """akn_relations con colonne sbagliate → SystemExit con messaggio."""
    bad = tmp_path / "akn_relations.parquet"
    pd.DataFrame({"foo": [1]}).to_parquet(bad)
    with pytest.raises(SystemExit, match="colonne mancanti"):
        akn_abrogation_targets(bad)


def test_akn_file_assente_vuoto(tmp_path):
    """akn_relations assente → nessun target (nessun errore)."""
    assert akn_abrogation_targets(tmp_path / "nope.parquet") == set()
