"""Test per lab_tools.fetch_status — mapping classeProvvedimento → stato."""

from lab_tools.fetch_status import build_rows


def _atto(cod="051U0207", **over):
    a = {
        "codiceRedazionale": cod,
        "denominazioneAtto": "DECRETO-LEGGE",
        "annoProvvedimento": "1951",
        "numeroProvvedimento": "207",
        "dataGU": "1951-04-09",
        "titoloAtto": "Disposizioni",
    }
    a.update(over)
    return a


def test_classe_1_2_vigente():
    rows = build_rows([("1", [_atto("A")]), ("2", [_atto("B")])])
    assert {r["codice_redazionale"]: r["stato"] for r in rows} == {
        "A": "vigente", "B": "vigente",
    }


def test_classe_3_abrogato():
    rows = build_rows([("3", [_atto("C")])])
    assert rows[0]["stato"] == "abrogato"
    assert rows[0]["classe"] == "3"


def test_salta_senza_codice():
    rows = build_rows([("3", [_atto("C"), _atto(None)])])
    assert len(rows) == 1


def test_classe_sconosciuta_ignorata():
    rows = build_rows([("9", [_atto("C")])])
    assert rows == []


def test_campi_derivati():
    rows = build_rows([("3", [_atto("051U0207")])])
    r = rows[0]
    assert r["denominazione"] == "DECRETO-LEGGE"
    assert r["anno"] == "1951"
    assert r["numero"] == "207"
    assert r["data_gu"] == "1951-04-09"
