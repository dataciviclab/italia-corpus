"""Test per l'identità dell'atto: `versione`, `snapshot_data`, `is_current`.

`is_current` marca **l'espressione corrente** dell'atto: una sola riga per URN
(le espressioni ORIGINALE/VIGENZA sono lo stesso atto). Regola: VIGENZA con
snapshot più recente → altrimenti ORIGINALE → tie deterministico.
"""

from __future__ import annotations

from lab_tools.extract import _marca_is_current, _versione_da_filename


class TestVersioneDaFilename:
    def test_vigenza_con_data(self):
        assert _versione_da_filename("2020-01-01_20G00001_VIGENZA_2025-10-14_V0.md") == (
            "VIGENZA",
            "2025-10-14",
        )

    def test_originale_senza_data(self):
        assert _versione_da_filename("2020-01-01_20G00001_ORIGINALE_V0.md") == ("ORIGINALE", None)

    def test_forma_sconosciuta_non_silenziosa(self):
        """Un naming nuovo non deve essere interpretato a caso."""
        assert _versione_da_filename("2020-01-01_20G00001_V0.md") == ("", None)


def _atto(filename: str, urn: str, versione: str, snapshot: str | None) -> dict:
    return {
        "filename": filename,
        "urn": urn,
        "versione": versione,
        "snapshot_data": snapshot,
        "duplicato": False,
    }


class TestMarcaIsCurrent:
    def test_urn_unico_e_corrente(self):
        rec = [_atto("a.md", "urn:1", "ORIGINALE", None)]
        _marca_is_current(rec)
        assert rec[0]["is_current"] is True

    def test_due_vigenza_prende_lo_snapshot_piu_recente(self):
        """Caso reale (701 atti): due consolidati, vince il più recente."""
        rec = [
            _atto("b.md", "urn:1", "VIGENZA", "2025-06-11"),
            _atto("a.md", "urn:1", "VIGENZA", "2025-10-14"),
        ]
        _marca_is_current(rec)
        correnti = [r["filename"] for r in rec if r["is_current"]]
        assert correnti == ["a.md"]

    def test_originale_piu_vigenza_prende_vigenza(self):
        """Caso reale (521 atti): vince il consolidato, non l'originale."""
        rec = [
            _atto("originale.md", "urn:1", "ORIGINALE", None),
            _atto("vigenza.md", "urn:1", "VIGENZA", "2025-01-01"),
        ]
        _marca_is_current(rec)
        assert [r["filename"] for r in rec if r["is_current"]] == ["vigenza.md"]

    def test_una_sola_riga_corrente_per_urn(self):
        rec = [
            _atto("a.md", "urn:1", "ORIGINALE", None),
            _atto("b.md", "urn:1", "VIGENZA", "2025-01-01"),
            _atto("c.md", "urn:1", "VIGENZA", "2025-02-01"),
            _atto("d.md", "urn:2", "ORIGINALE", None),
            _atto("e.md", "urn:3", "VIGENZA", "2024-01-01"),
        ]
        _marca_is_current(rec)
        for urn in ("urn:1", "urn:2", "urn:3"):
            assert sum(1 for r in rec if r["urn"] == urn and r["is_current"]) == 1
        assert sum(1 for r in rec if r["is_current"]) == 3

    def test_deterministico_sull_ordine_dei_record(self):
        """La scelta non dipende dall'ordine dei file su disco."""
        base = [
            _atto("z.md", "urn:1", "VIGENZA", "2025-01-01"),
            _atto("a.md", "urn:1", "VIGENZA", "2025-01-01"),
            _atto("m.md", "urn:1", "ORIGINALE", None),
        ]
        esiti = []
        for perm in (base, list(reversed(base)), [base[1], base[2], base[0]]):
            rec = [dict(r) for r in perm]
            _marca_is_current(rec)
            esiti.append([r["filename"] for r in rec if r["is_current"]])
        assert esiti == [["a.md"]] * 3

    def test_urn_vuoto_e_corrente_di_se(self):
        """Righe senza URN (oggi 0) non appartengono a un gruppo: correnti."""
        rec = [_atto("a.md", "", "ORIGINALE", None), _atto("b.md", "", "ORIGINALE", None)]
        _marca_is_current(rec)
        assert all(r["is_current"] for r in rec)
