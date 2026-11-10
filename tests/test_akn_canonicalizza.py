"""Canonicalizzazione URN degli archi AKN (#142)."""

import pandas as pd
from lab_tools.akn_canonicalizza import canonical_index, canonicalizza_urns

CANON = [
    "urn:nir:stato:regio.decreto:1942-03-16;262",
    "urn:nir:stato:decreto.del.presidente.della.repubblica:1988-09-22;447",
    "urn:nir:stato:legge:1990-08-07;241",
]


def _df(targets):
    return pd.DataFrame(
        [
            {
                "fonte_urn": "urn:nir:stato:legge:1990-08-07;241",
                "target_urn": t,
                "rel_type": "citation",
                "origin": "ref",
                "detail": f"/akn/...#art_{i}",
            }
            for i, t in enumerate(targets, start=1)
        ]
    )


def test_alias_codice_e_slug():
    index = canonical_index(CANON)
    out, per_regola, duplicati = canonicalizza_urns(
        _df(
            [
                "urn:nir:stato:codice.civile:1942-03-16;262",  # ALIAS_CODICI
                "urn:nir:stato:regiodecreto:1942-03-16;262",  # slug
                "urn:nir:stato:regio.decreto:1942-03-16;262",  # già canonica
            ]
        ),
        index,
    )
    assert set(out["target_urn"]) == {"urn:nir:stato:regio.decreto:1942-03-16;262"}
    assert duplicati == 0  # detail diversi: tre citazioni, non duplicati
    assert per_regola.get("codice") == 1
    assert per_regola.get("slug") == 1


def test_dpr_senza_punti():
    index = canonical_index(CANON)
    out, _, _ = canonicalizza_urns(
        _df(["urn:nir:stato:decretodelpresidentedellarepubblica:1988-09-22;447"]),
        index,
    )
    assert out["target_urn"].iloc[0] == (
        "urn:nir:stato:decreto.del.presidente.della.repubblica:1988-09-22;447"
    )


def test_sconosciuto_resta_invariato():
    index = canonical_index(CANON)
    ignoto = "urn:nir:stato:legge:1999-01-01;999"
    out, per_regola, _ = canonicalizza_urns(_df([ignoto]), index)
    assert out["target_urn"].iloc[0] == ignoto
    assert not per_regola


def test_duplicati_con_stesso_detail():
    """Due forme della stessa citazione collassano (stesso detail)."""
    index = canonical_index(CANON)
    df = pd.DataFrame(
        [
            {
                "fonte_urn": "urn:nir:stato:legge:1990-08-07;241",
                "target_urn": "urn:nir:stato:codice.civile:1942-03-16;262",
                "rel_type": "citation",
                "origin": "ref",
                "detail": "/akn/...#art_2043",
            },
            {
                "fonte_urn": "urn:nir:stato:legge:1990-08-07;241",
                "target_urn": "urn:nir:stato:regio.decreto:1942-03-16;262",
                "rel_type": "citation",
                "origin": "ref",
                "detail": "/akn/...#art_2043",
            },
        ]
    )
    out, _, duplicati = canonicalizza_urns(df, index)
    assert duplicati == 1
    assert len(out) == 1
