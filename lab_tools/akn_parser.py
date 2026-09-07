"""Parse Akoma Ntoso XML e produci frontmatter YAML + body markdown.

Adattato da ahmeabd/italia-corpus-script (MIT).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"
ELI_NS = "http://data.europa.eu/eli/ontology#"
NS = {"akn": AKN_NS, "eli": ELI_NS}

NORMATTIVA_URI_RES = "https://www.normattiva.it/uri-res/N2Ls"


@dataclass(frozen=True)
class AknFrontmatter:
    tipo: str | None
    numero: str | None
    data: str | None
    titolo: str | None
    urn: str | None
    codice_redazionale: str | None
    vigente: bool


# ── Helpers ──────────────────────────────────────────────────────────

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    text = "".join(el.itertext()).strip()
    return text or None


def _find_one(root: ET.Element, path: str) -> ET.Element | None:
    return root.find(path, NS)


def _camel_to_dots(value: str) -> str:
    import re
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1.\2", value)
    return value.lower()


_HREF_ENCODE = {
    " ": "%20", "(": "%28", ")": "%29", "[": "%5B", "]": "%5D",
    "#": "%23", '"': "%22", "<": "%3C", ">": "%3E", "\\": "%5C",
}


def _encode_href(href: str) -> str:
    return "".join(_HREF_ENCODE.get(c, c) for c in href)


# ── Frontmatter extraction ───────────────────────────────────────────

def extract_frontmatter(root: ET.Element) -> AknFrontmatter:
    """Estrae i campi frontmatter da un documento Akoma Ntoso."""
    tipo = _text(_find_one(root, ".//akn:preface//akn:docType"))
    numero = _text(_find_one(root, ".//akn:preface//akn:docNumber"))

    doc_date = _find_one(root, ".//akn:preface//akn:docDate")
    data = doc_date.get("date") if doc_date is not None else None

    titolo_raw = _text(_find_one(root, ".//akn:preface//akn:docTitle"))
    titolo = " ".join(titolo_raw.split()) if titolo_raw else None

    urn_el = _find_one(
        root, ".//akn:meta/akn:identification//akn:FRBRalias[@name='urn:nir']"
    )
    urn = urn_el.get("value") if urn_el is not None else None

    codice_el = _find_one(root, ".//akn:meta/akn:proprietary//eli:id_local")
    codice_redazionale = _text(codice_el)

    repeal_events = root.findall(
        ".//akn:meta/akn:lifecycle//akn:eventRef[@type='repeal']", NS
    )
    vigente = len(repeal_events) == 0

    return AknFrontmatter(
        tipo=tipo, numero=numero, data=data, titolo=titolo,
        urn=urn, codice_redazionale=codice_redazionale, vigente=vigente,
    )


def format_frontmatter(fm: AknFrontmatter) -> str:
    """Serializza il frontmatter in YAML tra marker ---."""
    lines = ["---"]
    if fm.tipo is not None:
        lines.append(f"tipo: {fm.tipo}")
    if fm.numero is not None:
        lines.append(f"numero: {fm.numero}")
    if fm.data is not None:
        lines.append(f"data: {fm.data}")
    if fm.titolo is not None:
        escaped = fm.titolo.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'titolo: "{escaped}"')
    if fm.urn is not None:
        lines.append(f"urn: {fm.urn}")
    if fm.codice_redazionale is not None:
        lines.append(f"codice_redazionale: {fm.codice_redazionale}")
    lines.append(f"vigente: {'true' if fm.vigente else 'false'}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


# ── Reference resolution ─────────────────────────────────────────────

def href_to_urn(href: str) -> str | None:
    """Mapping href (urn:nir o /akn/...) a identificativo urn:nir."""
    path, _, _ = href.partition("#")
    if path.startswith("urn:nir:"):
        return path
    if not path.startswith("/akn/"):
        return None
    parts = path.strip("/").split("/")
    if len(parts) < 7 or parts[:3] != ["akn", "it", "act"]:
        return None
    act_type, authority, date, number = parts[3], parts[4], parts[5], parts[6]
    urn_type = _camel_to_dots(act_type)
    urn_authority = authority.lower().replace("_", ".")
    return f"urn:nir:{urn_authority}:{urn_type}:{date};{number}"


def _normattiva_url(href: str) -> str:
    urn, _, fragment = href.partition("#")
    if not urn.startswith("urn:nir:"):
        derived = href_to_urn(href)
        if derived:
            urn = derived
    url = f"{NORMATTIVA_URI_RES}?{urn}"
    if fragment:
        url = f"{url}#{fragment}"
    return url


def resolve_ref(href: str, label: str, urn_index: dict[str, str], source_path: str) -> str:
    """Converte un <ref> href in un link markdown."""
    if not href:
        return label
    urn, _, fragment = href.partition("#")
    lookup_urn = href_to_urn(href) or urn
    target = urn_index.get(lookup_urn)
    if target:
        import os
        source_dir = os.path.dirname(source_path)
        start = source_dir or "."
        rel = os.path.relpath(target, start=start).replace(os.sep, "/")
        rel = _encode_href(rel)
        return f"[{label}]({rel})"
    return f"[{label}]({_normattiva_url(href)})"


# ── Inline rendering ─────────────────────────────────────────────────

def _render_inline(el: ET.Element, urn_index: dict[str, str], source_path: str) -> str:
    tag = _local(el.tag)
    if tag == "ref":
        href = el.get("href") or ""
        label = _text(el) or href
        if href:
            return resolve_ref(href, label, urn_index, source_path)
        return label

    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        parts.append(_render_inline(child, urn_index, source_path))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts).strip()


# ── Block rendering ──────────────────────────────────────────────────

def _render_block(
    el: ET.Element, lines: list[str],
    urn_index: dict[str, str], source_path: str,
    heading_level: int = 2,
) -> None:
    tag = _local(el.tag)

    if tag == "article":
        num_el = el.find(f"{{{AKN_NS}}}num")
        heading_el = el.find(f"{{{AKN_NS}}}heading")
        num = _text(num_el)
        heading = _text(heading_el)
        title = " — ".join(part for part in (num, heading) if part)
        if title:
            lines.append(f"{'#' * heading_level} {title}")
            lines.append("")
        for child in el:
            if _local(child.tag) not in {"num", "heading"}:
                _render_block(child, lines, urn_index, source_path, heading_level + 1)
        return

    if tag in {"paragraph", "content", "p", "blockList", "item", "point"}:
        text = _render_inline(el, urn_index, source_path) if tag == "p" else None
        if text:
            lines.append(text)
            lines.append("")
            return
        for child in el:
            _render_block(child, lines, urn_index, source_path, heading_level)
        return

    if tag in {"section", "chapter", "part", "division", "title", "subtitle"}:
        heading_el = el.find(f"{{{AKN_NS}}}heading")
        heading = _text(heading_el)
        if heading:
            lines.append(f"{'#' * min(heading_level, 6)} {heading}")
            lines.append("")
        for child in el:
            if heading_el is not None and child is heading_el:
                continue
            _render_block(child, lines, urn_index, source_path, heading_level + 1)
        return

    text = _render_inline(el, urn_index, source_path)
    if text and tag not in {"meta", "preface", "body", "preamble", "conclusions", "act"}:
        lines.append(text)
        lines.append("")
        return

    for child in el:
        _render_block(child, lines, urn_index, source_path, heading_level)


# ── Main entry ───────────────────────────────────────────────────────

def body_to_markdown(root: ET.Element, urn_index: dict[str, str], source_path: str) -> str:
    """Converte preamble, body e conclusions in markdown."""
    lines: list[str] = []
    for section in ("preamble", "body", "conclusions"):
        section_el = _find_one(root, f".//akn:{section}")
        if section_el is not None:
            _render_block(section_el, lines, urn_index, source_path)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def akn_xml_to_markdown(
    content: str,
    urn_index: dict[str, str],
    source_path: str,
) -> tuple[AknFrontmatter, str]:
    """Parse AKN XML e restituisce (frontmatter, markdown_completo)."""
    root = ET.fromstring(content)
    fm = extract_frontmatter(root)
    body = body_to_markdown(root, urn_index, source_path)
    return fm, format_frontmatter(fm) + body
