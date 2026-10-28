"""Regressione sulla gold set del campo `materia` (200 atti annotati a mano).

Due campioni stratificati indipendenti da 100 atti:
- `materia_gold.csv`          — sviluppo (seed 42)
- `materia_gold_holdout.csv`  — validazione (seed 7, atti disgiunti)

Baseline pre-fix (`materia_attuale`) = 56% su entrambi. Le soglie proteggono il
guadagno misurato: se un cambio di keyword o di ordine le abbassa, si rivede
l'annotazione, non la soglia. Report completo in docs/MATERIA_AUDIT.md.

Dettaglio per materia e per causa di errore: `pytest tests/test_classifica_gold.py -s`.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from lab_tools.classifica_tematich import _classifica_oggetto

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLD_FILES = ("materia_gold.csv", "materia_gold_holdout.csv")

BASELINE = 0.56
MIN_PRECISION = 0.75
MAX_DISTACCO_SVILUPPO = 0.10


def _carica(nome: str) -> pd.DataFrame:
    df = pd.read_csv(FIXTURES / nome)
    df["nuova"] = df["oggetto"].fillna("").map(_classifica_oggetto)
    return df


@pytest.mark.contract
@pytest.mark.parametrize("nome", GOLD_FILES)
def test_precision_sopra_soglia(nome):
    df = _carica(nome)
    errori = df[df["nuova"] != df["materia_gold"]]
    assert (df["materia_attuale"] == df["materia_gold"]).mean() == pytest.approx(BASELINE, abs=0.01)
    assert (df["nuova"] == df["materia_gold"]).mean() >= MIN_PRECISION, (
        f"{nome}: errori residui {errori[['idx', 'materia_gold', 'nuova']].to_dict('records')}"
    )


@pytest.mark.contract
@pytest.mark.parametrize("nome", GOLD_FILES)
def test_nessuna_regressione_su_baseline(nome):
    """Nessun atto che il classificatore pre-fix azzeccava deve rompersi."""
    df = _carica(nome)
    regressi = df[(df["materia_attuale"] == df["materia_gold"]) & (df["nuova"] != df["materia_gold"])]
    assert regressi.empty, f"{nome}: {regressi[['idx', 'materia_gold', 'nuova']].to_dict('records')}"


@pytest.mark.contract
def test_holdout_non_peggiore_dello_sviluppo():
    """Guardia contro l'overfitting sulle keyword del campione di sviluppo."""
    p = {n: (_carica(n).pipe(lambda d: (d["nuova"] == d["materia_gold"]).mean())) for n in GOLD_FILES}
    sviluppo, holdout = p["materia_gold.csv"], p["materia_gold_holdout.csv"]
    assert holdout >= sviluppo - MAX_DISTACCO_SVILUPPO, f"holdout {holdout:.2f} vs sviluppo {sviluppo:.2f}"


@pytest.mark.contract
def test_report(capsys):
    """Report leggibile (non fallisce): `pytest tests/test_classifica_gold.py -s`."""
    righe = []
    for nome in GOLD_FILES:
        df = _carica(nome)
        errs = df[df["nuova"] != df["materia_gold"]]
        righe.append(f"{nome}: {len(df)} atti, precision {(df['nuova'] == df['materia_gold']).mean():.0%}")
        for causa, n in errs["errore_tipo"].replace("", "non-classificato").value_counts().items():
            righe.append(f"    errore residuo {causa}: {n}")
        ok = df.assign(ok=df["nuova"] == df["materia_gold"])
        per_materia = ok.groupby("materia_gold")["ok"].agg(["size", "mean"])
        righe += [
            f"    {m:18} {100 * r['mean']:5.1f}%  (n={int(r['size'])})"
            for m, r in per_materia.iterrows()
            if r["size"] >= 3
        ]
    with capsys.disabled():
        print("\n" + "\n".join(righe))
