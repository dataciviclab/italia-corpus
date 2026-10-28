"""Test per lab_tools.classifica_tematich — classificatore tematico.

Tabella di casi: happy path, confini di parola (anti-regressione sui falsi
positivi trovati nell'audit), radici, trattati. Vedi docs/MATERIA_AUDIT.md.
"""

import pytest
from lab_tools.classifica_tematich import _PAROLA_INTERA, _TEMI, _classifica_oggetto

CASI = [
    # --- happy path ---
    ("Disposizioni in materia fiscale e tributaria", "fisco"),
    ("Norme per la tutela dell'ambiente e dei rifiuti", "ambientale"),
    ("Disciplina dei rapporti di lavoro e sicurezza sul lavoro", "lavoro"),
    ("Disposizioni in materia sanitaria e farmaceutica", "sanita"),
    ("Disposizioni in materia di procedura penale", "giustizia"),
    ("Conversione in legge del decreto-legge n. 123", "strutturale"),
    ("Delega al Governo per il recepimento delle direttive", "strutturale"),
    ("DISPOSIZIONI IN MATERIA FISCALE", "fisco"),
    ("", "altro"),
    (None, "altro"),
    ("Titolo senza keyword riconoscibili", "altro"),
    # --- confini di parola: la keyword non deve matchare dentro un'altra parola ---
    # "iva" dentro "relativa"/"riattivazione" valeva il 22% del corpus
    ("Attuazione della direttiva relativa alle acque", "ambientale"),
    ("Misure per la riattivazione del bacino carbonifero", "altro"),
    # "arte" dentro "parte"
    ("Norme sull'istituzione di un servizio di controllo interno", "altro"),
    # "rai" dentro "contrari"
    ("Provvedimenti contrari alla disciplina vigente", "altro"),
    # "nato" dentro "coordinato"/"destinato"
    ("Coordinato con il decreto del Presidente della Repubblica", "altro"),
    # "gara" dentro "garanzia"
    ("Fondo interbancario di garanzia", "altro"),
    # "posta" dentro "imposta"
    ("Aliquote dell'imposta sul valore aggiunto", "fisco"),
    # "sport" dentro "trasporto"
    ("Misure urgenti per il settore dell'autotrasporto", "trasporti"),
    # "comuni" dentro "comunitaria"
    ("Legge comunitaria per il 1990", "altro"),
    # "pac" dentro "pace"/"capacità"
    ("Partecipazione italiana alla missione di pace", "altro"),
    # "armi" dentro "armonizzazione"
    ("Armonizzazione delle legislazioni sulle macchine", "altro"),
    # "5g" dentro il codice redazionale "(15G00065)"
    ("Regolamento su intermediari finanziari (15G00065)", "altro"),
    # --- radici: le keyword devono coprire tutte le flessioni ---
    ("Requisiti per il conseguimento delle patenti di guida", "trasporti"),
    ("Finanziamento delle imprese operanti nel turismo", "turismo"),
    ("Demanio marittimo ad uso turistico-ricreativo", "turismo"),
    ("Norme per la disciplina dei professori a contratto", "istruzione"),
    ("Lavori di restauro del Teatro della Scala", "cultura"),
    ("Esenzione dal dazio sul valore all'importazione", "fisco"),
    # keyword generiche ristrette: "civile", "impiego"
    ("Eventi alluvionali e protezione civile", "ordine-pubblico"),
    ("Impiego dei fondi patrimoniali degli Istituti di previdenza", "previdenza"),
    # --- trattati: affari-esteri solo se internazionale ---
    ("Ratifica ed esecuzione dell'Accordo tra Italia e Francia", "affari-esteri"),
    ("Ratifica ed esecuzione del Trattato per il bando degli esperimenti nucleari", "affari-esteri"),
    (
        "Ratifica, con modificazioni, del decreto legislativo 2 maggio 1947, n. 499, "
        "concernente il riordinamento dei ruoli organici degli insegnanti elementari.",
        "istruzione",
    ),
]


@pytest.mark.parametrize(("oggetto", "attesa"), CASI, ids=[f"{i:02d}" for i in range(len(CASI))])
def test_classifica_oggetto(oggetto, attesa):
    assert _classifica_oggetto(oggetto) == attesa


def test_parola_intera_coerente_con_le_keyword():
    """`_PAROLA_INTERA` è una lista manuale: ogni voce deve esistere in `_TEMI`."""
    keyword = {kw for _, kws in _TEMI for kw in kws}
    assert _PAROLA_INTERA <= keyword, f"voci non presenti in _TEMI: {_PAROLA_INTERA - keyword}"


def test_strutturale_e_l_ultima_entry():
    """`strutturale` è fallback per posizione: deve restare l'ultima entry di `_TEMI`."""
    assert _TEMI[-1][0] == "strutturale"
