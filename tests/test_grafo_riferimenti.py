"""Test per lab_tools.grafo_riferimenti — estrazione link e risoluzione path."""

from pathlib import Path

import pytest
from lab_tools.grafo_riferimenti import (
    ESITO_DOMINIO_UE,
    ESITO_FUORI_PERIMETRO,
    ESITO_IN_CATALOGO,
    ESITO_IN_CORPUS,
    ESITO_SENZA_BERSAGLIO,
    _chiave_arco,
    _chiave_ue,
    _dedup_archi,
    _risolvi_bersaglio,
    _verifica_celex,
    _verifica_esiti,
    _verifica_invarianti,
    _verifica_pk_unica,
    dominio_urn,
    esito_bersaglio,
    estrai_link,
    estrai_link_con_contesto,
    risolvi_celex,
    risolvi_path,
)
from lab_tools.text_clean import pulisci_markup

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestEstraiLink:
    """Test per estrai_link(): estrazione link ../ dal body markdown."""

    def test_senza_link(self):
        body = "Testo senza link relativi."
        assert estrai_link(body) == []

    def test_link_singolo(self):
        body = "Vedi ../Decreti Legislativi/TU.md per dettagli."
        links = estrai_link(body)
        assert len(links) == 1
        assert "Decreti Legislativi/TU.md" in links[0]

    def test_link_multipli(self):
        body = (
            "Riferimenti: ../DL%20e%20leggi%20di%20conversione/LeggeX.md "
            "e ../Decreti%20Legislativi/DecretoY.md."
        )
        links = estrai_link(body)
        assert len(links) == 2

    def test_url_decode(self):
        body = "Vedi ../DL%20e%20leggi%20di%20conversione/Norma%20importante.md"
        links = estrai_link(body)
        assert len(links) == 1
        assert "DL e leggi di conversione" in links[0]
        assert "Norma importante" in links[0]

    def test_link_con_parentesi(self):
        """Link con %28 %29 (parentesi) nel nome file."""
        body = "Cfr ../Atti%20normativi%20abrogati%20%28in%20originale%29/Testo.md"
        links = estrai_link(body)
        assert len(links) == 1
        assert "Atti normativi abrogati (in originale)" in links[0]

    def test_body_vuoto(self):
        assert estrai_link("") == []

    def test_link_duplicato(self):
        """Stesso link appare due volte -> estrai_link le trova entrambe."""
        body = "Vedi ../Leggi/LeggeX.md. Rivedi ../Leggi/LeggeX.md."
        links = estrai_link(body)
        assert len(links) == 2
        assert links[0] == links[1]

    def test_no_falsi_positivi(self):
        """Link assoluti (http/https) non devono matchare."""
        body = "Vedi https://www.normattiva.it/uri-res/N2Ls e http://example.com"
        assert estrai_link(body) == []


class TestRisolviPath:
    """Test per risolvi_path(): path relativi a COLLEZIONI_ROOT.

    Formato parquet stabile: ``Collezione/file.md`` (sotto collezioni/,
    stessa forma di prima del move).
    """

    def test_risoluzione_semplice(self):
        """../Codici/TU.md da DL Proroghe/x.md."""
        link = "Codici/TU.md"
        current = Path("DL Proroghe") / "x.md"
        result = risolvi_path(link, current)
        assert result is not None
        assert str(result) == "Codici/TU.md"

    def test_risoluzione_subdir(self):
        """../Codici/Sub/Norma.md da DL Proroghe/x.md."""
        link = "Codici/Sub/Norma.md"
        current = Path("DL Proroghe") / "x.md"
        result = risolvi_path(link, current)
        assert result is not None
        assert str(result) == "Codici/Sub/Norma.md"

    def test_risoluzione_root_collezione(self):
        """../Leggi/Legge.md da Decreti Legislativi/x.md."""
        link = "Leggi/Legge.md"
        current = Path("Decreti Legislativi") / "x.md"
        result = risolvi_path(link, current)
        assert result is not None
        assert str(result) == "Leggi/Legge.md"

    def test_risoluzione_file_in_root(self):
        """File in root collezioni (raro) -> None per sicurezza."""
        link = "Altro/file.md"
        current = Path("file_nella_root.md")
        result = risolvi_path(link, current)
        assert result is None


class TestEstraiSuFixture:
    """Test di estrazione su un file fixture reale."""

    def test_fixture_con_celex(self):
        """Il fixture con_celex.md non ha link ../."""
        body = (FIXTURES / "con_celex.md").read_text("utf-8")
        links = estrai_link(body)
        assert links == []

    def test_fixture_frontmatter(self):
        """Il fixture con_celex_fm.md non ha link ../."""
        body = (FIXTURES / "con_celex_fm.md").read_text("utf-8")
        links = estrai_link(body)
        assert links == []


