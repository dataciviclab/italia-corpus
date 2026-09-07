"""Test per lab_tools.akn_parser."""

import xml.etree.ElementTree as ET

import pytest

from lab_tools.akn_parser import (
    AknFrontmatter,
    akn_xml_to_markdown,
    extract_frontmatter,
    format_frontmatter,
    href_to_urn,
    resolve_ref,
)

AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"


def _make_xml(
    tipo: str = "LEGGE",
    numero: str = "1",
    data: str = "2024-01-01",
    titolo: str = "Titolo di test",
    urn: str = "urn:nir:stato:legge:2024-01-01;1",
    codice: str = "024G00001",
    vigente: bool = True,
    body_text: str = "Art. 1. Testo.",
) -> str:
    repeal = "" if vigente else '<eventRef type="repeal" />'
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<act xmlns="{AKN_NS}" xmlns:eli="http://data.europa.eu/eli/ontology#">
  <preface>
    <docType>{tipo}</docType>
    <docNumber>{numero}</docNumber>
    <docDate date="{data}">{data}</docDate>
    <docTitle>{titolo}</docTitle>
  </preface>
  <meta>
    <identification>
      <FRBRalias name="urn:nir" value="{urn}"/>
    </identification>
    <proprietary>
      <eli:id_local>{codice}</eli:id_local>
    </proprietary>
    <lifecycle>
      {repeal}
    </lifecycle>
  </meta>
  <body>
    <article>
      <num>Art. 1.</num>
      <p>{body_text}</p>
    </article>
  </body>
</act>"""


# ── extract_frontmatter ─────────────────────────────────────────────


class TestExtractFrontmatter:

    def test_basic(self):
        xml = _make_xml()
        root = ET.fromstring(xml)
        fm = extract_frontmatter(root)
        assert fm.tipo == "LEGGE"
        assert fm.numero == "1"
        assert fm.data == "2024-01-01"
        assert fm.titolo == "Titolo di test"
        assert fm.urn == "urn:nir:stato:legge:2024-01-01;1"
        assert fm.codice_redazionale == "024G00001"
        assert fm.vigente is True

    def test_abrogato(self):
        xml = _make_xml(vigente=False)
        root = ET.fromstring(xml)
        fm = extract_frontmatter(root)
        assert fm.vigente is False

    def test_missing_fields(self):
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<act xmlns="{AKN_NS}">
  <preface></preface>
  <meta></meta>
  <body></body>
</act>"""
        root = ET.fromstring(xml)
        fm = extract_frontmatter(root)
        assert fm.tipo is None
        assert fm.numero is None
        assert fm.vigente is True  # no repeal events


# ── format_frontmatter ──────────────────────────────────────────────


class TestFormatFrontmatter:

    def test_roundtrip(self):
        fm = AknFrontmatter(
            tipo="DECRETO LEGISLATIVO",
            numero="45",
            data="2020-03-15",
            titolo="Titolo con \"virgolette\"",
            urn="urn:nir:stato:decreto.legislativo:2020-03-15;45",
            codice_redazionale="020G01234",
            vigente=True,
        )
        text = format_frontmatter(fm)
        assert text.startswith("---\n")
        assert text.endswith("---\n\n")
        assert 'tipo: DECRETO LEGISLATIVO' in text
        assert 'titolo: "Titolo con \\"virgolette\\""' in text
        assert "vigente: true" in text

    def test_vigente_false(self):
        fm = AknFrontmatter(
            tipo="LEGGE", numero="1", data="2020-01-01",
            titolo="T", urn=None, codice_redazionale=None, vigente=False,
        )
        text = format_frontmatter(fm)
        assert "vigente: false" in text


# ── href_to_urn ─────────────────────────────────────────────────────


class TestHrefToUrn:

    def test_urn_nir_passthrough(self):
        assert href_to_urn("urn:nir:stato:legge:2024-01-01;1") == "urn:nir:stato:legge:2024-01-01;1"

    def test_akn_path(self):
        result = href_to_urn("/akn/it/act/decreto.legislativo/stato/2020-03-15/45")
        assert result == "urn:nir:stato:decreto.legislativo:2020-03-15;45"

    def test_non_akn_returns_none(self):
        assert href_to_urn("https://example.com") is None

    def test_short_path_returns_none(self):
        assert href_to_urn("/akn/it/act") is None


# ── resolve_ref ─────────────────────────────────────────────────────


class TestResolveRef:

    def test_internal_ref(self):
        urn_index = {"urn:nir:stato:legge:2024-01-01;1": "Leggi/2024-01-01.md"}
        result = resolve_ref(
            "urn:nir:stato:legge:2024-01-01;1", "Legge 1/2024",
            urn_index, "DL/attuazione.md",
        )
        assert "[Legge 1/2024]" in result
        assert "normattiva.it" not in result

    def test_external_ref(self):
        urn_index = {}
        result = resolve_ref(
            "urn:nir:stato:legge:2024-01-01;1", "Legge 1/2024",
            urn_index, "DL/attuazione.md",
        )
        assert "normattiva.it" in result
        assert "[Legge 1/2024]" in result

    def test_empty_href(self):
        assert resolve_ref("", "label", {}, "path.md") == "label"


# ── akn_xml_to_markdown (integration) ──────────────────────────────


class TestAknXmlToMarkdown:

    def test_full_conversion(self):
        xml = _make_xml(body_text="Testo dell'articolo.")
        urn_index = {}
        fm, md = akn_xml_to_markdown(xml, urn_index, "test.md")
        assert fm.tipo == "LEGGE"
        assert fm.vigente is True
        assert md.startswith("---\n")
        assert "tipo: LEGGE" in md
        assert "Art. 1." in md
        assert "Testo dell'articolo." in md

    def test_with_internal_ref(self):
        xml = _make_xml(body_text="Come previsto dalla legge.")
        urn_index = {"urn:nir:stato:legge:2020-01-01;1": "Leggi/2020.md"}
        # Add a ref element to the body
        xml = xml.replace(
            "<p>Come previsto dalla legge.</p>",
            '<p>Come previsto dalla <ref href="urn:nir:stato:legge:2020-01-01;1">legge</ref>.</p>',
        )
        fm, md = akn_xml_to_markdown(xml, urn_index, "DL/test.md")
        assert "[legge]" in md
        assert "normattiva.it" not in md  # internal, not external
