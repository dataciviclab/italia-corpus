"""Test per lab_tools.asserts — i gate estratti dai workflow.

Ogni test protegge un comportamento che in CI *deve* fermare il build, oppure
un'eccezione deliberata (allowlist, baseline assente). Prima erano heredoc nel
YAML: se qualcuno li rompeva, nessun test se ne accorgeva.
"""

from __future__ import annotations

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from lab_tools.asserts import (
    allowlist_urns,
    diff_urn,
    missing_columns,
    regex_unresolved,
    renamed_files,
    vigenza_downgrade,
)


def _scrivi_normativa(path, urns, filename=None, is_current=None, versione=None):
    n = len(urns)
    tab = pa.table(
        {
            "urn": urns,
            "filename": filename or [f"f{i}.md" for i in range(n)],
            "is_current": is_current or [True] * n,
            "versione": versione or ["VIGENZA"] * n,
        }
    )
    pq.write_table(tab, path)


class TestDiffUrn:
    """Nessun atto può sparire build-over-build (classe 29/10)."""

    def test_nessuna_perdita(self):
        assert diff_urn({"a", "b"}, {"a", "b", "c"}, set()) == []

    def test_perdita_bloccante(self):
        assert diff_urn({"a", "b"}, {"a"}, set()) == ["b"]

    def test_allowlist_esenta(self):
        assert diff_urn({"a", "b"}, {"a"}, {"b"}) == []

    def test_ordinato_e_senza_duplicati(self):
        assert diff_urn({"z", "a", "m"}, set(), set()) == ["a", "m", "z"]


class TestMissingColumns:
    """Contract backward-compatible: main ⊂ build."""

    def test_ok(self):
        assert missing_columns(["a", "b"], ["a", "b", "nuova"]) == []

    def test_colonna_sparita(self):
        assert missing_columns(["a", "b"], ["a"]) == ["b"]


class TestVigenzaDowngrade:
    """Un atto corrente che torna ORIGINALE è una regressione."""

    def test_stabile(self):
        assert vigenza_downgrade(13200, 13200) == 0

    def test_calo_entro_soglia(self):
        # soglia = max(50, 1% di 13200 = 132) → 100 non basta a far fallire
        assert vigenza_downgrade(13200, 13100) == 0

    def test_calo_oltre_soglia(self):
        # 300 declassati, soglia 132 → l'eccesso è 168
        assert vigenza_downgrade(13200, 12900) == 168

    def test_minimo_assoluto_su_corpus_piccolo(self):
        # main piccolo: la soglia è il minimo (50), altrimenti 1 atto farebbe 1%
        assert vigenza_downgrade(10, 0) == 0
        assert vigenza_downgrade(60, 0) == 10


class TestRegexUnresolved:
    """Churn dei filename: i link puntano a nomi che non esistono più."""

    def _df(self, rows):
        return pd.DataFrame(rows, columns=["origine", "risolto", "bersaglio_filename"])

    def test_tutto_risolto(self):
        df = self._df([("regex", True, "a.md"), ("akn", False, "b")])
        assert regex_unresolved(df) == (0, 0)

    def test_conta_per_bersaglio_non_per_link(self):
        df = self._df(
            [
                ("regex", False, "vecchio1.md"),
                ("regex", False, "vecchio1.md"),
                ("regex", False, "vecchio2.md"),
            ]
        )
        assert regex_unresolved(df) == (3, 2)

    def test_gli_akn_non_contano(self):
        df = self._df([("akn", False, "x"), ("akn", False, "y")])
        assert regex_unresolved(df) == (0, 0)


class TestRenamedFiles:
    """Advisory: un rename non cambia gli URN ma rompe i link."""

    def test_rinomina(self):
        assert renamed_files({"a.md", "b.md"}, {"a.md", "c.md"}) == ["b.md"]


class TestAllowlist:
    def test_commenti_e_righe_vuote(self, tmp_path):
        p = tmp_path / "allow.txt"
        p.write_text(
            "# commento\nurn:nir:stato:legge:1900-01-01;1\n\n  \
urn:nir:stato:legge:1900-01-01;2  \n# coda\n",
            encoding="utf-8",
        )
        assert allowlist_urns(p) == {
            "urn:nir:stato:legge:1900-01-01;1",
            "urn:nir:stato:legge:1900-01-01;2",
        }

    def test_file_assente(self, tmp_path):
        assert allowlist_urns(tmp_path / "manca.txt") == set()


