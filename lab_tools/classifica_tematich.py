"""Classificatore tematico per atti normativi.

Estrae la materia predominante dall'oggetto (titolo) di ogni atto
usando keyword mapping. Produce la colonna 'materia' in normativa.parquet.

Da eseguire DOPO arricchisci_normativa.

Uso: python -m lab_tools.classifica_tematich
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTDIR = REPO / "data" / "derived"
NORMATIVA_PARQUET = OUTDIR / "normativa.parquet"

# Mapping keyword → materia. Ordine = priorità (primo match vincente).
# Le keyword sono in minuscolo; l'oggetto viene normalizzato prima del match.
_TEMI: list[tuple[str, tuple[str, ...]]] = [
    ("ambientale", (
        "ambientale", "ambiente", "inquinamento", "acque", "rifiuti",
        "energia", "rinnovabili", "emissioni", "clima", "biodiversita",
        "fauna", "flora", "paesaggio", "vincoli ambientali", "sismica",
        "bonifica", "discarica", "aria", "acustica",
    )),
    ("lavoro", (
        "lavoro", "lavoratori", "occupazione", "impiego", "sindacat",
        "contratto collettivo", "apprendist", "disoccupaz", "cassa integrazione",
        "mobilita", "sicurezza sul lavoro", "infortun", "igiene industriale",
        "orario di lavoro", "tfr", "trattamento di fine rapporto",
    )),
    ("fisco", (
        "fiscal", "tributar", "imposta", "imposte", "iva", "irpef",
        "iregionali", "contribut", "entrare delle entrate", "ministero delle finanze",
        "dogana", "accisa", "sgrav", "detrazion", "deduzion",
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
        "istruzion", "scuola", "universit", "ricerca", "formazione",
        "docenti", "student", "laure", "diplom", "accademi",
        "consiglio nazionale delle ricerche", "inps", "cnr",
    )),
    ("trasporti", (
        "trasport", "ferrovi", "navale", "aeronautic", "portuale",
        "stradale", "autostrad", "aeroport", "circolazione",
        "codice della strada", "patente", "navigazione",
    )),
    ("agricoltura", (
        "agricol", "agroalimentar", "vinificaz", "olivicolt",
        "zootecnia", "pesca", "foreste", "comunita' europee dell'agricoltura",
        "pac", "politica agricola comune", "alimentare", "alimentari",
        "galline", "ovaiole", "veterinar", "carne", "latte", "cereali",
    )),
    ("difesa", (
        "difesa", "militar", "esercito", "aeronautica militare",
        "marina militare", "carabinieri", "guardia costiera",
        "armi", "munizioni", "stato maggiore", "servizio militare",
    )),
    ("giustizia", (
        "giustizi", "penale", "civile", "procedur", "magistrat",
        "corte costituzionale", "cassazione", "tribunale", "pretura",
        "avvocat", "notai", "conciliaz", "mediaz",
        "esecuzione penale", "benefit penitenziari", "istituti penitenziari",
        "amnistia", "indulto", "grazia",
    )),
    ("affari-esteri", (
        "affari esteri", "esteri", "trattat", "convenzion", "accord",
        "ratifica", "diplomaz", "cancellier", "ambasciat",
        "onu", "nato", "osce", "consiglio d'europa",
    )),
    ("enti-locali", (
        "enti locali", "comuni", "province", "regioni", "statuto speciale",
        "autonomia", "decentramento", "federalismo", "conferenza dei servizi",
        "urbanistic", "edilizi", "piano regolatore", "opere pubbliche",
        "interesse statale",
    )),
    ("previdenza", (
        "previdenz", "pension", "inps", "inail", "contributi previdenziali",
        "quota 100", "quota 41", "reddito di cittadinanza",
    )),
    ("cultura", (
        "cultur", "beni culturali", "arte", "archeologi", "musei",
        "biblioteche", "archivi", "spettacol", "cinematograf",
        "editoria", "libro", "radio", "televisione", "rai",
    )),
    ("sport", (
        "sport", "olimpic", "fifa", "uefa", "coni", "anti-doping",
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
        "postali", "telecomunicazioni", "comunicazioni elettroniche",
        "internet", "posta", "banda larga", "5g",
    )),
    ("turismo", (
        "turism", "ospitalit", "alberghier", "crocierist",
    )),
    ("ordine-pubblico", (
        "pubblica sicurezza", "pubblico ordine", "pubblica incolumita",
        "ordine pubblico", "vigili del fuoco", "protezione civile",
    )),
    ("industria", (
        "industrial", "manifattur", "produzione", "imprese",
        "piccole e medie imprese", "pmi", "competitivit",
        "innovazione", "brevett", "marchio",
    )),
    ("servizi-pubblici", (
        "servizi pubblici", "pubblico consumo", "utenti", "concession",
        "servizio pubblico", "water", "energia elettrica", "gas",
        "riscaldamento", "raccolta rifiuti", "net",
    )),
    ("terzo-settore", (
        "terzo settore", "no profit", "non profit", "organizzazioni di volontariato",
        "cooperativ", "consorzi", "sociali", "beneficenza",
    )),
    ("ordinamento-stato", (
        "organizzazione del governo", "governo", "presidenza del consiglio",
        "corte dei conti", "corte costituzionale", "parlamento",
        "senato", "camera dei deputati", "capo dello stato",
        "intestazione dei decreti",
    )),
    ("strutturale", (
        "conversione in legge", "conversione del decreto", "delega al governo",
        "deleghe al governo", "delega legislativa",
    )),
]


def _classifica_oggetto(oggetto: str) -> str:
    """Classifica un oggetto (titolo) in una materia.

    Returns nome della materia, oppure 'altro' se nessun match.
    """
    if not oggetto:
        return "altro"
    text = oggetto.lower()
    for materia, keywords in _TEMI:
        for kw in keywords:
            if kw in text:
                return materia
    return "altro"


def main() -> None:
    try:
        import pandas as pd
    except ImportError:
        print("Errore: pandas necessario.")
        return

    if not NORMATIVA_PARQUET.exists():
        print(f"Errore: {NORMATIVA_PARQUET} non trovato.")
        return

    df = pd.read_parquet(NORMATIVA_PARQUET)
    print(f"Atti caricati: {len(df)}")

    df["materia"] = df["oggetto"].fillna("").apply(_classifica_oggetto)

    df.to_parquet(NORMATIVA_PARQUET, index=False)
    print(f"Arricchito con colonna 'materia': {NORMATIVA_PARQUET}")

    # Metriche
    print(f"\n📊 Distribuzione materie")
    print(f"{'='*40}")
    counts = df["materia"].value_counts()
    for materia, n in counts.items():
        pct = 100.0 * n / len(df)
        bar = "█" * int(pct / 2)
        print(f"  {materia:<25} {n:>6,}  {pct:>5.1f}%  {bar}")

    # Cross: materia x stato
    print(f"\n📊 Materie x stato (top 10) ===")
    ct = df.groupby(["materia", "stato"]).size().unstack(fill_value=0)
    ct["totale"] = ct.sum(axis=1)
    ct = ct.sort_values("totale", ascending=False).head(10)
    print(ct.to_string())


if __name__ == "__main__":
    main()