def _arco(fonte, bersaglio_path="", bersaglio_fn="", origine="akn", peso=1, collezione=""):
    """Arco minimo con i campi che compongono la PK del clean."""
    return {
        "fonte_filename": fonte,
        "fonte_collezione": collezione,
        "bersaglio_filename": bersaglio_fn or bersaglio_path,
        "bersaglio_path": bersaglio_path,
        "origine": origine,
        "peso": peso,
    }


class TestChiaveArco:
    """La chiave rispecchia la PK del clean (`clean.sql`)."""

    def test_akn_basename_usa_collezione(self):
        a = _arco("a.md", bersaglio_path="b.md", origine="akn", collezione="Leggi")
        assert _chiave_arco(a) == ("Leggi/a.md", "b.md", "akn", "citation")

    def test_regex_relpath(self):
        a = _arco("Leggi/a.md", bersaglio_path="Codici/b.md", origine="regex")
        assert _chiave_arco(a) == ("Leggi/a.md", "Codici/b.md", "regex", "citation")

    def test_regex_non_risolto_usa_il_link(self):
        """`bersaglio_path` vuoto → la PK usa `bersaglio_filename` (il link)."""
        a = _arco("Leggi/a.md", bersaglio_path="", bersaglio_fn="Altro/x.md", origine="regex")
        assert _chiave_arco(a) == ("Leggi/a.md", "Altro/x.md", "regex", "citation")

    def test_akn_fuori_corpus_usa_urn(self):
        """Citation AKN senza filename: la PK usa `bersaglio_urn`."""
        a = _arco("Leggi/a.md", bersaglio_path="", bersaglio_fn="", origine="akn")
        a["bersaglio_urn"] = "urn:nir:stato:legge:1990-08-07;241"
        assert _chiave_arco(a) == ("Leggi/a.md", "urn:nir:stato:legge:1990-08-07;241", "akn", "citation")


class TestDedupArchi:
    """Un arco per chiave; `peso` sommato."""

    def test_stessa_coppia_collassa_e_somma_peso(self):
        archi = [
            _arco("a.md", bersaglio_path="b.md"),
            _arco("a.md", bersaglio_path="b.md"),
        ]
        out = _dedup_archi(archi)
        assert len(out) == 1
        assert out[0]["peso"] == 2

    def test_origine_diversa_non_collassa(self):
        archi = [
            _arco("a.md", bersaglio_path="b.md", origine="akn"),
            _arco("a.md", bersaglio_path="b.md", origine="regex", peso=3),
        ]
        assert len(_dedup_archi(archi)) == 2

    def test_coppie_diverse_restano(self):
        archi = [
            _arco("a.md", bersaglio_path="b.md"),
            _arco("a.md", bersaglio_path="c.md"),
            _arco("x.md", bersaglio_path="b.md"),
        ]
        assert len(_dedup_archi(archi)) == 3

    def test_lista_vuota(self):
        assert _dedup_archi([]) == []


class TestVerificaPkUnica:
    """Invariante: dopo `_dedup_archi` la PK del clean è unica."""

    def test_unica_non_solleva(self):
        archi = [
            _arco("a.md", bersaglio_path="b.md", origine="akn"),
            _arco("a.md", bersaglio_path="b.md", origine="regex"),
            _arco("a.md", bersaglio_path="c.md", origine="akn"),
        ]
        _verifica_pk_unica(archi)  # non solleva

    def test_regex_non_risolti_distinti_non_collassano(self):
        """Regressione: due link non risolti diversi NON sono duplicati."""
        archi = [
            _arco("a.md", bersaglio_path="", bersaglio_fn="Altro/x.md", origine="regex"),
            _arco("a.md", bersaglio_path="", bersaglio_fn="Altro/y.md", origine="regex"),
        ]
        _verifica_pk_unica(archi)  # non solleva

    def test_dedup_rende_unica_anche_l_unione(self):
        """Regex non risolti + AKN alias: dopo il dedup la PK è unica."""
        archi = [
            _arco("a.md", bersaglio_path="", bersaglio_fn="Altro/x.md", origine="regex"),
            _arco("a.md", bersaglio_path="", bersaglio_fn="Altro/y.md", origine="regex"),
            _arco("a.md", bersaglio_path="b.md"),
            _arco("a.md", bersaglio_path="b.md"),
        ]
        _verifica_pk_unica(_dedup_archi(archi))  # non solleva

    def test_duplicato_solleva(self):
        archi = [
            _arco("a.md", bersaglio_path="b.md"),
            _arco("a.md", bersaglio_path="b.md"),
        ]
        with pytest.raises(AssertionError, match="dedup incompleto"):
            _verifica_pk_unica(archi)


