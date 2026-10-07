"""Test per lab_tools.akn_relations — estrazione relazioni e metadati AKN."""

import xml.etree.ElementTree as ET

import pytest

from lab_tools.akn_relations import (
    _extract_eiv,
    extract_act_meta,
    extract_from_xml,
    extract_relations,
    href_to_urn,
)

AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"


def _xml_rich() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<act xmlns="{AKN_NS}" xmlns:eli="http://data.europa.eu/eli/ontology#">
  <preface>
    <docType>DECRETO LEGISLATIVO</docType>
    <docNumber>36</docNumber>
    <docDate date="2023-03-31">2023-03-31</docDate>
    <docTitle>Codice contratti pubblici</docTitle>
  </preface>
  <meta>
    <identification>
      <FRBRalias name="urn:nir" value="urn:nir:stato:decreto.legislativo:2023-03-31;36"/>
    </identification>
    <proprietary>
      <eli:id_local>23G00044</eli:id_local>
      <eli:version rdf:resource="gu:tables/versions#ORIGINAL"
                   xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>
      <eli:type_document rdf:resource="gu:tables/resource-type#DECRETO LEGISLATIVO"
                         xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>
    </proprietary>
    <lifecycle>
      <eventRef eId="eventRef_0" date="2023-03-31" source="ro1"/>
    </lifecycle>
    <analysis>
      <activeModifications>
        <textualMod eId="amod_0" type="repeal">
          <source href="urn:nir:stato:decreto.legislativo:2023-03-31;36#226"/>
          <destination href="urn:nir:stato:decreto.legislativo:2016-04-18;50#1"/>
          <new/>
        </textualMod>
        <textualMod eId="amod_1" type="insertion">
          <source href="urn:nir:stato:decreto.legislativo:2023-03-31;36#1"/>
          <destination href="urn:nir:stato:legge:2012-09-13;158#6"/>
          <new/>
        </textualMod>
      </activeModifications>
      <passiveModifications>
        <textualMod eId="pmod_0" type="insertion">
          <source href="urn:nir:stato:decreto.legge:2024-01-01;9#1"/>
          <destination href="urn:nir:stato:decreto.legislativo:2023-03-31;36#5"/>
          <new/>
        </textualMod>
      </passiveModifications>
    </analysis>
    <references>
      <original eId="ro1" href="/akn/it/act/DECRETO_LEGISLATIVO/stato/2023-03-31/36/!main"/>
      <passiveRef eId="rp1" href="/akn/it/act/DECRETO_LEGGE/stato/2024-01-01/9/!main"/>
    </references>
  </meta>
  <body>
    <article>
      <num>Art. 1.</num>
      <p>
        <ref href="urn:nir:stato:decreto.legislativo:2016-04-18;50">D.Lgs 50/2016</ref>
        e <ref href="/akn/it/act/LEGGE/stato/2012-09-13/158/!main">L. 158/2012</ref>.
      </p>
    </article>
  </body>
  <conclusions>
    <authorialNote eId="atn1" placement="bottom">
      Entrata in vigore del provvedimento: 01/04/2023
    </authorialNote>
  </conclusions>
