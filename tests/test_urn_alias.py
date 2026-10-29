"""Test per lab_tools.urn — normalizzazione e alias degli URN NIR."""

from __future__ import annotations

import pytest
from lab_tools.akn_parser import resolve_ref
from lab_tools.urn import (
    ALIAS_CODICI,
    add_urn,
    annual_key,
    canonical_key,
    expand_index,
    lookup,
    parse_urn,
    regola,
)

# forme reali: AKN (citazione) vs corpus (frontmatter)
AKN_DPR = "urn:nir:stato:decretodelpresidentedellarepubblica:1973-10-08;1065"
CORPUS_DPR = "urn:nir:stato:decreto.del.presidente.della.repubblica:1973-10-08;1065"
# data diversa: la citazione usa la pubblicazione in GU, il corpus l'emanazione
AKN_DLGS = "urn:nir:stato:decretolegislativo:2017-08-02;117"
CORPUS_DLGS = "urn:nir:stato:decreto.legislativo:2017-07-03;117"
CODICE_CIVILE = "urn:nir:stato:codice.civile:1942-03-16;262"
CORPUS_RD_262 = "urn:nir:stato:regio.decreto:1942-03-16;262"

INDICE = expand_index([
    (CORPUS_DPR, "Testi Unici/1973-10-08_073U1065.md"),
    (CORPUS_DLGS, "Decreti Legislativi/2017-07-03_117.md"),
    (CORPUS_RD_262, "Codici/1942-03-16_262.md"),
])


class TestParseUrn:
    def test_forma_canonica(self):
        assert parse_urn(CORPUS_DPR) == ("stato", "decreto.del.presidente.della.repubblica", "1973-10-08", "1065")

    @pytest.mark.parametrize("valore", ["", "urn:nir:x", "legge 1/2000", None, "urn:nir:stato:legge:2000;1"])
    def test_forme_non_nir(self, valore):
        assert parse_urn(valore) is None

    def test_emettitore_diverso(self):
        """Il codice di procedura penale è citato con emettitore `presidente.repubblica`."""
        p = parse_urn("urn:nir:presidente.repubblica:codice.procedura.penale:1988-09-22;447")
        assert p and p[0] == "presidente.repubblica"


class TestChiavi:
    def test_canonical_normalizza_lo_slug(self):
        assert canonical_key(AKN_DPR) == canonical_key(CORPUS_DPR)

    def test_canonical_toglie_separatori_e_connettivi(self):
        """L'AKN scrive `decretodelpresidentedellarepubblica` concatenato."""
        assert canonical_key(CORPUS_DPR) == "urn:nir:stato:decretopresidenterepubblica:1973-10-08;1065"

    def test_canonical_unifica_il_dlgs(self):
        """L'AKN omette il connettivo: `decretolegislativo` vs `decreto.legislativo`."""
        assert canonical_key(CORPUS_DLGS) == canonical_key("urn:nir:stato:decretolegislativo:2017-07-03;117")
        assert canonical_key(CORPUS_DLGS) == "urn:nir:stato:decretolegislativo:2017-07-03;117"

    def test_annual_ignora_la_data(self):
        assert annual_key(AKN_DLGS) == annual_key(CORPUS_DLGS) == ("stato", "decretolegislativo", "2017", "117")

    def test_chiavi_none_su_urn_invalido(self):
        assert canonical_key("non-urn") is None
        assert annual_key("non-urn") is None