class TestComandi:
    """Gli stessi gate, sul file vero: il CLI deve dare gli stessi esiti."""

    def test_urn_subset_ok(self, tmp_path, capsys):
        from lab_tools.asserts import main

        base, build = tmp_path / "base.parquet", tmp_path / "build.parquet"
        _scrivi_normativa(base, ["urn:1", "urn:2"])
        _scrivi_normativa(build, ["urn:1", "urn:2", "urn:3"])
        allow = tmp_path / "allow.txt"
        allow.write_text("", encoding="utf-8")
        rc = main(
            ["urn-subset", "--build", str(build), "--baseline", str(base), "--allowlist", str(allow)]
        )
        assert rc == 0
        assert "mancanti=0" in capsys.readouterr().out

    def test_urn_subset_fallisce(self, tmp_path, capsys):
        from lab_tools.asserts import main

        base, build = tmp_path / "base.parquet", tmp_path / "build.parquet"
        _scrivi_normativa(base, ["urn:1", "urn:2"])
        _scrivi_normativa(build, ["urn:1"])
        allow = tmp_path / "allow.txt"
        allow.write_text("", encoding="utf-8")
        rc = main(
            ["urn-subset", "--build", str(build), "--baseline", str(base), "--allowlist", str(allow)]
        )
        assert rc == 1
        assert "URN MANCANTI" in capsys.readouterr().out

    def test_baseline_assente_disattiva_il_gate(self, tmp_path, capsys):
        """Comportamento storico: niente rete → gate spento, build non rotta."""
        from lab_tools.asserts import main

        build = tmp_path / "build.parquet"
        _scrivi_normativa(build, ["urn:1"])
        rc = main(
            [
                "urn-subset",
                "--build",
                str(build),
                "--baseline",
                str(tmp_path / "non_esiste.parquet"),
                "--baseline-url",
                "http://127.0.0.1:9/inesistente.parquet",
            ]
        )
        assert rc == 0
        assert "gate disattivato" in capsys.readouterr().out

    def test_contract_downgrade_fallisce(self, tmp_path):
        from lab_tools.asserts import main

        base, build = tmp_path / "base.parquet", tmp_path / "build.parquet"
        _scrivi_normativa(base, [f"urn:{i}" for i in range(200)])
        _scrivi_normativa(build, [f"urn:{i}" for i in range(200)], versione=["ORIGINALE"] * 200)
        assert main(["contract", "--build", str(build), "--baseline", str(base)]) == 1

    def test_regex_resolution_fallisce(self, tmp_path):
        from lab_tools.asserts import main

        p = tmp_path / "rif.parquet"
        df = pd.DataFrame(
            {
                "origine": ["regex"] * 60,
                "risolto": [False] * 60,
                "bersaglio_filename": [f"x{i}.md" for i in range(60)],
            }
        )
        df.to_parquet(p, index=False)
        assert main(["regex-resolution", "--path", str(p), "--max-bersagli", "50"]) == 1
        assert main(["regex-resolution", "--path", str(p), "--max-bersagli", "60"]) == 0


class TestSchema:
    """Il gate che lega clean.sql allo schema **reale** del raw.

    Nasce da un incidente: aggiungere una colonna alla clean.sql e mergiare
    prima che il raw la contenesse → publish rosso a metà run. `toolkit run
    --dry-run` non lo prende (placeholder).
    """

    def _dataset(self, tmp_path, raw_cols, sql):
        raw = tmp_path / "raw.parquet"
        pa_table = pa.table({c: [1] for c in raw_cols})
        pq.write_table(pa_table, raw)
        (tmp_path / "sql").mkdir()
        (tmp_path / "sql" / "clean.sql").write_text(sql, encoding="utf-8")
        cfg = tmp_path / "dataset.yml"
        cfg.write_text(
            f"""
dataset:
  name: prova
  years: [2026]
raw:
  sources:
    - name: "r"
      type: "local_file"
      args:
        path: "{raw.name}"
clean:
  sql: "sql/clean.sql"
""",
            encoding="utf-8",
        )
        return cfg

    def test_compatibile(self, tmp_path, capsys):
        from lab_tools.asserts import main

        cfg = self._dataset(tmp_path, ["a", "b"], "SELECT a, b FROM raw_input")
        assert main(["schema", "--config", str(cfg)]) == 0
        assert "compatibile" in capsys.readouterr().out

    def test_colonna_mancante(self, tmp_path, capsys):
        from lab_tools.asserts import main

        cfg = self._dataset(tmp_path, ["a"], "SELECT a, nuova_colonna FROM raw_input")
        assert main(["schema", "--config", str(cfg)]) == 1
        out = capsys.readouterr().out
        assert "SCHEMA NON COMPATIBILE" in out
        assert "nuova_colonna" in out

    def test_alias_uguale_alla_colonna(self, tmp_path):
        """`COALESCE(x,'') AS x` con x assente: DuckDB dà un errore criptico."""
        from lab_tools.asserts import main

        cfg = self._dataset(
            tmp_path, ["a"], "SELECT COALESCE(NULLIF(a, ''), 'altro') AS a, COALESCE(b, '') AS b FROM raw_input"
        )
        assert main(["schema", "--config", str(cfg)]) == 1

    def test_raw_assente_skip(self, tmp_path, capsys):
        from lab_tools.asserts import main

        cfg = tmp_path / "dataset.yml"
        cfg.write_text(
            """
dataset: {name: prova, years: [2026]}
raw:
  sources:
    - {name: r, type: local_file, args: {path: "non_esiste.parquet"}}
clean: {sql: "sql/clean.sql"}
""",
            encoding="utf-8",
        )
        assert main(["schema", "--config", str(cfg)]) == 0
        assert "raw assente" in capsys.readouterr().out

    def test_raw_csv_skip(self, tmp_path, capsys):
        """Il bind è su read_parquet: un raw CSV non va bloccato per finta."""
        import pandas as pd
        from lab_tools.asserts import main

        pd.DataFrame({"a": [1]}).to_csv(tmp_path / "raw.csv", index=False)
        cfg = tmp_path / "dataset.yml"
        cfg.write_text(
            """
dataset: {name: prova, years: [2026]}
raw:
  sources:
    - {name: r, type: local_file, args: {path: "raw.csv"}}
clean: {sql: "sql/clean.sql"}
""",
            encoding="utf-8",
        )
        assert main(["schema", "--config", str(cfg)]) == 0
        assert "raw non parquet" in capsys.readouterr().out