class TestRisolviBersaglio:
    """Path esatto → altrimenti fallback per `data_codice`."""

    def test_path_esatto(self):
        file_set = {"Codici/2003-08-07_003G0227_ORIGINALE_V0.md"}
        bp, fn, risolto, via_id = _risolvi_bersaglio(
            "Codici/2003-08-07_003G0227_ORIGINALE_V0.md",
            Path("Leggi/x.md"),
            file_set,
            {},
        )
        assert risolto and not via_id
        assert bp == "Codici/2003-08-07_003G0227_ORIGINALE_V0.md"
        assert fn == "2003-08-07_003G0227_ORIGINALE_V0.md"

    def test_fallback_identita_su_nome_vecchio(self):
        """Il link punta all'ORIGINALE, il corpus ha solo la VIGENZA."""
        file_set = {"Codici/2003-08-07_003G0227_VIGENZA_2026-02-25_V0.md"}
        indice = {"2003-08-07_003G0227": "Codici/2003-08-07_003G0227_VIGENZA_2026-02-25_V0.md"}
        bp, fn, risolto, via_id = _risolvi_bersaglio(
            "2003-08-07_003G0227_ORIGINALE_V0.md",
            Path("Leggi/x.md"),
            file_set,
            indice,
        )
        assert risolto and via_id
        assert bp == "Codici/2003-08-07_003G0227_VIGENZA_2026-02-25_V0.md"
        assert fn == "2003-08-07_003G0227_VIGENZA_2026-02-25_V0.md"

    def test_nessuna_identita(self):
        bp, fn, risolto, via_id = _risolvi_bersaglio(
            "Altro/x.md", Path("Leggi/x.md"), set(), {}
        )
        assert not risolto and not via_id
        assert fn == "x.md"


class TestVerificaInvarianti:
    @staticmethod
    def _arco(fonte, bersaglio, origine="regex", risolto=True):
        from pathlib import PurePosixPath

        return {
            "fonte_filename": fonte,
            "bersaglio_filename": PurePosixPath(bersaglio).name,
            "bersaglio_path": bersaglio if risolto else "",
            "origine": origine,
            "risolto": risolto,
        }

    def test_pulito_non_solleva(self):
        archi = [self._arco("Leggi/a.md", "Codici/b.md")]
        _verifica_invarianti(archi, {"Leggi/a.md", "Codici/b.md"})  # non solleva

    def test_churn_solleva(self):
        """Molti bersagli non risolti = churn di filename."""
        archi = [self._arco("Leggi/a.md", f"Altro/x{i}.md", risolto=False) for i in range(60)]
        with pytest.raises(ValueError, match="possibile churn di filename"):
            _verifica_invarianti(archi, set())

    def test_pochi_bersagli_non_risolti_ammessi(self):
        archi = [self._arco("Leggi/a.md", f"Altro/x{i}.md", risolto=False) for i in range(5)]
        _verifica_invarianti(archi, set())  # 5 <= soglia

    def test_bersaglio_fantasma_solleva(self):
        archi = [self._arco("Leggi/a.md", "Codici/b.md")]
        with pytest.raises(ValueError, match="bersagli inesistenti"):
            _verifica_invarianti(archi, {"Leggi/a.md"})

    def test_fonte_fantasma_solleva(self):
        archi = [self._arco("Leggi/a.md", "Codici/b.md")]
        with pytest.raises(ValueError, match="fonte inesistente"):
            _verifica_invarianti(archi, {"Codici/b.md"})


class TestContestoAkn:
    """Regressione 2026-10-30: in CI il contesto AKN arriva come NaN (float).

    `nan or ""` è NaN (truthy) → `.strip()` esplodeva. Locale non si vedeva
    perché il parquet non aveva ancora la colonna.
    """

    def _parquet(self, tmp_path, contesto):
        import pandas as pd

        df = pd.DataFrame(
            [
                {
                    "fonte_urn": "urn:nir:stato:legge:2020-01-01;1",
                    "target_urn": "urn:nir:stato:legge:2019-01-01;2",
                    "rel_type": "citation",
                    "origin": "ref",
                    "detail": "href",
                    "contesto": contesto,
                }
            ]
        )
        df.to_parquet(tmp_path / "akn_relations.parquet")

    def test_contesto_nan_usa_segnaposto(self, tmp_path, monkeypatch):
        from lab_tools import grafo_riferimenti as g

        self._parquet(tmp_path, float("nan"))
        monkeypatch.setattr(g, "OUTDIR", tmp_path)
        mappa = {
            "urn:nir:stato:legge:2020-01-01;1": "Leggi/2020.md",
            "urn:nir:stato:legge:2019-01-01;2": "Leggi/2019.md",
        }
        archi = g._archi_da_akn_relations({}, mappa)
        assert archi, "nessun arco AKN prodotto"
        assert archi[0]["contesto"] == "akn:ref"
        assert archi[0]["clausola_lettura"] is None

    def test_contesto_testuale_classificato(self, tmp_path, monkeypatch):
        from lab_tools import grafo_riferimenti as g

        self._parquet(tmp_path, "al solo fine di facilitare la lettura delle norme")
        monkeypatch.setattr(g, "OUTDIR", tmp_path)
        mappa = {
            "urn:nir:stato:legge:2020-01-01;1": "Leggi/2020.md",
            "urn:nir:stato:legge:2019-01-01;2": "Leggi/2019.md",
        }
        archi = g._archi_da_akn_relations({}, mappa)
        assert archi[0]["clausola_lettura"] is True