</act>"""


class TestHrefToUrn:
    def test_urn_passthrough(self):
        assert href_to_urn("urn:nir:stato:legge:2020-01-01;1") == (
            "urn:nir:stato:legge:2020-01-01;1"
        )

    def test_akn_path(self):
        urn = href_to_urn("/akn/it/act/DECRETO_LEGISLATIVO/stato/2016-04-18/50/!main")
        assert urn == "urn:nir:stato:decreto.legislativo:2016-04-18;50"

    def test_fragment_stripped(self):
        urn = href_to_urn("urn:nir:stato:legge:2020-01-01;1#art_3")
        assert urn == "urn:nir:stato:legge:2020-01-01;1"

    def test_invalid(self):
        assert href_to_urn("") is None
        assert href_to_urn("/akn/it/other") is None


class TestExtractEiv:
    def test_eiv_basic(self):
        root = ET.fromstring(_xml_rich())
        assert _extract_eiv(root) == "2023-04-01"

    def test_eiv_absent(self):
        xml = _xml_rich().replace("Entrata in vigore del provvedimento: 01/04/2023", "x")
        root = ET.fromstring(xml)
        assert _extract_eiv(root) is None


class TestExtractRelations:
    def test_covers_origins(self):
        root = ET.fromstring(_xml_rich())
        rows = extract_relations(root)
        origins = {r["origin"] for r in rows}
        assert "ref" in origins
        assert "activeModification" in origins
        assert "passiveModification" in origins
        assert "references" in origins
        assert "eventRef" in origins

    def test_typed_mods(self):
        root = ET.fromstring(_xml_rich())
        rows = extract_relations(root)
        active = {(r["rel_type"], r["target_urn"]) for r in rows if r["origin"] == "activeModification"}
        assert ("repeal", "urn:nir:stato:decreto.legislativo:2016-04-18;50") in active
        assert ("insertion", "urn:nir:stato:legge:2012-09-13;158") in active

    def test_passive_inverted(self):
        root = ET.fromstring(_xml_rich())
        rows = extract_relations(root)
        passive = [r for r in rows if r["origin"] == "passiveModification"]
        assert passive
        assert passive[0]["fonte_urn"] == "urn:nir:stato:decreto.legge:2024-01-01;9"
        assert passive[0]["target_urn"] == "urn:nir:stato:decreto.legislativo:2023-03-31;36"

    def test_passive_ref(self):
        root = ET.fromstring(_xml_rich())
        rows = extract_relations(root)
        prefs = [r for r in rows if r["rel_type"] == "passiveRef"]
        assert len(prefs) == 1
        assert prefs[0]["target_urn"] == "urn:nir:stato:decreto.legge:2024-01-01;9"

    def test_citations_from_refs(self):
        root = ET.fromstring(_xml_rich())
        rows = extract_relations(root)
        cites = {r["target_urn"] for r in rows if r["origin"] == "ref"}
        assert "urn:nir:stato:decreto.legislativo:2016-04-18;50" in cites
        assert "urn:nir:stato:legge:2012-09-13;158" in cites


class TestExtractActMeta:
    def test_meta_fields(self):
        root = ET.fromstring(_xml_rich())
        meta = extract_act_meta(root)
        assert meta["fonte_urn"] == "urn:nir:stato:decreto.legislativo:2023-03-31;36"
        assert meta["fonte_codice"] == "23G00044"
        assert meta["eiv"] == "2023-04-01"
        assert meta["n_eventRef"] == 1
        assert meta["n_repeal_events"] == 0
        assert meta["n_active_mods"] == 2
        assert meta["mod_types"] == {"repeal": 1, "insertion": 1}
        assert meta["n_passive_ref"] == 1
        assert meta["has_workflow"] is False

    def test_repeal_event_counted(self):
        xml = _xml_rich().replace(
            '<eventRef eId="eventRef_0" date="2023-03-31" source="ro1"/>',
            '<eventRef eId="eventRef_0" date="2023-03-31" source="ro1"/>'
            '<eventRef eId="eventRef_1" type="repeal" date="2024-06-01" source="rp1"/>',
        )
        meta = extract_act_meta(ET.fromstring(xml))
        assert meta["n_eventRef"] == 2
        assert meta["n_repeal_events"] == 1


class TestExtractFromXml:
    def test_tuple_shape(self):
        relations, meta = extract_from_xml(_xml_rich())
        assert isinstance(relations, list) and relations
        assert meta is not None and meta["fonte_codice"] == "23G00044"

    @pytest.mark.contract
    def test_schema_stable(self):
        relations, meta = extract_from_xml(_xml_rich())
        assert set(relations[0]) >= {"fonte_urn", "target_urn", "rel_type", "origin"}
        assert set(meta) >= {"fonte_urn", "eiv", "mod_types", "n_refs"}