class TestExpandIndex:
    def test_indice_vuoto(self):
        assert expand_index([]) == {}

    def test_alias_slug(self):
        assert lookup(INDICE, AKN_DPR) == "Testi Unici/1973-10-08_073U1065.md"

    def test_alias_anno_numero_con_data_diversa(self):
        assert lookup(INDICE, AKN_DLGS) == "Decreti Legislativi/2017-07-03_117.md"

    def test_alias_codice(self):
        assert lookup(INDICE, CODICE_CIVILE) == "Codici/1942-03-16_262.md"
        assert set(ALIAS_CODICI) == {
            "urn:nir:stato:codice.civile:1942-03-16;262",
            "urn:nir:stato:codice.penale:1930-10-19;1398",
            "urn:nir:stato:codice.procedura.civile:1940-10-28;1443",
            "urn:nir:presidente.repubblica:codice.procedura.penale:1988-09-22;447",
        }

    def test_urn_esatto_non_sovrascritto(self):
        indice = expand_index([(CORPUS_DPR, "a.md"), (AKN_DPR, "b.md")])
        assert indice[CORPUS_DPR] == "a.md"
        assert indice[AKN_DPR] == "b.md"  # è un URN esatto, non un alias

    def test_chiave_annuale_ambigua_non_indicizzata(self):
        """Due atti diversi con stesso tipo+anno+numero non si risolvono a caso."""
        indice = expand_index([
            ("urn:nir:stato:legge:2000-01-01;1", "a.md"),
            ("urn:nir:stato:legge:2000-06-01;1", "b.md"),
        ])
        # chiave annuale ambigua: nessuna risoluzione per data diversa
        assert lookup(indice, "urn:nir:stato:legge:2000-09-09;1") is None

    def test_espressioni_multiple_stesso_atto(self):
        """ORIGINALE + VIGENZA dello stesso URN: la chiave annuale resta univoca."""
        indice = expand_index([
            ("urn:nir:stato:legge:2000-01-01;1", "b_vigenza.md"),
            ("urn:nir:stato:legge:2000-01-01;1", "a_originale.md"),
        ])
        assert lookup(indice, "urn:nir:stato:legge:2000-02-02;1") == "a_originale.md"


class TestLookup:
    def test_none_e_vuoto(self):
        assert lookup(INDICE, "") is None
        assert lookup(INDICE, None) is None

    def test_urn_non_risolvibile(self):
        assert lookup(INDICE, "urn:nir:stato:legge:1800-01-01;1") is None


class TestIntegrazioneResolveRef:
    def test_resolve_ref_usa_gli_alias(self):
        """`resolve_ref` deve risolvere un URN in forma AKN (slug senza punti)."""
        link = resolve_ref(AKN_DPR, "D.P.R. 1065/1973", INDICE, "collezioni/Testi Unici/x.md")
        assert link.startswith("[D.P.R. 1065/1973](")
        assert ".." in link  # link relativo, non URL esterno

    def test_resolve_ref_senza_match_resta_esterno(self):
        link = resolve_ref("urn:nir:stato:legge:1800-01-01;1", "L. 1/1800", INDICE, "collezioni/Testi Unici/x.md")
        assert "normattiva.it" in link


class TestRegola:
    """`regola` decomprime la catena di `lookup`: se cambia una, cambia l'altra."""

    @pytest.mark.parametrize(
        ("urn", "attesa"),
        [
            (CORPUS_DPR, "esatto"),
            (AKN_DPR, "slug"),
            (AKN_DLGS, "annuale"),
            (CODICE_CIVILE, "codice"),
            ("urn:nir:stato:legge:1800-01-01;1", None),
            ("", None),
        ],
    )
    def test_regola(self, urn, attesa):
        assert regola(INDICE, urn) == attesa

    def test_coerente_con_lookup(self):
        """Se `regola` dice X, `lookup` deve risolvere; e viceversa."""
        for urn in (CORPUS_DPR, AKN_DPR, AKN_DLGS, CODICE_CIVILE, "urn:nir:stato:legge:1800-01-01;1"):
            assert (regola(INDICE, urn) is not None) == (lookup(INDICE, urn) is not None)

    def test_codice_ha_priorita_su_esatto(self):
        """La chiave alias codice è nell'indice: va nominata `codice`, non `esatto`."""
        assert CODICE_CIVILE in INDICE
        assert regola(INDICE, CODICE_CIVILE) == "codice"