class TestCitationFuoriCorpus:
    """Le citation AKN verso atti non nel corpus non si scartano (2026-11).

    Prima: `not t_fn → continue`, e ~19.700 bersagli / ~180.000 citazioni
    (incluse L. 241/1990 e L. 15/2005) sparivano dal grafo.
    """

    def _parquet(self, tmp_path, target_urns):
        import pandas as pd

        df = pd.DataFrame([
            {
                "fonte_urn": "urn:nir:stato:legge:2020-01-01;1",
                "target_urn": t,
                "rel_type": "citation",
                "origin": "ref",
                "detail": "href",
                "contesto": "",
            }
            for t in target_urns
        ])
        df.to_parquet(tmp_path / "akn_relations.parquet")

    MAPPA = {"urn:nir:stato:legge:2020-01-01;1": "Leggi/2020.md"}

    def test_bersaglio_fuori_corpus_emesso_con_urn(self, tmp_path, monkeypatch):
        from lab_tools import grafo_riferimenti as g

        self._parquet(tmp_path, ["urn:nir:stato:legge:1990-08-07;241"])
        monkeypatch.setattr(g, "OUTDIR", tmp_path)
        archi = g._archi_da_akn_relations({}, self.MAPPA)
        assert len(archi) == 1
        a = archi[0]
        assert a["risolto"] is False
        assert a["bersaglio_urn"] == "urn:nir:stato:legge:1990-08-07;241"
        assert a["bersaglio_filename"] == ""
        assert a["bersaglio_anno"] == 1990
        assert a["bersaglio_tipo"] == "legge"

    def test_anno_senza_giorno_mese_risolve(self, tmp_path, monkeypatch):
        from lab_tools import grafo_riferimenti as g

        self._parquet(tmp_path, ["urn:nir:stato:legge:2019;2"])
        monkeypatch.setattr(g, "OUTDIR", tmp_path)
        from lab_tools.urn import expand_index

        mappa = expand_index([
            ("urn:nir:stato:legge:2020-01-01;1", "Leggi/2020.md"),
            ("urn:nir:stato:legge:2019-01-10;2", "Leggi/2019.md"),
        ])
        archi = g._archi_da_akn_relations({}, mappa)
        assert len(archi) == 1
        assert archi[0]["risolto"] is True
        assert archi[0]["bersaglio_filename"] == "2019.md"
        assert archi[0]["bersaglio_urn"] == "urn:nir:stato:legge:2019;2"

    def test_due_fuori_corpus_restano_distinti(self, tmp_path, monkeypatch):
        """La PK non collassa gli unresolved dello stesso file (usa l'URN)."""
        from lab_tools import grafo_riferimenti as g

        self._parquet(
            tmp_path,
            [
                "urn:nir:stato:legge:1990-08-07;241",
                "urn:nir:stato:legge:2005-02-11;15",
            ],
        )
        monkeypatch.setattr(g, "OUTDIR", tmp_path)
        archi = g._archi_da_akn_relations({}, self.MAPPA)
        assert len(archi) == 2
        assert len({a["bersaglio_urn"] for a in archi}) == 2

    def test_bersaglio_canonicalizzato_dal_catalogo(self, tmp_path, monkeypatch):
        """La URN grezza viene risolta sulla forma canonica del catalogo.

        legal-graph fa join esatto su `nodes.id`: la normalizzazione vive qui,
        non nel compose.
        """
        from lab_tools import grafo_riferimenti as g

        self._parquet(tmp_path, ["urn:nir:stato:legge:1990;241"])
        monkeypatch.setattr(g, "OUTDIR", tmp_path)
        atti = {
            ("annual", "stato", "legge", "1990", "241"):
                "urn:nir:stato:legge:1990-08-07;241"
        }
        archi = g._archi_da_akn_relations({}, self.MAPPA, atti)
        assert archi[0]["bersaglio_urn"] == "urn:nir:stato:legge:1990-08-07;241"

    def test_senza_catalogo_resta_la_urn_grezza(self, tmp_path, monkeypatch):
        """`atti_index.parquet` assente (pipeline-core): nessun errore, URN grezza."""
        from lab_tools import grafo_riferimenti as g

        self._parquet(tmp_path, ["urn:nir:stato:legge:1990;241"])
        monkeypatch.setattr(g, "OUTDIR", tmp_path)
        archi = g._archi_da_akn_relations({}, self.MAPPA, None)
        assert archi[0]["bersaglio_urn"] == "urn:nir:stato:legge:1990;241"

    def test_bersaglio_canonico_con_chiave_piena(self, tmp_path, monkeypatch):
        """La chiave con data completa risolve i casi anno+numero ambigui.

        Es. due decreti con lo stesso numero nello stesso anno: la data
        disambigua e il tipo concatenato viene riportato alla forma dotted.
        """
        from lab_tools import grafo_riferimenti as g

        self._parquet(
            tmp_path,
            ["urn:nir:stato:decretodelpresidentedellarepubblica:1950-10-17;857"],
        )
        monkeypatch.setattr(g, "OUTDIR", tmp_path)
        atti = {
            ("full", "stato", "decretopresidenterepubblica", "1950-10-17", "857"):
                "urn:nir:stato:decreto.del.presidente.della.repubblica:1950-10-17;857"
        }
        archi = g._archi_da_akn_relations({}, self.MAPPA, atti)
        assert archi[0]["bersaglio_urn"] == (
            "urn:nir:stato:decreto.del.presidente.della.repubblica:1950-10-17;857"
        )

    def test_fonte_assente_saltata_conteggi_coerenti(self, tmp_path, monkeypatch):
        """Righe senza fonte si saltano; l'invariante di conteggio
        (skip + risolti + fuori corpus == righe) resta verificato.

        Il gate è stato perso nel rewrite che ha introdotto i nodi fuori
        corpus: senza, un `continue` non conteggiato passerebbe in silenzio.
        """
        import pandas as pd
        from lab_tools import grafo_riferimenti as g
        from lab_tools.urn import expand_index

        df = pd.DataFrame(
            [
                {
                    "fonte_urn": "urn:nir:stato:legge:2021-01-01;9",
                    "target_urn": "urn:nir:stato:legge:1990-08-07;241",
                    "rel_type": "citation",
                    "origin": "ref",
                    "detail": "href",
                    "contesto": "",
                },
                {
                    "fonte_urn": "urn:nir:stato:legge:2020-01-01;1",
                    "target_urn": "urn:nir:stato:legge:1990-08-07;241",
                    "rel_type": "citation",
                    "origin": "ref",
                    "detail": "href",
                    "contesto": "",
                },
                {
                    "fonte_urn": "urn:nir:stato:legge:2020-01-01;1",
                    "target_urn": "urn:nir:stato:legge:2019-01-10;2",
                    "rel_type": "citation",
                    "origin": "ref",
                    "detail": "href",
                    "contesto": "",
                },
            ]
        )
        df.to_parquet(tmp_path / "akn_relations.parquet")
        monkeypatch.setattr(g, "OUTDIR", tmp_path)
        mappa = expand_index(
            [
                ("urn:nir:stato:legge:2020-01-01;1", "Leggi/2020.md"),
                ("urn:nir:stato:legge:2019-01-10;2", "Leggi/2019.md"),
            ]
        )
        archi = g._archi_da_akn_relations({}, mappa)
        assert len(archi) == 2, "la riga con fonte assente deve essere saltata"


