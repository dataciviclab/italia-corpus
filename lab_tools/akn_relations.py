"""Estrae relazioni AKN strutturate e metadati atto da XML Akoma Ntoso.

Output (data/derived/):
- akn_relations.parquet — citazioni, modifiche tipizzate, passiveRef, eventRef
- akn_act_meta.parquet — una riga per atto (EIV, ELI, lifecycle, conteggi)

Non tocca la conversione markdown: va chiamato a fianco di akn_xml_to_markdown.

Uso CLI:
  python -m lab_tools.akn_relations --xml-dir PATH [--outdir PATH]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"
ELI_NS = "http://data.europa.eu/eli/ontology#"
NS = {"akn": AKN_NS, "eli": ELI_NS}

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUTDIR = REPO / "data" / "derived"

# EIV: "Entrata in vigore del provvedimento: 01/04/2023" (anche parziale)
RE_EIV = re.compile(
    r"entrata\s+in\s+vigore(?:\s+del\s+provvedimento)?\s*:?\s*"
    r"(\d{1,2}/\d{1,2}/\d{4})",
    re.IGNORECASE,
)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def href_to_urn(href: str) -> str | None:
    """Mapping href AKN o urn:nir a URN normalizzato (o None)."""
    if not href:
        return None
    path, _, _ = href.partition("#")
    if path.startswith("urn:nir:"):
        return path
    if not path.startswith("/akn/"):
        return None
    parts = path.strip("/").split("/")
    if len(parts) < 7 or parts[:3] != ["akn", "it", "act"]:
        return None
    act_type, authority, date, number = parts[3], parts[4], parts[5], parts[6]
    # AKN usa underscore nei tipi (DECRETO_LEGISLATIVO); URN:NIR usa punti
    urn_type = act_type.lower().replace("_", ".")
    urn_authority = authority.lower().replace("_", ".")
    return f"urn:nir:{urn_authority}:{urn_type}:{date};{number}"


def _child_urn(el: ET.Element, tag: str) -> str | None:
    child = el.find(f"akn:{tag}", NS)
    if child is None:
        return None
    return href_to_urn(child.get("href") or "")


def _eli_text(root: ET.Element, name: str) -> str | None:
    """Valore ELI da testo o attributo rdf:resource (short name dopo #)."""
    el = root.find(f".//eli:{name}", NS)
    if el is None:
        return None
    text = (el.text or "").strip()
    if text:
        return text
    for attr_key, attr_val in el.attrib.items():
        if _local(attr_key) == "resource" and attr_val:
            return attr_val.rsplit("#", 1)[-1]
    return None


def _extract_eiv(root: ET.Element) -> str | None:
    """Prima data EIV da authorialNote, normalizzata ISO (YYYY-MM-DD)."""
    for note in root.findall(".//akn:authorialNote", NS):
        text = "".join(note.itertext())
        m = RE_EIV.search(text)
        if m:
            raw = m.group(1)
            try:
                gg, mm, aaaa = raw.split("/")
                return f"{aaaa}-{int(mm):02d}-{int(gg):02d}"
            except ValueError:
                return raw
    return None


def extract_relations(root: ET.Element) -> list[dict[str, Any]]:
    """Righe relazione da un elemento AKN root.

    origin: ref | activeModification | passiveModification | references | eventRef
    """
    urn_el = root.find(".//akn:meta/akn:identification//akn:FRBRalias[@name='urn:nir']", NS)
    fonte_urn = urn_el.get("value") if urn_el is not None else None
    codice = _eli_text(root, "id_local")
    rows: list[dict[str, Any]] = []

    def _row(
        target_urn: str | None,
        rel_type: str,
        origin: str,
        detail: str = "",
        fonte_override: str | None = None,
    ) -> None:
        rows.append(
            {
                "fonte_urn": fonte_override if fonte_override is not None else fonte_urn,
                "fonte_codice": codice,
                "target_urn": target_urn,
                "rel_type": rel_type,
                "origin": origin,
                "detail": detail[:300],
            }
        )

    for rf in root.findall(".//akn:ref", NS):
        href = rf.get("href") or ""
        target = href_to_urn(href)
        if target:
            _row(target, "citation", "ref", href)

    for am in root.findall(".//akn:activeModifications", NS):
        for tm in am.iter():
            if _local(tm.tag) != "textualMod":
                continue
            rel = tm.get("type") or "modification"
            dest = _child_urn(tm, "destination")
            src = _child_urn(tm, "source")
            target = dest if dest and dest != fonte_urn else src
            if not target or target == fonte_urn:
                continue
            _row(target, rel, "activeModification", f"src={src};dest={dest}")

    for pm in root.findall(".//akn:passiveModifications", NS):
        for tm in pm.iter():
            if _local(tm.tag) != "textualMod":
                continue
            rel = tm.get("type") or "modification"
            dest = _child_urn(tm, "destination")
            src = _child_urn(tm, "source")
            # In passive: source = atto che interviene; destination = noi
            intervengono = src if src and src != fonte_urn else dest
            target = fonte_urn or dest
            if not intervengono or intervengono == fonte_urn:
                continue
            _row(
                target,
                rel,
                "passiveModification",
                f"src={src};dest={dest}",
                fonte_override=intervengono,
            )

    refsec = root.find(".//akn:references", NS)
    if refsec is not None:
        for child in refsec:
            kind = _local(child.tag)
            target = href_to_urn(child.get("href") or "")
            if not target or target == fonte_urn:
                continue
            rel = "passiveRef" if "passive" in kind.lower() else f"refsec:{kind}"
            _row(target, rel, "references", child.get("href") or "")

    for er in root.findall(".//akn:eventRef", NS):
        etype = (er.get("type") or "version").lower()
        href = er.get("source") or ""
        _row(href_to_urn(href), f"event:{etype}", "eventRef",
             f"date={er.get('date')};eId={er.get('eId')}")

    return rows


def extract_act_meta(root: ET.Element) -> dict[str, Any]:
    """Metadati atto da AKN (identità, EIV, ELI, lifecycle, conteggi)."""
    urn_el = root.find(".//akn:meta/akn:identification//akn:FRBRalias[@name='urn:nir']", NS)
    fonte_urn = urn_el.get("value") if urn_el is not None else None
    codice = _eli_text(root, "id_local")
    eiv = _extract_eiv(root)

    events = []
    for er in root.findall(".//akn:eventRef", NS):
        events.append(
            {
                "eId": er.get("eId"),
                "type": (er.get("type") or "").lower() or None,
                "date": er.get("date"),
                "source": er.get("source"),
            }
        )
    n_repeal = sum(1 for e in events if e.get("type") == "repeal")

    tmods = [
        tm.get("type") or "unknown"
        for am in root.findall(".//akn:activeModifications", NS)
        for tm in am.iter()
        if _local(tm.tag) == "textualMod"
    ]
    mod_types = dict(Counter(tmods))

    return {
        "fonte_urn": fonte_urn,
        "fonte_codice": codice,
        "eiv": eiv,
        "eli_version": _eli_text(root, "version"),
        "eli_type_document": _eli_text(root, "type_document"),
        "eli_date_document": _eli_text(root, "date_document"),
        "n_refs": len(root.findall(".//akn:ref", NS)),
        "n_eventRef": len(events),
        "n_repeal_events": n_repeal,
        "n_active_mods": len(tmods),
        "mod_types": mod_types,
        "mod_types_json": json.dumps(mod_types, ensure_ascii=False),
        "has_workflow": root.find(".//akn:workflow", NS) is not None,
        "n_passive_ref": len(
            [
                c
                for refsec in root.findall(".//akn:references", NS)
                for c in refsec
                if "passive" in _local(c.tag).lower()
            ]
        ),
        "event_types": [e.get("type") for e in events if e.get("type")],
        "event_types_json": json.dumps(
            [e.get("type") for e in events if e.get("type")], ensure_ascii=False
        ),
    }


def extract_from_xml(content: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Parse XML di un atto → (relations, act_meta)."""
    root = ET.fromstring(content)
    meta = extract_act_meta(root)
    relations = extract_relations(root)
    return relations, meta


def collect_from_xml_dir(xml_dir: Path) -> tuple[list[dict], list[dict]]:
    """Estrai relations + metadati da tutti gli .xml sotto xml_dir."""
    rel_rows: list[dict] = []
    meta_rows: list[dict] = []
    for path in sorted(xml_dir.rglob("*.xml")):
        try:
            content = path.read_text("utf-8", errors="replace")
            relations, meta = extract_from_xml(content)
        except ET.ParseError:
            continue
        rel_rows.extend(relations)
        if meta and meta.get("fonte_urn"):
            meta["fonte_file"] = path.name
            meta_rows.append(meta)
    return rel_rows, meta_rows


def write_parquets(rel_rows: list[dict], meta_rows: list[dict], outdir: Path) -> tuple[Path, Path]:
    """Scrive akn_relations.parquet e akn_act_meta.parquet."""
    import pandas as pd

    outdir.mkdir(parents=True, exist_ok=True)
    rel_path = outdir / "akn_relations.parquet"
    meta_path = outdir / "akn_act_meta.parquet"

    rel_cols = [
        "fonte_urn", "fonte_codice", "target_urn",
        "rel_type", "origin", "detail",
    ]
    meta_cols = [
        "fonte_urn", "fonte_codice", "fonte_file", "eiv",
        "eli_version", "eli_type_document", "eli_date_document",
        "n_refs", "n_eventRef", "n_repeal_events", "n_active_mods",
        "mod_types_json", "has_workflow", "n_passive_ref", "event_types_json",
    ]

    pd.DataFrame(rel_rows, columns=rel_cols).to_parquet(rel_path, index=False)
    pd.DataFrame(meta_rows, columns=meta_cols).to_parquet(meta_path, index=False)
    return rel_path, meta_path


def stage_akn_rows(rel_rows: list[dict], meta_rows: list[dict], stage_dir: Path, collection: str) -> None:
    """Scrive staging JSONL per collezione (sopravvive a errori di merge)."""
    import json

    stage_dir.mkdir(parents=True, exist_ok=True)
    safe = collection.replace(" ", "_")
    rel_path = stage_dir / f"{safe}__relations.jsonl"
    meta_path = stage_dir / f"{safe}__meta.jsonl"
    with rel_path.open("w", encoding="utf-8") as fh:
        for row in rel_rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    with meta_path.open("w", encoding="utf-8") as fh:
        for row in meta_rows:
            # dict event_types/mod_types -> json string per compat parquet
            r = dict(row)
            if isinstance(r.get("mod_types"), dict):
                r["mod_types_json"] = json.dumps(r["mod_types"], ensure_ascii=False)
            else:
                r.setdefault("mod_types_json", None)
            if isinstance(r.get("event_types"), list):
                r["event_types_json"] = json.dumps(r["event_types"], ensure_ascii=False)
            else:
                r.setdefault("event_types_json", None)
            r.pop("mod_types", None)
            r.pop("event_types", None)
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_staged_akn(stage_dir: Path) -> tuple[list[dict], list[dict]]:
    """Ricostruisce relations/meta da JSONL di staging."""
    import json

    rel_rows: list[dict] = []
    meta_rows: list[dict] = []
    if not stage_dir.exists():
        return rel_rows, meta_rows
    for rel_path in sorted(stage_dir.glob("*__relations.jsonl")):
        with rel_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rel_rows.append(json.loads(line))
    for meta_path in sorted(stage_dir.glob("*__meta.jsonl")):
        with meta_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    meta_rows.append(json.loads(line))
    return rel_rows, meta_rows


REL_KEY = ["fonte_urn", "target_urn", "rel_type", "origin"]
META_KEY = "fonte_urn"


def _upsert_by_key(
    old: "pd.DataFrame",
    new: "pd.DataFrame",
    keys: list[str],
    cols: list[str],
) -> "pd.DataFrame":
    """Rimuove da old le chiavi presenti in new e concatena new (keep last)."""
    import pandas as pd

    for col in cols:
        if col not in old.columns:
            old[col] = None
        if col not in new.columns:
            new[col] = None
    old = old[cols].copy()
    new = new[cols].copy()
    if new.empty:
        return old
    if old.empty:
        return new.drop_duplicates(subset=keys, keep="last")
    new_keys = set(map(tuple, new[keys].astype(str).itertuples(index=False)))
    keep_mask = ~old[keys].astype(str).apply(
        lambda row: tuple(row) in new_keys, axis=1
    )
    combined = pd.concat([old.loc[keep_mask], new], ignore_index=True)
    return combined.drop_duplicates(subset=keys, keep="last")


def merge_akn_artifacts(
    rel_rows: list[dict],
    meta_rows: list[dict],
    outdir: Path,
) -> tuple[Path, Path]:
    """Merge parziale nel parquet esistente (fetch --only non sovrascrive il resto).

    - relations: upsert per (fonte_urn, target_urn, rel_type, origin)
    - acts: upsert per fonte_urn (l'ultimo fetch vince per atto)
    """
    import pandas as pd

    rel_path = outdir / "akn_relations.parquet"
    meta_path = outdir / "akn_act_meta.parquet"
    rel_cols = [
        "fonte_urn", "fonte_codice", "target_urn",
        "rel_type", "origin", "detail",
    ]
    meta_cols = [
        "fonte_urn", "fonte_codice", "fonte_file", "eiv",
        "eli_version", "eli_type_document", "eli_date_document",
        "n_refs", "n_eventRef", "n_repeal_events", "n_active_mods",
        "mod_types_json", "has_workflow", "n_passive_ref", "event_types_json",
    ]

    new_rel = pd.DataFrame(rel_rows, columns=rel_cols)
    new_meta = pd.DataFrame(meta_rows, columns=meta_cols)

    old_rel = pd.read_parquet(rel_path) if rel_path.exists() else pd.DataFrame(columns=rel_cols)
    old_meta = pd.read_parquet(meta_path) if meta_path.exists() else pd.DataFrame(columns=meta_cols)

    combined = _upsert_by_key(old_rel, new_rel, REL_KEY, rel_cols)
    combined_meta = _upsert_by_key(old_meta, new_meta, [META_KEY], meta_cols)

    outdir.mkdir(parents=True, exist_ok=True)
    combined[rel_cols].to_parquet(rel_path, index=False)
    combined_meta[meta_cols].to_parquet(meta_path, index=False)
    return rel_path, meta_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Estrai relazioni AKN da XML")
    parser.add_argument("--xml-dir", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument(
        "--merge",
        action="store_true",
       description="Merge con parquet esistenti invece di sovrascrivere",
    )
    args = parser.parse_args()

    rel_rows, meta_rows = collect_from_xml_dir(args.xml_dir)
    if args.merge:
        rel_path, meta_path = merge_akn_artifacts(rel_rows, meta_rows, args.outdir)
    else:
        rel_path, meta_path = write_parquets(rel_rows, meta_rows, args.outdir)
    print(f"relations: {len(rel_rows)} -> {rel_path}")
    print(f"acts: {len(meta_rows)} -> {meta_path}")
    if meta_rows:
        eiv_n = sum(1 for m in meta_rows if m.get("eiv"))
        mods = Counter(t for m in meta_rows for t in (m.get("mod_types") or {}))
        print(f"atti con EIV: {eiv_n}/{len(meta_rows)}")
        print(f"mod_types totals: {dict(mods)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
