"""Canonicalizzazione URN degli archi AKN (#142)."""

import pandas as pd
from lab_tools.akn_canonicalizza import (
    canonical_index,
    canonicalizza_urns,
    dedup_per_slug,
)

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


class TestDedupPerSlug:
    """Le forme URN diverse dello stesso arco sono una riga sola (#109)."""

    FONTE = "urn:nir:stato:decreto.legislativo:2007-11-06;202"
    VECCHIO = "urn:nir:stato:decretodelpresidentedellarepubblica:1978-05-27;504"
    NUOVO = "urn:nir:stato:decreto.del.presidente.della.repubblica:1978-05-27;504"

    def _df(self, righe):
        import pandas as pd

        return pd.DataFrame(righe)

    def test_tiene_la_riga_col_contesto(self):
        df = self._df([
            {"fonte_urn": self.FONTE, "fonte_codice": None, "target_urn": self.VECCHIO,
             "rel_type": "citation", "origin": "ref", "detail": "/akn/x/!main",
             "contesto": None, "locator": None, "articolo": None},
            {"fonte_urn": self.FONTE, "fonte_codice": None, "target_urn": self.NUOVO,
             "rel_type": "citation", "origin": "ref", "detail": "/akn/x/!main",
             "contesto": "visto il decreto", "locator": "1", "articolo": "art_1"},
        ])
        out = dedup_per_slug(df)
        assert len(out) == 1
        assert out.iloc[0]["target_urn"] == self.NUOVO
        assert out.iloc[0]["contesto"] == "visto il decreto"
        assert out.iloc[0]["locator"] == "1"

    def test_unisce_locator_e_articolo(self):
        df = self._df([
            {"fonte_urn": self.FONTE, "fonte_codice": None, "target_urn": self.VECCHIO,
             "rel_type": "insertion", "origin": "activeModification", "detail": "x",
             "contesto": None, "locator": "art_3,art_47", "articolo": "art_3,art_47"},
            {"fonte_urn": self.FONTE, "fonte_codice": None, "target_urn": self.NUOVO,
             "rel_type": "insertion", "origin": "activeModification", "detail": "x",
             "contesto": None, "locator": "art_5", "articolo": "art_5"},
        ])
        out = dedup_per_slug(df)
        assert len(out) == 1
        assert out.iloc[0]["locator"] == "art_3,art_47,art_5"
        assert out.iloc[0]["articolo"] == "art_3,art_47,art_5"

    def test_atti_diversi_restano(self):
        altro = "urn:nir:stato:decreto.del.presidente.della.repubblica:1978-05-27;505"
        df = self._df([
            {"fonte_urn": self.FONTE, "fonte_codice": None, "target_urn": self.NUOVO,
             "rel_type": "citation", "origin": "ref", "detail": "a", "contesto": "x"},
            {"fonte_urn": self.FONTE, "fonte_codice": None, "target_urn": altro,
             "rel_type": "citation", "origin": "ref", "detail": "a", "contesto": "y"},
        ])
        assert len(dedup_per_slug(df)) == 2

    def test_stringa_vuota_non_e_contesto(self):
        """`''` non deve vincere il tie-break sull'identità (nota review #151)."""
        df = self._df([
            {"fonte_urn": self.FONTE, "fonte_codice": None, "target_urn": self.VECCHIO,
             "rel_type": "citation", "origin": "ref", "detail": "/akn/x/!main",
             "contesto": "", "locator": None, "articolo": None},
            {"fonte_urn": self.FONTE, "fonte_codice": None, "target_urn": self.NUOVO,
             "rel_type": "citation", "origin": "ref", "detail": "/akn/x/!main",
             "contesto": "visto il decreto", "locator": "1", "articolo": "art_1"},
        ])
        out = dedup_per_slug(df)
        assert len(out) == 1
        assert out.iloc[0]["target_urn"] == self.NUOVO
        assert out.iloc[0]["contesto"] == "visto il decreto"

    def test_evidenza_non_si_perde_nel_collasso(self):
        """L'evidenza della riga vecchia non deve sparire (C1)."""
        df = self._df([
            {"fonte_urn": self.FONTE, "fonte_codice": None, "target_urn": self.VECCHIO,
             "rel_type": "insertion", "origin": "activeModification", "detail": "x",
             "contesto": None, "locator": "art_3", "articolo": "art_3",
             "evidenza": "ha disposto (con l'art. 1) l'abrogazione dell'intero provvedimento."},
            {"fonte_urn": self.FONTE, "fonte_codice": None, "target_urn": self.NUOVO,
             "rel_type": "insertion", "origin": "activeModification", "detail": "x",
             "contesto": None, "locator": "art_5", "articolo": "art_5",
             "evidenza": ""},
        ])
        out = dedup_per_slug(df)
        assert len(out) == 1
        assert out.iloc[0]["evidenza"].startswith("ha disposto")