class TestArchiAbrogazioni:
    """Fold di `abrogations_raw`: risoluzione anno+numero e guardia temporale."""

    def _normativa(self):
        return {
            "s.md": {
                "urn": "urn:nir:stato:legge:2020-01-01;1",
                "anno_atto": 2020,
                "numero": "1",
                "tipo": "LEGGE",
                "collezione": "Leggi",
                "materia": "",
                "stato": "vigente",
            },
            "t.md": {
                "urn": "urn:nir:stato:legge:2010-01-01;2",
                "anno_atto": 2010,
                "numero": "2",
                "tipo": "LEGGE",
                "collezione": "Leggi",
                "materia": "",
                "stato": "vigente",
            },
            "old.md": {
                "urn": "urn:nir:stato:legge:2000-01-01;3",
                "anno_atto": 2000,
                "numero": "3",
                "tipo": "LEGGE",
                "collezione": "Leggi",
                "materia": "",
                "stato": "vigente",
            },
        }

    def _parquet(self, tmp_path):
        import pandas as pd

        df = pd.DataFrame(
            [
                # valida: 2020 abroga 2010
                {"abrogating_file": "s.md", "abrogating_collection": "Leggi",
                 "abrogated_year": 2010, "abrogated_number": 2, "context": "ok"},
                # impossibile: 2000 abroga 2020
                {"abrogating_file": "old.md", "abrogating_collection": "Leggi",
                 "abrogated_year": 2020, "abrogated_number": 1, "context": "no"},
                # target non nel corpus
                {"abrogating_file": "s.md", "abrogating_collection": "Leggi",
                 "abrogated_year": 1999, "abrogated_number": 9, "context": "no"},
            ]
        )
        df.to_parquet(tmp_path / "abrogations_raw.parquet")

    def test_risolve_e_applica_la_guardia(self, tmp_path, monkeypatch):
        from lab_tools import grafo_riferimenti as g

        self._parquet(tmp_path)
        monkeypatch.setattr(g, "OUTDIR", tmp_path)
        archi = g._archi_da_abrogazioni(self._normativa())
        assert len(archi) == 1, archi
        a = archi[0]
        assert a["rel_type"] == "abroga"
        assert a["fonte_urn"] == "urn:nir:stato:legge:2020-01-01;1"
        assert a["bersaglio_urn"] == "urn:nir:stato:legge:2010-01-01;2"
        assert a["fonte_filename"] == "Leggi/s.md"
        assert a["risolto"] is True

    def test_file_assente(self, tmp_path, monkeypatch):
        from lab_tools import grafo_riferimenti as g

        monkeypatch.setattr(g, "OUTDIR", tmp_path)
        assert g._archi_da_abrogazioni(self._normativa()) == []