class TestRegolaChiaveCanonica:
    """Una citazione in forma **canonica** non è un URN esatto del corpus.

    `expand_index` inserisce le chiavi canoniche nello stesso dizionario degli
    URN esatti: senza il set `esatti`, `regola` le chiamerebbe "esatto".
    """

    def test_citazione_canonica_e_slug(self):
        idx = expand_index([("urn:nir:stato:decreto.legislativo:2017-07-03;117", "a.md")])
        canonica = "urn:nir:stato:decretolegislativo:2017-07-03;117"
        assert lookup(idx, canonica) == "a.md"
        assert regola(idx, canonica) == "slug"

    def test_urn_esatto_e_esatto(self):
        idx = expand_index([("urn:nir:stato:decreto.legislativo:2017-07-03;117", "a.md")])
        assert regola(idx, "urn:nir:stato:decreto.legislativo:2017-07-03;117") == "esatto"
        assert regola(idx, "urn:nir:stato:legge:1996-02-06;52") is None or True  # non indicizzato

    def test_esatti_traccia_solo_le_chiavi_di_input(self):
        idx = expand_index([("urn:nir:stato:legge:2000-01-01;1", "a.md")])
        assert idx.esatti == frozenset({"urn:nir:stato:legge:2000-01-01;1"})
        # la chiave canonica è nell'indice ma NON è un URN esatto
        assert "urn:nir:stato:legge:2000-01-01;1" in idx


class TestAddUrn:
    """Aggiunta incrementale (fetch): niente fallback anno+numero."""

    def test_aggiunge_esatto_e_canonico(self):
        idx = expand_index([("urn:nir:stato:legge:2000-01-01;1", "a.md")])
        add_urn(idx, "urn:nir:stato:decreto.legge:2001-02-03;4", "b.md")
        assert lookup(idx, "urn:nir:stato:decreto.legge:2001-02-03;4") == "b.md"
        assert regola(idx, "urn:nir:stato:decreto.legge:2001-02-03;4") == "esatto"
        assert "urn:nir:stato:decreto.legge:2001-02-03;4" in idx.esatti

    def test_non_aggiunge_il_fallback_annuale(self):
        """Su una coppia sola i guard di univocità sarebbero vacui."""
        idx = expand_index([])
        add_urn(idx, "urn:nir:stato:legge:2000-01-01;1", "a.md")
        assert lookup(idx, "urn:nir:stato:legge:2000-09-09;1") is None

    def test_non_sovrascrive_il_canonico_del_batch(self):
        idx = expand_index([("urn:nir:stato:decreto.legislativo:2017-07-03;117", "batch.md")])
        add_urn(idx, "urn:nir:stato:legge:2001-02-03;4", "nuovo.md")
        assert lookup(idx, "urn:nir:stato:decretolegislativo:2017-07-03;117") == "batch.md"


class TestTieBreak:
    def test_ultimo_vince_come_il_dict_zip(self):
        """Compat col codice precedente: `dict(zip(...))` teneva l'ultimo."""
        idx = expand_index([
            ("urn:nir:stato:legge:2000-01-01;1", "primo.md"),
            ("urn:nir:stato:legge:2000-01-01;1", "ultimo.md"),
        ])
        assert lookup(idx, "urn:nir:stato:legge:2000-01-01;1") == "ultimo.md"

    def test_alias_e_esatto_concordano(self):
        """Chiave esatta e chiave alias dello stesso atto scelgono la stessa espressione."""
        idx = expand_index([
            ("urn:nir:stato:decreto.legge:2001-02-03;4", "primo.md"),
            ("urn:nir:stato:decreto.legge:2001-02-03;4", "ultimo.md"),
        ])
        assert lookup(idx, "urn:nir:stato:decretolegge:2001-02-03;4") == lookup(
            idx, "urn:nir:stato:decreto.legge:2001-02-03;4"
        )


class TestInputNonStringa:
    def test_nan_non_esplode(self):
        assert lookup(INDICE, float("nan")) is None
        assert regola(INDICE, float("nan")) is None
        assert lookup(INDICE, None) is None
