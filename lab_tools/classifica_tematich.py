"""Classificatore tematico per atti normativi (colonna `materia`).

Match sull'`oggetto` (titolo) con keyword → materia, 25 categorie. Semantica:

- **Confine di parola a sinistra** su tutte le keyword (le radici tipo "fiscal",
  "istruzion" restano libere a destra); **confine a destra** per `_PAROLA_INTERA`
  (parole intere e acronimi: "comuni", "arte", "posta", "pac"). Senza, "iva"
  matchava "rel**ativa**", "arte" matchava "p**arte**", "pac" matchava "pace".
- **Trattati internazionali** (ratifica ed esecuzione, trattato, scambio di note,
  accordo/convenzione fra Governi, protocollo internazionale) → `affari-esteri`,
  prima delle keyword tematiche. La ratifica di un atto interno non è un trattato.
- **`strutturale`** (conversione in legge, delega) è **fallback**: solo se nessuna
  materia tematica matcha.
- Il codice redazionale in coda (es. `(15G00065)`) è metadato, non titolo: rimosso
  prima del match ("5g" matchava dentro "15G00065").

Qualità misurata, gold set e limiti: docs/MATERIA_AUDIT.md.

Uso: python -m lab_tools.classifica_tematich
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTDIR = REPO / "data" / "derived"
NORMATIVA_PARQUET = OUTDIR / "normativa.parquet"

# Codice redazionale in coda al titolo: (12G0207), ((16G00062)), (030U1002).
_CODICE_REDAZIONALE = re.compile(r"\(\s*\(?\s*\d{2,3}[A-Z]\d{3,}\s*\)?\s*\)")

# Trattati internazionali → affari-esteri (tier 1, prima delle keyword tematiche).
_TRATTATO = re.compile(
    "|".join(
        (
            r"ratifica ed esecuzione",
            r"\btrattato\b",
            r"scambio di note",
            r"memorandum",
            r"accordo (?:tra|fra) (?:il|i) govern[oi]",
            r"convenzione (?:tra|fra) (?:il|i) govern[oi]",
            r"emendament\w* (?:al|della|della )?\s*protocollo",
            r"protocollo\b.{0,90}?(?:convenzione|internazional|emendament)",
        )
    )
)

# Mapping keyword → materia. Ordine = priorità (primo match vincente).
# Le keyword sono in minuscolo; l'oggetto viene normalizzato prima del match.
_TEMI: list[tuple[str, tuple[str, ...]]] = [
    ("ambientale", (
        "ambientale", "ambiente", "inquinamento", "acque", "rifiuti",
        "energia", "rinnovabili", "emissioni", "clima", "biodiversita",
        "fauna", "flora", "vincoli ambientali", "sismica",
        "bonifica", "discarica", "acustica",
    )),
    ("lavoro", (
        "lavoro", "lavoratori", "occupazione", "pubblico impiego", "sindacat",
        "contratto collettivo", "apprendist", "disoccupaz", "cassa integrazione",
        "mobilita", "sicurezza sul lavoro", "infortun", "igiene industriale",
        "dispositivi di protezione",
        "orario di lavoro", "tfr", "trattamento di fine rapporto",
    )),
    ("fisco", (
        "fiscal", "tributar", "imposta", "imposte", "iva", "irpef",
        "entrate", "ministero delle finanze",
        "dogana", "dogan", "dazio", "tassa", "tasse", "accisa", "sgrav",
        "detrazion", "deduzion", "valutari",
        "riciclaggio",
        "bilancio", "spesa pubblica", "debito pubblico", "finanza pubblica",
        "razionalizzazione della finanza",
    )),
    ("sanita", (
        "sanitar", "salute", "medic", "farmac", "ospedal",
        "servizio sanitario", "ssn", "medico", "infermier",
        "malattie", "epidemi", "vaccin", "pronto soccorso",
        "igienic", "igiene pubblica",
    )),
    ("istruzione", (
        "istruzion", "scuola", "scolastic", "universit", "ricerca", "formazione",
        "docenti", "insegnant", "professor", "student", "laure", "diplom", "accademi",
        "consiglio nazionale delle ricerche", "cnr",
    )),
    ("trasporti", (
        "trasport", "autotrasport", "ferrovi", "navale", "aeronautic", "portual", "porto",
        "stradale", "autostrad", "aeroport", "circolazione stradale",
        "codice della strada", "patent", "autoscuol", "navigazione",
    )),
    ("agricoltura", (
        "agricol", "agrar", "agronom", "agroalimentar", "vinificaz", "olivicolt",
        "zootecnia", "pesca", "foreste", "comunita' europee dell'agricoltura",
        "pac", "politica agricola comune", "alimentare", "alimentari",
        "olio di oliva",
        "galline", "ovaiole", "veterinar", "carne", "latte", "cereali",
    )),
    ("difesa", (
        "difesa", "militar", "esercito", "aeronautica militare",
        "marina militare", "carabinieri", "guardia costiera",
        "armi", "munizioni", "stato maggiore", "servizio militare",
    )),
    ("giustizia", (
        "giustizi", "penale", "magistrat",
        "procedura penale", "procedura civile", "procedura amministrativa",
        "codice civile", "stato civile", "parte civile",
        "corte costituzionale", "cassazione", "tribunale", "pretura",
        "avvocat", "forense", "notai", "conciliaz", "mediaz",
        "sequestr", "confisca", "impugnazion",
        "esecuzione penale", "benefit penitenziari", "istituti penitenziari",
        "amnistia", "indulto", "grazia",
    )),
    ("affari-esteri", (
        "affari esteri", "esteri", "trattat", "convenzion", "accord",
        "diplomaz", "cancellier", "ambasciat",
        "onu", "nato", "osce", "consiglio d'europa",
    )),
    ("enti-locali", (
        "enti locali", "comune", "comuni", "province", "regioni", "statuto speciale",
        "autonomia", "decentramento", "federalismo", "conferenza dei servizi",
        "urbanistic", "edilizi", "piano regolatore", "opere pubbliche", "idraulich",
        "interesse statale",
    )),
    ("previdenza", (
        "previdenz", "pension", "inps", "inail", "contributi previdenziali",
        "trattamento di fine servizio", "quota 100", "quota 41",
        "reddito di cittadinanza",
    )),
    ("cultura", (
        "cultur", "beni culturali", "paesaggio", "arte", "archeologi", "museo",
        "biblioteche", "archivi", "spettacol", "cinematograf",
        "editori", "editric", "quotidiani", "libro", "radio", "televisione", "rai",
        "teatr", "restaur",
        "interesse storico",
    )),
    ("sport", (
        "sport", "sportiv", "olimpic", "fifa", "uefa", "coni", "anti-doping",
    )),
    ("ordinamento-pa", (
        "pubblica amministrazione", "funzion", "concorso pubblico",
        "organizzazione amministrativa", "protocollo", "archivio di stato",
        "accesso agli atti", "trasparenza", "anticorruzione",
        "codice dei contratti", "aggiudicatar", "appalt", "gara",
        "concessione", "concessionar",
    )),
    ("recepimento-ue", (
        "attuazione della direttiva", "recepimento della direttiva",
        "attuazione del regolamento", "direttiva ce", "direttiva ue",
        "regolamento ue", "delegazione europea",
        "direttive 19", "direttive 20", "regolamento (ce)",
    )),
    ("comunicazioni", (
        "postali", "postal", "telecomunicazioni", "comunicazioni elettroniche",
        "internet", "posta", "banda larga", "5g",
    )),
    ("turismo", (
        "turism", "turist", "ospitalit", "alberghier", "crocierist",
    )),
    ("ordine-pubblico", (
        "pubblica sicurezza", "pubblico ordine", "pubblica incolumita",
        "ordine pubblico", "vigili del fuoco", "protezione civile",
    )),
    ("industria", (
        "industrial", "manifattur", "produzione", "imprese",
        "piccole e medie imprese", "pmi", "competitivit", "esportazion",
        "innovazione", "brevett", "marchio",
    )),
    ("servizi-pubblici", (
        "servizi pubblici", "pubblico consumo", "utenti", "concession",
        "servizio pubblico", "water", "energia elettrica", "gas",
        "riscaldamento", "raccolta rifiuti", "net",
    )),
    ("terzo-settore", (
        "terzo settore", "no profit", "non profit", "organizzazioni di volontariato",
        "cooperativ", "consorzi", "servizi sociali", "assistenza sociale",
        "politiche sociali", "beneficenza",
    )),
    ("ordinamento-stato", (
        "organizzazione del governo", "corte dei conti", "corte costituzionale",
        "parlamento", "senato", "camera dei deputati", "capo dello stato",
        "intestazione dei decreti", "presidenza del consiglio",
    )),
    ("strutturale", (
        "conversione in legge", "conversione del decreto", "delega al governo",
        "deleghe al governo", "delega legislativa",
    )),
]

_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}

# Keyword che sono parole intere o acronimi: oltre al confine sinistro serve
# anche quello destro. Senza, "comuni" matcha "comunitaria", "pac" matcha
# "pace", "posta" matcha "imposta", "arte" matcha "parte". Lista esplicita
# (non derivata): le radici che finiscono in vocale — "giustizi", "ferrovi",
# "archivi", "valutari" — devono restare a lato destro libero.
_PAROLA_INTERA = frozenset({
    "arte", "armi", "comune", "comuni", "coni", "fifa", "gara", "iva",
    "nato", "net", "onu", "osce", "pac", "pmi", "posta", "porto", "rai",
    "sport", "tfr", "cnr", "ssn", "inps", "uefa", "5g",
})


def _pattern(kw: str) -> re.Pattern[str]:
    """Regex keyword con confine a sinistra (e a destra per le parole intere)."""
    pat = _PATTERN_CACHE.get(kw)
    if pat is None:
        destra = r"(?![a-zàèéìòù])" if kw in _PAROLA_INTERA else ""
        pat = re.compile(r"(?<![a-zàèéìòù0-9])" + re.escape(kw) + destra)
        _PATTERN_CACHE[kw] = pat
    return pat


def _normalizza(oggetto: str) -> str:
    """Titolo normalizzato per il match (minuscolo, senza codice redazionale)."""
    return _CODICE_REDAZIONALE.sub(" ", oggetto.lower())


def _classifica_oggetto(oggetto: str) -> str:
    """Classifica un oggetto (titolo) in una materia.

    Returns nome della materia, oppure 'altro' se nessun match.
    """
    if not oggetto:
        return "altro"
    text = _normalizza(oggetto)
    if _TRATTATO.search(text):
        return "affari-esteri"
    for materia, keywords in _TEMI:
        for kw in keywords:
            if _pattern(kw).search(text):
                return materia
    return "altro"


def main() -> None:
    try:
        import pandas as pd
    except ImportError:
        raise SystemExit("Errore: pandas necessario.")

    if not NORMATIVA_PARQUET.exists():
        raise SystemExit(f"Errore: {NORMATIVA_PARQUET} non trovato.")

    df = pd.read_parquet(NORMATIVA_PARQUET)
    print(f"Atti caricati: {len(df)}")

    df["materia"] = df["oggetto"].fillna("").apply(_classifica_oggetto)

    df.to_parquet(NORMATIVA_PARQUET, index=False)
    print(f"Arricchito con colonna 'materia': {NORMATIVA_PARQUET}")

    # Metriche
    print("\n📊 Distribuzione materie")
    print(f"{'='*40}")
    counts = df["materia"].value_counts()
    for materia, n in counts.items():
        pct = 100.0 * n / len(df)
        bar = "█" * int(pct / 2)
        print(f"  {materia:<25} {n:>6,}  {pct:>5.1f}%  {bar}")

    # Cross: materia x stato
    print("\n📊 Materie x stato (top 10) ===")
    ct = df.groupby(["materia", "stato"]).size().unstack(fill_value=0)
    ct["totale"] = ct.sum(axis=1)
    ct = ct.sort_values("totale", ascending=False).head(10)
    print(ct.to_string())


if __name__ == "__main__":
    main()
