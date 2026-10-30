"""Indice degli allegati AKN (#94): costruzione righe e scrittura accumulativa.

Un file per atto (`allegati/<data_codice>.md`, sezioni `## <doc_name>`) e un
indice `allegati.parquet` con provenienza e hash, consumato da legal-graph.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from lab_tools.akn_parser import allegati_to_markdown

ALLEGATI_DIRNAME = "allegati"


def righe_indice(
    data_codice: str,
    urn: str,
    versione: str,
    snapshot_data: str | None,
    docs: list[dict],
    rel_path: str,
) -> list[dict]:
    """Una riga per `<doc>`, con provenienza (`versione`/`snapshot_data`) e hash."""
    righe: list[dict] = []
    for d in docs:
        markdown = d["markdown"]
        righe.append(
            {
                "data_codice": data_codice,
                "urn": urn,
                "doc_id": d["doc_id"],
                "doc_name": d["doc_name"],
                "chars": len(markdown),
                "hash": hashlib.sha256(markdown.encode("utf-8")).hexdigest()[:16],
                "versione": versione,
                "snapshot_data": snapshot_data,
                "rel_path": rel_path,
            }
        )
    return righe


def scrivi_atto(
    content: str,
    urn: str,
    data_codice: str,
    versione: str,
    snapshot_data: str | None,
    allegati_dir: Path,
    urn_index: dict[str, str] | None = None,
) -> list[dict]:
    """Scrive `allegati/<data_codice>.md` e restituisce le righe d'indice.

    Se l'atto non ha allegati non scrive nulla e restituisce `[]`.
    """
    rel_path = f"{ALLEGATI_DIRNAME}/{data_codice}.md"
    docs = allegati_to_markdown(content, urn_index or {}, rel_path)
    if not docs:
        return []

    blocchi = [f"# Allegati - {data_codice}", ""]
    for d in docs:
        blocchi.extend([f"## {d['doc_name']}", "", d["markdown"], ""])
    testo = "\n".join(blocchi).strip() + "\n"

    allegati_dir.mkdir(parents=True, exist_ok=True)
    (allegati_dir / f"{data_codice}.md").write_text(testo, encoding="utf-8")

    return righe_indice(data_codice, urn, versione, snapshot_data, docs, rel_path)


def aggiorna_indice(rows: list[dict], parquet: Path) -> int:
    """Merge accumulativo per `data_codice` (sostituisce il gruppo)."""
    import pandas as pd

    nuovo = pd.DataFrame(rows)
    if parquet.exists():
        prev = pd.read_parquet(parquet)
        nuovo = pd.concat(
            [prev[~prev["data_codice"].isin(nuovo["data_codice"])], nuovo],
            ignore_index=True,
        )
    nuovo.to_parquet(parquet, index=False)
    return len(nuovo)
