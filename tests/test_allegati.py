"""Test per lab_tools.allegati: file per atto + indice accumulativo."""

from __future__ import annotations

import pandas as pd
from lab_tools.allegati import aggiorna_indice, righe_indice, scrivi_atto

XML = """<?xml version="1.0"?>
<akn xmlns="http://www.normattiva.it/akn">
  <attachments>
    <doc name="Codice Penale-art. 1" FRBRthis="u/!main/annesso_1">
      <mainBody><article><num>Art. 1</num><p>Testo.</p></article></mainBody>
    </doc>
  </attachments>
</akn>"""


class TestScriviAtto:
    def test_file_e_riga(self, tmp_path):
        rows = scrivi_atto(XML, "urn:x", "2020-01-01_020G0001", "ORIGINALE", None, tmp_path)
        assert len(rows) == 1
        assert rows[0]["versione"] == "ORIGINALE"
        assert rows[0]["snapshot_data"] is None
        assert rows[0]["rel_path"] == "allegati/2020-01-01_020G0001.md"
        assert rows[0]["hash"]
        assert rows[0]["chars"] > 0
        testo = (tmp_path / "2020-01-01_020G0001.md").read_text(encoding="utf-8")
        assert "## Codice Penale-art. 1" in testo

    def test_senza_allegati(self, tmp_path):
        assert scrivi_atto("<akn/>", "urn:x", "c", "ORIGINALE", None, tmp_path) == []
        assert not list(tmp_path.glob("*.md"))


class TestAggiornaIndice:
    def test_accumulativo_per_data_codice(self, tmp_path):
        p = tmp_path / "allegati.parquet"
        a = righe_indice(
            "A", "urn:a", "VIGENZA", "2026-01-01",
            [{"doc_id": "d1", "doc_name": "A-1", "markdown": "x"}], "allegati/A.md",
        )
        b = righe_indice(
            "B", "urn:b", "ORIGINALE", None,
            [{"doc_id": "d1", "doc_name": "B-1", "markdown": "y"}], "allegati/B.md",
        )
        assert aggiorna_indice(a + b, p) == 2

        b2 = righe_indice(
            "B", "urn:b", "VIGENZA", "2026-02-01",
            [
                {"doc_id": "d1", "doc_name": "B-1", "markdown": "y"},
                {"doc_id": "d2", "doc_name": "B-2", "markdown": "z"},
            ],
            "allegati/B.md",
        )
        assert aggiorna_indice(b2, p) == 3

        df = pd.read_parquet(p)
        assert set(df["data_codice"]) == {"A", "B"}
        assert (df[df["data_codice"] == "B"]["versione"] == "VIGENZA").all()