class TestAttiIndexPubblicato:
    """Fallback di rete: clean pubblicato quando il raw locale manca."""

    def test_download_valido(self, monkeypatch):
        import io

        import pandas as pd
        import requests
        from lab_tools import grafo_riferimenti as g

        buf = io.BytesIO()
        pd.DataFrame(
            {"urn": ["urn:nir:stato:legge:1990-08-07;241"]}
        ).to_parquet(buf, index=False)
        payload = buf.getvalue()

        class R:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def raise_for_status(self):
                pass

            def iter_content(self, chunk_size=1):
                yield payload

        monkeypatch.setattr(requests, "get", lambda *a, **k: R())
        df = g._scarica_atti_index_pubblicato()
        assert df is not None
        assert list(df["urn"]) == ["urn:nir:stato:legge:1990-08-07;241"]

    def test_http_500_degrada_a_none(self, monkeypatch):
        import requests
        from lab_tools import grafo_riferimenti as g

        class R:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def raise_for_status(self):
                raise requests.HTTPError("500")

            def iter_content(self, chunk_size=1):
                yield b""

        monkeypatch.setattr(requests, "get", lambda *a, **k: R())
        assert g._scarica_atti_index_pubblicato() is None


class TestContestoMarkdown:
    """Il contesto citazione è testo: link e URL non devono finirci dentro."""

    def test_link_diventa_testo(self):
        body = (
            "Visto l'[art. 1 della legge 190/2012]"
            "(../Leggi/2012-11-06_12G0213_VIGENZA_2025-10-10_V0.md); visto il resto."
        )
        [(path, ctx)] = estrai_link_con_contesto(body)
        assert path.endswith("2012-11-06_12G0213_VIGENZA_2025-10-10_V0.md")
        assert "art. 1 della legge 190/2012" in ctx
        assert "](" not in ctx and ".md" not in ctx and "VIGENZA" not in ctx

    def test_finestra_che_inizia_dentro_un_target(self):
        """Regressione: la finestra ±_CTX_MAX può partire dentro un link."""
        body = (
            "[legge 447](../Codici/1992-02-15_092G0118_VIGENZA_2025-10-14_V0.md) "
            "e [art. 2](../Leggi/2000-01-01_000G0001_VIGENZA_2025-01-01_V0.md)."
        )
        contesti = [c for _, c in estrai_link_con_contesto(body)]
        assert len(contesti) == 2
        for ctx in contesti:
            assert "](" not in ctx, ctx
            assert ".md" not in ctx, ctx
            assert "VIGENZA" not in ctx, ctx

    def test_url_e_urn_nudi_rimossi(self):
        body = (
            "Vedi https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:1990;241 "
            "e [art. 1](../Leggi/2000-01-01_000G0001_VIGENZA_2025-01-01_V0.md)."
        )
        [(_, ctx)] = estrai_link_con_contesto(body)
        assert "http" not in ctx and "urn:nir:" not in ctx


    def test_target_spezzato_mantiene_i_newline(self):
        """Un target su più righe non deve far sparire la riga."""
        body = (
            "Testo [legge 190/2012](../Leggi/2012-11-06_12G0213_\n"
            "VIGENZA_2025-10-10_V0.md) fine."
        )
        pulito = pulisci_markup(body)
        assert len(pulito) == len(body)
        assert pulito.count("\n") == body.count("\n")
        assert ".md" not in pulito and "](" not in pulito


