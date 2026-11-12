"""Test per lab_tools.akn_relations — estrazione relazioni e metadati AKN."""

import xml.etree.ElementTree as ET

import pytest
from lab_tools.akn_relations import (
    REL_KEY,
    _extract_eiv,
    articolo_da_frammento,
    extract_act_meta,
    extract_from_xml,
    extract_relations,
    frammento,
    href_to_urn,
    locator_gap,
    locator_stats,
    merge_akn_artifacts,
)

AKN_NS = "http://docs.oasis-open.org/legaldocml/ns/akn/3.0"

# Fragment osservati sul corpus 2026-11 (collezione abrogati): num → suffisso,
# `bis` attaccato o separato, eId con sezione, Tabelle/Allegati.
FORMATI_REALI = [
    ("1", "art_1"),
    ("Ordinamento-art. 6", "art_6"),
    ("art_47-com1-leta", "art_47-com1"),
    ("art_1bis-com3", "art_1-bis-com3"),
    ("art_840 octies", "art_840-octies"),
    ("art_47-bis", "art_47-bis"),
    ("Tabelle", None),
]


def _xml_formati_reali() -> str:
    """Un atto con i fragment reali: blinda la grammatica in CI."""
    mods = "\n".join(
        f"""        <textualMod eId="amod_{i}" type="insertion">
          <source href="urn:nir:stato:legge:2023-03-31;36#1"/>
          <destination href="urn:nir:stato:legge:2020-01-01;{100 + i}#{frag}"/>
        </textualMod>"""
        for i, (frag, _) in enumerate(FORMATI_REALI)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<act xmlns="{AKN_NS}">
  <meta>
    <identification>
      <FRBRalias name="urn:nir" value="urn:nir:stato:legge:2023-03-31;36"/>
    </identification>
    <analysis>
      <activeModifications>
{mods}
      </activeModifications>
    </analysis>
  </meta>
  <body>
    <article>
      <num>Art. 1.</num>
      <p><ref href="urn:nir:stato:legge:2021-01-01;7#art_47-ter">rinvio</ref></p>
    </article>
  </body>
</act>"""


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


class TestLocator:
    """Fragment grezzo (`locator`) e articolo normalizzato (`articolo`, #142)."""

    @pytest.mark.parametrize(
        ("frag", "atteso"),
        [
            ("1", "art_1"),
            ("226", "art_226"),
            ("art_47-com1", "art_47-com1"),
            ("art_47-com1-leta", "art_47-com1"),
            ("art_13-com2", "art_13-com2"),
            ("Ordinamento-art. 6", "art_6"),
            ("Articolo 5", "art_5"),
            # suffissi che cambiano l'identità: non vanno persi
            ("art_47-bis", "art_47-bis"),
            ("art_47bis", "art_47-bis"),
            ("art_1bis-com3", "art_1-bis-com3"),
            ("art_840 octies", "art_840-octies"),
            ("Regolamento-art. 10-bis", "art_10-bis"),
            ("art_14vicies", "art_14-vicies"),
            ("art_47-bis-com1", "art_47-bis-com1"),
            # ordinali lunghi: `ter` non deve troncare `terdecies`
            ("art_5-terdecies", "art_5-terdecies"),
            ("art_5quaterdecies", "art_5-quaterdecies"),
            ("art_2-vicies", "art_2-vicies"),
            # coda sconosciuta: si torna all'articolo base, mai a un suffisso
            # sbagliato (`bisonte` non è `bis`)
            ("art_47-bisonte", "art_47"),
            # sotto-articolo: stesso articolo
            ("art_47-com4bis", "art_47-com4"),
            ("art_47-par2", "art_47"),
            ("art_47-com1-letb", "art_47-com1"),
            ("art_5", "art_5"),
            ("preambolo", None),
            ("allegato-1", None),
            ("", None),
            (None, None),
        ],
    )
    def test_articolo_da_frammento(self, frag, atteso):
        assert articolo_da_frammento(frag) == atteso

    def test_frammento(self):
        href = "urn:nir:stato:legge:2012-09-13;158#art_47-com1"
        assert frammento(href) == "art_47-com1"
        assert frammento("urn:nir:stato:legge:2012-09-13;158") is None
        assert frammento("") is None
        assert frammento(None) is None

    def test_modifiche_attive(self):
        """Il locator delle textualMod è l'articolo del lato target."""
        rows = extract_relations(ET.fromstring(_xml_rich()))
        active = {r["target_urn"]: r for r in rows if r["origin"] == "activeModification"}
        repeal = active["urn:nir:stato:decreto.legislativo:2016-04-18;50"]
        assert repeal["locator"] == "1"  # destination `...#1`
        assert repeal["articolo"] == "art_1"
        ins = active["urn:nir:stato:legge:2012-09-13;158"]
        assert ins["locator"] == "6"
        assert ins["articolo"] == "art_6"

    def test_modifica_passiva(self):
        """L'articolo modificato nell'atto è il `destination` della passive."""
        rows = extract_relations(ET.fromstring(_xml_rich()))
        passive = [r for r in rows if r["origin"] == "passiveModification"]
        assert passive[0]["locator"] == "5"  # destination `...#5`
        assert passive[0]["articolo"] == "art_5"

    def test_href_reale_art_n(self):
        """Gli href reali usano `#art_47-com1`, non solo l'eId numerico."""
        xml = _xml_rich().replace(
            "urn:nir:stato:legge:2012-09-13;158#6",
            "urn:nir:stato:legge:2012-09-13;158#art_47-com1-leta",
        )
        rows = extract_relations(ET.fromstring(xml))
        ins = [
            r for r in rows
            if r["origin"] == "activeModification" and r["rel_type"] == "insertion"
        ][0]
        assert ins["locator"] == "art_47-com1-leta"
        assert ins["articolo"] == "art_47-com1"


    def test_formati_reali_da_fixture(self):
        """I fragment reali (fixture) restano pinnati: num, sezione, suffissi."""
        rows = extract_relations(ET.fromstring(_xml_formati_reali()))
        got = {
            r["target_urn"]: (r["locator"], r["articolo"])
            for r in rows
            if r["origin"] == "activeModification"
        }
        for i, (frag, art) in enumerate(FORMATI_REALI):
            urn = f"urn:nir:stato:legge:2020-01-01;{100 + i}"
            assert got[urn] == (frag, art), (frag, got[urn])

    def test_citazione_con_suffisso(self):
        """Anche le citazioni conservano il suffisso (l'LG lo perdeva)."""
        rows = extract_relations(ET.fromstring(_xml_formati_reali()))
        cite = [r for r in rows if r["origin"] == "ref"][0]
        assert (cite["locator"], cite["articolo"]) == ("art_47-ter", "art_47-ter")
    def test_frammento_path_akn(self):
        """Le textualMod usano il sotto-elemento del path (`~art_...`), non `#`."""
        href = (
            "/akn/it/act/decreto_del_presidente_della_repubblica/stato/1998-03-10/76"
            "/ita@2025-01-22/!main/~art_8-ter__para_3"
        )
        assert frammento(href) == "art_8-ter__para_3"
        assert articolo_da_frammento(frammento(href)) == "art_8-ter"
        assert frammento(
            "/akn/it/act/x/stato/1998-04-30/217/ita@2025-01-23/!main/~art_1__para_1__point_c"
        ) == "art_1__para_1__point_c"
        assert frammento("/akn/it/act/LEGGE/stato/2012-09-13/158/!main") is None

    def test_repeal_con_path_akn(self):
        """Repeal/substitution: destination in sintassi path, locator valorizzato."""
        xml = _xml_rich().replace(
            '<destination href="urn:nir:stato:decreto.legislativo:2016-04-18;50#1"/>',
            '<destination href="/akn/it/act/decreto_legislativo/stato/2016-04-18/50'
            '/ita@2020-01-01/!main/~art_8-ter__para_3"/>',
        )
        rows = extract_relations(ET.fromstring(xml))
        repeal = [r for r in rows if r["rel_type"] == "repeal"][0]
        assert repeal["locator"] == "art_8-ter__para_3"
        assert repeal["articolo"] == "art_8-ter"
        assert repeal["target_urn"] == "urn:nir:stato:decreto.legislativo:2016-04-18;50"

    def test_citazioni_senza_fragment(self):
        """Le citazioni del fixture non hanno fragment: locator resta NULL."""
        rows = extract_relations(ET.fromstring(_xml_rich()))
        cites = [r for r in rows if r["origin"] == "ref"]
        assert cites and all(r["locator"] is None for r in cites)
        assert all(r["articolo"] is None for r in cites)


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
    def test_contesto_ref_dal_paragrafo(self):
        """Il contesto del <ref> è il paragrafo che lo contiene (non 'akn:ref')."""
        relations, _ = extract_from_xml(_xml_rich())
        cit = [r for r in relations if r["origin"] == "ref"]
        assert cit, "nessuna citazione ref nel fixture"
        assert all(r["contesto"] for r in cit), "contesto vuoto sui ref"
        assert any("D.Lgs 50/2016" in r["contesto"] for r in cit), cit[0]["contesto"]

    def test_contesto_assente_su_modifiche(self):
        """Le modifiche tipizzate non hanno un paragrafo: contesto vuoto."""
        relations, _ = extract_from_xml(_xml_rich())
        mods = [r for r in relations if r["origin"] == "activeModification"]
        assert mods and all(r["contesto"] == "" for r in mods)

    def test_tuple_shape(self):
        relations, meta = extract_from_xml(_xml_rich())
        assert isinstance(relations, list) and relations
        assert meta is not None and meta["fonte_codice"] == "23G00044"

    @pytest.mark.contract
    def test_schema_stable(self):
        relations, meta = extract_from_xml(_xml_rich())
        assert set(relations[0]) >= {"fonte_urn", "target_urn", "rel_type", "origin"}
        assert set(meta) >= {"fonte_urn", "eiv", "mod_types", "n_refs"}


class TestMergeNormalizza:
    def test_vecchi_target_a_trattino_normalizzati(self, tmp_path):
        """Le collezioni invariate restano nel parquet: il merge le normalizza.

        Senza questo, il fix di `href_to_urn` vale solo per le collezioni
        riprocessate e i target `decreto-legge` delle altre restano a
        trattino (15.637 righe sul corpus 2026-11).
        """
        import pandas as pd

        old = pd.DataFrame(
            [
                {
                    "fonte_urn": "urn:nir:stato:legge:2022-12-29;197",
                    "fonte_codice": None,
                    "target_urn": "urn:nir:stato:decreto-legge:2005-09-30;203",
                    "rel_type": "repeal",
                    "origin": "activeModification",
                    "detail": "",
                    "contesto": "",
                }
            ]
        )
        old.to_parquet(tmp_path / "akn_relations.parquet", index=False)

        merge_akn_artifacts([], [], tmp_path)

        got = pd.read_parquet(tmp_path / "akn_relations.parquet")
        assert got.iloc[0]["target_urn"] == (
            "urn:nir:stato:decreto.legge:2005-09-30;203"
        )

    def test_vecchia_e_nuova_collassano(self, tmp_path):
        """Vecchia riga a trattino + nuova canonica → una sola riga (la nuova)."""
        import pandas as pd

        old = pd.DataFrame(
            [
                {
                    "fonte_urn": "urn:nir:stato:legge:2022-12-29;197",
                    "fonte_codice": None,
                    "target_urn": "urn:nir:stato:decreto-legge:2005-09-30;203",
                    "rel_type": "repeal",
                    "origin": "activeModification",
                    "detail": "vecchia",
                    "contesto": "",
                }
            ]
        )
        old.to_parquet(tmp_path / "akn_relations.parquet", index=False)
        new = [
            {
                "fonte_urn": "urn:nir:stato:legge:2022-12-29;197",
                "fonte_codice": None,
                "target_urn": "urn:nir:stato:decreto.legge:2005-09-30;203",
                "rel_type": "repeal",
                "origin": "activeModification",
                "detail": "nuova",
                "contesto": "",
            }
        ]
        merge_akn_artifacts(new, [], tmp_path)
        got = pd.read_parquet(tmp_path / "akn_relations.parquet")
        assert len(got) == 1
        assert got.iloc[0]["detail"] == "nuova"
        assert set(REL_KEY) <= set(got.columns)


class TestMergeLocator:
    """Il merge (#142) aggrega i locator e resta compatibile coi parquet vecchi."""

    @staticmethod
    def _riga(target="urn:nir:stato:legge:2012-09-13;158", locator=None, articolo=None):
        return {
            "fonte_urn": "urn:nir:stato:decreto.legislativo:2023-03-31;36",
            "fonte_codice": "23G00044",
            "target_urn": target,
            "rel_type": "insertion",
            "origin": "activeModification",
            "detail": "src=x;dest=y",
            "contesto": "",
            "locator": locator,
            "articolo": articolo,
        }

    def test_piu_articoli_aggregati(self, tmp_path):
        """Due modifiche allo stesso atto su articoli diversi → un locator list."""
        merge_akn_artifacts(
            [
                self._riga(locator="art_47", articolo="art_47"),
                self._riga(locator="art_3", articolo="art_3"),
            ],
            [],
            tmp_path,
        )
        import pandas as pd

        got = pd.read_parquet(tmp_path / "akn_relations.parquet")
        assert len(got) == 1
        assert got.iloc[0]["locator"] == "art_3,art_47"
        assert got.iloc[0]["articolo"] == "art_3,art_47"

    def test_parquet_vecchio_senza_colonne(self, tmp_path):
        """Un parquet pre-IC-B non ha locator/articolo: il merge lo tollera."""
        import pandas as pd

        pd.DataFrame(
            [
                {
                    "fonte_urn": "urn:nir:stato:legge:1990-08-07;241",
                    "fonte_codice": None,
                    "target_urn": "urn:nir:stato:legge:2012-09-13;158",
                    "rel_type": "citation",
                    "origin": "ref",
                    "detail": "vecchia",
                    "contesto": "",
                }
            ]
        ).to_parquet(tmp_path / "akn_relations.parquet", index=False)

        merge_akn_artifacts([self._riga(locator="art_6", articolo="art_6")], [], tmp_path)
        got = pd.read_parquet(tmp_path / "akn_relations.parquet")
        assert {"locator", "articolo"} <= set(got.columns)
        vecchia = got[got["fonte_urn"] == "urn:nir:stato:legge:1990-08-07;241"]
        # In parquet è NULL (DuckDB lo legge come NULL); pandas lo mostra NaN.
        assert pd.isna(vecchia.iloc[0]["locator"])

    def test_eventref_con_target_nullo_sopravvive(self, tmp_path):
        """Gli eventRef hanno `target_urn` NULL: il groupby non deve scartarli."""
        merge_akn_artifacts(
            [
                {
                    "fonte_urn": "urn:nir:stato:legge:1990-08-07;241",
                    "fonte_codice": None,
                    "target_urn": None,
                    "rel_type": "event:version",
                    "origin": "eventRef",
                    "detail": "",
                    "contesto": "",
                    "locator": None,
                    "articolo": None,
                }
            ],
            [],
            tmp_path,
        )
        import pandas as pd

        got = pd.read_parquet(tmp_path / "akn_relations.parquet")
        assert len(got) == 1
        assert got.iloc[0]["rel_type"] == "event:version"


class TestLocatorStats:
    """Diagnostica di copertura per collezione (fetch)."""

    def test_conteggio_per_rel_type(self):
        rows = [
            {"rel_type": "citation", "locator": "art_1"},
            {"rel_type": "citation", "locator": None},
            {"rel_type": "repeal", "locator": None},
            {"rel_type": "repeal", "locator": None},
        ]
        stats = locator_stats(rows)
        assert stats["citation"] == (2, 1)
        assert stats["repeal"] == (2, 0)

    def test_rel_type_mancante(self):
        assert locator_stats([{"locator": "art_1"}]) == {"?": (1, 1)}

    def test_gap_solo_relazioni_attese(self):
        """`event:version`/`passiveRef` non hanno articolo per costruzione."""
        stats = {
            "repeal": (20, 0),
            "event:version": (100, 0),
            "passiveRef": (100, 0),
            "citation": (20, 3),
            "insertion": (5, 0),  # sotto soglia
        }
        assert locator_gap(stats) == ["repeal"]


class TestMergeMetaFile:
    """Un file che cambia URN non deve lasciare due righe con lo stesso file."""

    def test_upsert_per_urn_dedup_per_file(self, tmp_path):
        import pandas as pd

        old = pd.DataFrame([
            {"fonte_urn": "urn:nir:stato:decreto.legislativo:2026-03-13;38",
             "fonte_codice": "26G00056",
             "fonte_file": "Decreti Legislativi/2026-03-27_26G00056_ORIGINALE_V0.xml",
             "eiv": None},
        ])
        old.to_parquet(tmp_path / "akn_act_meta.parquet", index=False)
        new = [
            {"fonte_urn": "urn:nir:stato:decreto.legislativo:2026-03-13;39",
             "fonte_codice": "26G00056",
             "fonte_file": "Decreti Legislativi/2026-03-27_26G00056_ORIGINALE_V0.xml",
             "eiv": "2026-05-02"},
        ]
        merge_akn_artifacts([], new, tmp_path)
        got = pd.read_parquet(tmp_path / "akn_act_meta.parquet")
        assert len(got) == 1
        assert got.iloc[0]["fonte_urn"].endswith(";39")
        assert got.iloc[0]["eiv"] == "2026-05-02"
