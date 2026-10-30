"""Stato del corpus in una schermata: cosa c'è, quanto è fresco, cosa manca.

Un comando (`make stato`) per rispondere alla domanda "com'è messa IC?" senza
aprire il codice: file derivati, copertura del catalogo, collezioni congelate,
clausole di lettura. Nessuna rete, nessuna scrittura.

Uso:
    python -m lab_tools.stato
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from lab_tools._paths import COLLEZIONI_ROOT, OUTDIR, load_pin

PROBE_JSON = OUTDIR / "collezioni_probe.json"


def _parquet_info(path: Path, colonne: list[str] | None = None) -> dict | None:
    """Righe + mtime di un parquet (None se assente/illeggibile)."""
    if not path.exists():
        return None
    try:
        import pyarrow.parquet as pq

        pf = pq.ParquetFile(path)
        n = pf.metadata.num_rows
        data = {c: pf.read(columns=[c]).column(c).to_pylist() for c in (colonne or [])}
    except Exception:  # noqa: BLE001 — diagnostica, non deve mai bloccare
        return {"righe": None, "mtime": datetime.fromtimestamp(path.stat().st_mtime), "dati": {}}
    return {
        "righe": n,
        "mtime": datetime.fromtimestamp(path.stat().st_mtime),
        "dati": data,
    }


def _fmt(info: dict | None, extra: str = "") -> str:
    if info is None:
        return "assente"
    righe = info["righe"]
    quando = info["mtime"].strftime("%Y-%m-%d %H:%M")
    testo = f"{(righe if righe is not None else '?'):>9} righe · {quando}"
    return f"{testo} · {extra}" if extra else testo


def _conta_md() -> int:
    return sum(1 for _ in COLLEZIONI_ROOT.rglob("*.md"))


def _probe() -> dict | None:
    if not PROBE_JSON.exists():
        return None
    try:
        return json.loads(PROBE_JSON.read_text())
    except json.JSONDecodeError:
        return None


def main() -> int:
    print("Italia Corpus — stato\n")

    md = _conta_md()
    normativa = _parquet_info(OUTDIR / "normativa.parquet")
    print(f"corpus        {md:>9} file md · normativa: {_fmt(normativa)}")

    catalogo = _parquet_info(OUTDIR / "atti_index.parquet", ["in_corpus", "denominazione"])
    if catalogo and catalogo["righe"]:
        in_corpus = sum(1 for v in catalogo["dati"].get("in_corpus", []) if v)
        dl = [
            d == "DECRETO-LEGGE" and not c
            for d, c in zip(
                catalogo["dati"].get("denominazione", []),
                catalogo["dati"].get("in_corpus", []),
            )
        ]
        pct = 100.0 * in_corpus / catalogo["righe"]
        print(
            f"catalogo      {_fmt(catalogo)} · in corpus {in_corpus} ({pct:.1f}%) · "
            f"decreti-legge mancanti {sum(dl)}"
        )
    else:
        print("catalogo      assente (esegui `make atti-index`)")

    rif = _parquet_info(OUTDIR / "riferimenti.parquet", ["clausola_lettura"])
    if rif and rif["righe"]:
        lettura = sum(1 for v in rif["dati"].get("clausola_lettura", []) if v)
        print(
            f"riferimenti   {_fmt(rif)} · clausole di lettura {lettura} "
            f"({100.0 * lettura / rif['righe']:.1f}%)"
        )
    else:
        print("riferimenti   assente (esegui `make grafo`)")

    for nome, file in (
        ("akn relations", "akn_relations.parquet"),
        ("status abrogati", "status.parquet"),
        ("atti da API", "atti_api.parquet"),
    ):
        print(f"{nome:22s} {_fmt(_parquet_info(OUTDIR / file))}")

    pin = load_pin()
    probe = _probe()
    if probe:
        congelate = [c["nome"] for c in probe["collezioni"] if c["stato"] == "congelata"]
        quando = (probe.get("probed_at") or "")[:16].replace("T", " ")
        print(
            f"\ncollezioni    {probe['sintesi']['collezioni_api']} in Normattiva · "
            f"{probe['sintesi']['in_config']} in config · {len(pin)} pinnate · "
            f"probe {quando}"
        )
        if congelate:
            da = max(
                (c.get("senza_pin_da") or 0 for c in probe["collezioni"] if c["stato"] == "congelata"),
                default=0,
            )
            print(f"              {len(congelate)} congelate (formato pinnato assente, da {da} probe):")
            for nome in congelate:
                print(f"                · {nome}")
    else:
        print("\ncollezioni    probe assente (esegui `make probe-collezioni`)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