class TestDominioUrn:
    """Il grafo mescola tre spazi di nomi: vanno distinti, non contati insieme.

    I casi sono URN reali osservati sul corpus 2026-11 nei bersagli AKN non
    risolti: se il classificatore sbaglia, il conteggio degli "ignoti" torna a
    mentire.
    """

    @pytest.mark.parametrize(
        "urn,atteso",
        [
            ("urn:nir:stato:legge:1990-08-07;241", "nir"),
            ("urn:nir:stato:regio.decreto:1940-07-06;1056", "nir"),
            # Due grafie della stessa entità UE: stesso dominio.
            ("urn:nir:eu:direttivaue:1996;23", "ue"),
            ("urn:nir:eu:direttiva.ue:1989;391", "ue"),
            ("urn:nir:eu:regolamento:2016;679", "ue"),
            # Emettitore o tipo persi dalla fonte: non è normativa statale.
            ("urn:nir:::1928-02-05;577", "altro"),
            ("urn:nir::regolamento:1907;90", "altro"),
            ("urn:nir:capo.provvisorio.stato::1938-04-28;1165", "altro"),
            ("http://example.org/x", "altro"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_classificazione(self, urn, atteso):
        assert dominio_urn(urn) == atteso


class TestEsitoBersaglio:
    """`esito` raffina `risolto`: il corpus è il 10% del catalogo."""

    def _arco(self, risolto, urn):
        return {"risolto": risolto, "bersaglio_urn": urn}

    def test_risolto_vince_su_tutto(self):
        arco = self._arco(True, "urn:nir:stato:legge:1990-08-07;241")
        assert esito_bersaglio(arco, set()) == ESITO_IN_CORPUS

    def test_fuori_corpus_ma_in_catalogo(self):
        arco = self._arco(False, "urn:nir:stato:legge:1990-08-07;241")
        assert esito_bersaglio(arco, {arco["bersaglio_urn"]}) == ESITO_IN_CATALOGO

    def test_direttiva_non_e_mai_in_catalogo(self):
        arco = self._arco(False, "urn:nir:eu:direttivaue:1996;23")
        # anche se per ipotesi l'URN comparisse nel catalogo, il dominio vince
        assert esito_bersaglio(arco, {arco["bersaglio_urn"]}) == ESITO_DOMINIO_UE

    def test_fuori_perimetro(self):
        arco = self._arco(False, "urn:nir:autorita.energia:delibera:2002-03-19;42")
        assert esito_bersaglio(arco, set()) == ESITO_FUORI_PERIMETRO

    def test_senza_bersaglio(self):
        assert esito_bersaglio(self._arco(False, ""), set()) == ESITO_SENZA_BERSAGLIO


class TestVerificaEsiti:
    """L'invariante che impedisce ai due campi di divergere."""

    def test_coerenti(self):
        _verifica_esiti(
            [
                {"risolto": True, "esito": ESITO_IN_CORPUS},
                {"risolto": False, "esito": ESITO_IN_CATALOGO},
            ],
            catalogo_disponibile=True,
        )

    def test_divergenza_risolto_esito(self):
        with pytest.raises(ValueError, match="incoerenti"):
            _verifica_esiti(
                [{"risolto": False, "esito": ESITO_IN_CORPUS}],
                catalogo_disponibile=True,
            )

    def test_esito_non_valido(self):
        with pytest.raises(ValueError, match="esito non valido"):
            _verifica_esiti([{"risolto": False, "esito": "boh"}], catalogo_disponibile=True)

    def test_in_catalogo_senza_catalogo(self):
        """Senza atti_index non si può classificare: meglio fallire che mentire."""
        with pytest.raises(ValueError, match="senza catalogo"):
            _verifica_esiti([{"risolto": False, "esito": ESITO_IN_CATALOGO}], catalogo_disponibile=False)


class TestChiaveUe:
    """(anno, numero) è la chiave di fallback del ponte CELEX."""

    @pytest.mark.parametrize(
        "anno,numero,atteso",
        [(1989, "391", (1989, 391)), ("1989", 391, (1989, 391)), (None, 1, None),
         (1989, None, None), ("x", 1, None), (0, 5, None)],
    )
    def test_chiave(self, anno, numero, atteso):
        assert _chiave_ue(anno, numero) == atteso


class TestRisolviCelex:
    """Il ponte usa due stadi: URN esatta, poi anno/numero."""

    PER_URN = {
        "urn:nir:eu:direttiva.ue:1989;391": "31989L0391",
        "urn:nir:eu:direttivaue:1989;391": "31989L0391",
    }
    PER_CHIAVE = {(2006, 47): "32006L0047"}

    def test_join_esatto_su_entrambe_le_grafie(self):
        for urn in self.PER_URN:
            assert risolvi_celex(urn, self.PER_URN, {}) == "31989L0391"

    def test_fallback_anno_numero(self):
        """Forma non elencata in `urn_varianti`: si recupera dalla chiave."""
        assert (
            risolvi_celex("urn:nir:eu:direttiva.ue:2006;47", {}, self.PER_CHIAVE)
            == "32006L0047"
        )

    def test_sconosciuta(self):
        assert risolvi_celex("urn:nir:eu:direttiva.ue:1999;999", self.PER_URN, self.PER_CHIAVE) is None

    def test_non_direttiva(self):
        """I regolamenti sono un altro asse CELEX: `direttive_ue` non li copre."""
        assert risolvi_celex("urn:nir:eu:regolamento:2016;679", self.PER_URN, self.PER_CHIAVE) is None

    def test_urn_vuota(self):
        assert risolvi_celex("", self.PER_URN, self.PER_CHIAVE) is None
        assert risolvi_celex(None, self.PER_URN, self.PER_CHIAVE) is None


class TestVerificaCelex:
    """Un CELEX su un atto NIR sarebbe un'identità sbagliata."""

    def test_coerenti(self):
        _verifica_celex(
            [
                {"dominio_bersaglio": "ue", "bersaglio_celex": "31989L0391"},
                {"dominio_bersaglio": "ue", "bersaglio_celex": None},
                {"dominio_bersaglio": "nir", "bersaglio_celex": None},
            ]
        )

    def test_celex_su_nir(self):
        with pytest.raises(ValueError, match="fuori dal dominio UE"):
            _verifica_celex(
                [{"dominio_bersaglio": "nir", "bersaglio_celex": "31989L0391"}]
            )


class TestAnnoEspressione:
    """Anno dell'espressione: snapshot per le VIGENZA, atto per gli ORIGINALE.

    La guardia temporale dei consumer deve usare questo: con `anno_atto` un
    atto del 1874 con testo consolidato al 2025 fa scartare 6.379 coppie
    legittime (misurato su legal-graph 2026-11).
    """

    def test_vigenza_usa_lo_snapshot(self):
        from lab_tools.grafo_riferimenti import anno_espressione

        assert anno_espressione({"anno_atto": 1874, "snapshot_data": "2025-10-10"}) == 2025

    def test_originale_usa_l_anno_dell_atto(self):
        from lab_tools.grafo_riferimenti import anno_espressione

        assert anno_espressione({"anno_atto": 1874, "snapshot_data": None}) == 1874

    def test_timestamp_pandas(self):
        import pandas as pd
        from lab_tools.grafo_riferimenti import anno_espressione

        assert anno_espressione({"anno_atto": 1874, "snapshot_data": pd.Timestamp("2026-01-02")}) == 2026

    def test_nan_su_entrambi(self):
        from lab_tools.grafo_riferimenti import anno_espressione

        assert anno_espressione({"anno_atto": float("nan")}) is None


class TestRepealNelMart:
    """I `repeal` AKN entrano nel mart come `abroga`, con l'origine dichiarata.

    Prima LG leggeva `akn_relations` direttamente e i bersagli non erano
    canonicalizzati: 57.708 archi persi perché nessuno creava il nodo.
    """

    def _parquet(self, tmp_path):
        import pandas as pd

        df = pd.DataFrame(
            [
                {
                    "fonte_urn": "urn:nir:stato:legge:2020-01-01;1",
                    "target_urn": "urn:nir:stato:legge:1990-08-07;241",
                    "rel_type": "repeal",
                    "origin": "activeModification",
                    "detail": "href",
                    "contesto": float("nan"),
                    "locator": "~art_1",
                }
            ]
        )
        df.to_parquet(tmp_path / "akn_relations.parquet")

    def test_emesso_come_abroga_con_origine_akn(self, tmp_path, monkeypatch):
        from lab_tools import grafo_riferimenti as g

        self._parquet(tmp_path)
        monkeypatch.setattr(g, "OUTDIR", tmp_path)
        archi = g._archi_da_akn_relations({}, {"urn:nir:stato:legge:2020-01-01;1": "Leggi/2020.md"})
        assert len(archi) == 1
        a = archi[0]
        assert a["rel_type"] == "abroga"
        assert a["origine"] == "akn"
        assert a["risolto"] is False
        assert a["bersaglio_urn"] == "urn:nir:stato:legge:1990-08-07;241"
        assert a["bersaglio_anno"] == 1990
        assert a["contesto"] == "akn:activeModification"

    def test_le_citation_non_sono_toccate(self, tmp_path, monkeypatch):
        """Il blocco repeal non deve emettere le citation due volte."""
        import pandas as pd
        from lab_tools import grafo_riferimenti as g

        pd.DataFrame(
            [
                {
                    "fonte_urn": "urn:nir:stato:legge:2020-01-01;1",
                    "target_urn": "urn:nir:stato:legge:2019-01-01;2",
                    "rel_type": "citation",
                    "origin": "ref",
                    "detail": "href",
                    "contesto": "testo",
                }
            ]
        ).to_parquet(tmp_path / "akn_relations.parquet")
        monkeypatch.setattr(g, "OUTDIR", tmp_path)
        archi = g._archi_da_akn_relations({}, {"urn:nir:stato:legge:2020-01-01;1": "Leggi/2020.md"})
        assert [a["rel_type"] for a in archi] == ["citation"]
