"""Costruisce il grafo dei riferimenti normativi: archi orientati fonte → bersaglio.

Legge tutti i file .md delle collezioni legislative, estrae i link relativi ../,
li risolve in path assoluti del corpus, e produce un dataset con archi, peso e
metadati (anno, collezione, tipo) arricchiti da normativa.parquet.

Output: data/derived/riferimenti.parquet

Uso: python -m lab_tools.grafo_riferimenti
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

from lab_tools._paths import COLLEZIONI_ROOT, OUTDIR, collezioni_legislative
from lab_tools.classifica_riferimenti import clausola_di_lettura
from lab_tools.identity import build_indice_identita, data_codice
from lab_tools.text_clean import pulisci_markup
from lab_tools.urn import annual_key, expand_index, full_key
from lab_tools.urn import lookup as urn_lookup
from lab_tools.urn import regola as urn_regola

logger = logging.getLogger(__name__)

NORMATIVA_PARQUET = OUTDIR / "normativa.parquet"

RE_LINK = re.compile(r'\.\./([^)]+?)\.md')

# Soglia dell'invariante: **bersagli distinti** regex non risolti ammessi.
# Oggi 6 (gli XML che il fetch non è riuscito a convertire); prima del churn
# erano ~6-11, dopo il churn 1.262. Il conteggio per bersaglio (non per link)
# rende il gate robusto a quanti link puntano allo stesso atto mancante.
MAX_REGEX_BERSAGLI_NON_RISOLTI = 50

# ---------------------------------------------------------------------------
# Dominio identitario del bersaglio
# ---------------------------------------------------------------------------
# Il grafo mescola almeno tre spazi di nomi, e trattarli come uno solo è la
# causa principale dei "non risolti" gonfiati:
#   - `nir`   normativa statale, identità nel catalogo Normattiva (atti_index)
#   - `ue`    diritto UE: l'identità vera è CELEX, non l'URN NIR. Nel corpus
#             circola in due grafie (`direttivaue` / `direttiva.ue`) per la
#             stessa entità: ~5.229 bersagli distinti sul corpus 2026-11
#   - `altro` atti di autorità indipendenti, circolari, pareri (nessun URN
#             Normattiva per costruzione) e URN malformati dalla fonte
#             (`urn:nir:::1928-02-05;577`)
DOMINIO_NIR = "nir"
DOMINIO_UE = "ue"
DOMINIO_ALTRO = "altro"

# L'emettitore dell'URN UE è `eu` (non `ue`, che è il dominio): due lettere
# invertite sono una trappola silenziosa, quindi la costante è esplicita.
EMITTENTE_UE = "eu"

# Esito dell'identificazione del bersaglio. Sostituisce la lettura binaria di
# `risolto`, che misurava solo la presenza **nel corpus** (~10% del catalogo) e
# faceva sembrare un difetto ciò che è solo fuori perimetro: sul corpus 2026-11
# il 60,3% degli archi AKN era "non risolto", ma il 63,8% di quei bersagli era
# già noto (catalogo Normattiva oppure direttiva UE).
ESITO_IN_CORPUS = "in_corpus"
ESITO_IN_CATALOGO = "in_catalogo"
ESITO_DOMINIO_UE = "dominio_ue"
ESITO_FUORI_PERIMETRO = "fuori_perimetro"
ESITO_SENZA_BERSAGLIO = "senza_bersaglio"

ESITI = (
    ESITO_IN_CORPUS,
    ESITO_IN_CATALOGO,
    ESITO_DOMINIO_UE,
    ESITO_FUORI_PERIMETRO,
    ESITO_SENZA_BERSAGLIO,
)

# Max context length stored per side (chars). Total evidence ≤ 2 * _CTX_MAX + link text.
_CTX_MAX = 120


def _build_file_set() -> set[str]:
    """Path dei .md relativi a COLLEZIONI_ROOT (es. "Codici/x.md").

    Stesso formato di prima del move sotto collezioni/: il parquet
    non cambia contratto al prossimo build.
    """
    files: set[str] = set()
    for col_dir in collezioni_legislative():
        for f in col_dir.glob("*.md"):
            files.add(str(f.relative_to(COLLEZIONI_ROOT)))
    return files


def _load_normativa_lookup() -> dict[str, dict]:
    """Carica normativa.parquet e costruisce lookup filename → metadati."""
    try:
        import pandas as pd
    except ImportError:
        print("Errore: pandas necessario per leggere normativa.parquet.")
        return {}

    if not NORMATIVA_PARQUET.exists():
        print(f"Attenzione: {NORMATIVA_PARQUET} non trovato. Arricchimento saltato.")
        return {}

    df = pd.read_parquet(NORMATIVA_PARQUET)
    lookup: dict[str, dict] = {}
    for _, row in df.iterrows():
        fn = row.get("filename", "")
        if fn:
            lookup[fn] = {
                "urn": row.get("urn", "") or "",
                "collezione": row.get("collezione", ""),
                "anno_atto": row.get("anno_atto", 0),
                # anno dell'espressione: c'è solo sulle VIGENZA
                "snapshot_data": row.get("snapshot_data"),
                "numero": row.get("numero", ""),
                "tipo": row.get("tipo", ""),
                "materia": row.get("materia", ""),
                "stato": row.get("stato", ""),
                # identità (#88): serve a scegliere l'espressione corrente quando
                # lo stesso atto ha più versioni nel corpus
                "is_current": bool(row.get("is_current", False)),
            }
    return lookup


def estrai_link(body: str) -> list[str]:
    """Estrae i path dei link ../ da un body markdown, decodificati."""
    links = RE_LINK.findall(body)
    return [urllib.parse.unquote(link) + ".md" for link in links]


def estrai_link_con_contesto(body: str) -> list[tuple[str, str]]:
    """Estrae (path_decodificato, contesto) per ogni link ../ nel body.

    Usa RE_LINK per i path (stessa semantica di findall, non-overlapping)
    e poi localizza ogni occorrenza per catturare il contesto ±_CTX_MAX char.

    Il contesto è lo snippet di testo attorno al link, usato come evidence
    nei riferimenti del grafo.

    Returns:
        Lista di (path_decodificato, contesto) — una riga per occorrenza,
        non deduplicata (il caller fa il counting per peso).
    """
    results: list[tuple[str, str]] = []
    # Copia lunga uguale: le posizioni dei link restano quelle del body.
    pulito = pulisci_markup(body)
    # Trova tutte le posizioni dei link con RE_LINK (non-overlapping, come findall)
    for m in RE_LINK.finditer(body):
        path_raw = m.group(1)
        path_decoded = urllib.parse.unquote(path_raw) + ".md"
        # Contesto: ±_CTX_MAX char attorno al match, con bound di sicurezza
        start = max(0, m.start() - _CTX_MAX)
        end = min(len(body), m.end() + _CTX_MAX)
        raw_ctx = pulito[start:end]
        # Normalizza whitespace
        contesto = re.sub(r'\s+', ' ', raw_ctx).strip()
        results.append((path_decoded, contesto))
    return results


def risolvi_path(link_decoded: str, current_relpath: Path) -> Path | None:
    """Risolve un link relativo ../ in path relativo a COLLEZIONI_ROOT.

    I path del corpus sono sorelle sotto collezioni/ (es.
    ``DL proroghe/x.md`` → link ``../Codici/y.md`` → ``Codici/y.md``).

    Args:
        link_decoded: path decodificato (es. 'Codici/y.md')
        current_relpath: path del file corrente relativo a COLLEZIONI_ROOT

    Returns:
        Path relativo a COLLEZIONI_ROOT oppure None se non risolvibile.
    """
    parent = current_relpath.parent
    if str(parent) == ".":
        return None  # file in root collezioni, ../ salirebbe sopra
    resolved = (parent.parent / link_decoded)
    # Normalizza senza risolvere symlink/FS: solo rimozione di . e ..
    parts: list[str] = []
    for part in resolved.parts:
        if part == "..":
            if parts:
                parts.pop()
        elif part != ".":
            parts.append(part)
    if not parts:
        return None
    return Path(*parts)


def dominio_urn(urn: str | None) -> str:
    """Dominio identitario dell'URN di un bersaglio: `nir` | `ue` | `altro`.

    Pura. Vuota per URN assente.

    Il riconoscimento è deliberatamente sintattico: non serve un registro per
    sapere che `urn:nir:eu:direttivaue:1996;23` non è normativa statale. Le due
    grafie UE (`direttivaue`, `direttiva.ue`) collassano sullo stesso dominio.
    """
    u = (urn or "").strip()
    if not u:
        return ""
    if not u.startswith("urn:nir:"):
        return DOMINIO_ALTRO
    parts = u.split(":")
    emittente = parts[2] if len(parts) > 2 else ""
    tipo = parts[3] if len(parts) > 3 else ""
    if emittente == EMITTENTE_UE or tipo.startswith("direttiva"):
        return DOMINIO_UE
    if not emittente or not tipo:
        # `urn:nir:::1928-02-05;577` / `urn:nir::regolamento:1907;90`: la fonte
        # (o la nostra normalizzazione) ha perso emettitore o tipo.
        return DOMINIO_ALTRO
    return DOMINIO_NIR


def anno_espressione(meta: dict) -> int | None:
    """Anno dell'**espressione** letta dal corpus (non dell'atto).

    `snapshot_data` esiste solo sulle VIGENZA (14.831/14.831) e data lo snapshot
    consolidato: il testo può citare atti fino a quell'anno. Gli ORIGINALE non
    hanno snapshot e non possono citare atti successivi, quindi vale l'anno
    dell'atto.

    Serve alla guardia temporale dei consumer: `anno_atto` su un atto del 1874
    con testo consolidato al 2025 fa scartare come "impossibili" 6.379 coppie
    legittime (misurato su legal-graph 2026-11).
    """
    snap = meta.get("snapshot_data")
    if hasattr(snap, "year"):  # datetime/Timestamp (pandas)
        return int(snap.year)
    if isinstance(snap, str) and len(snap) >= 4 and snap[:4].isdigit():
        return int(snap[:4])
    try:
        return int(meta.get("anno_atto"))
    except (TypeError, ValueError):
        return None


def esito_bersaglio(arco: dict, catalogo_urns: set[str]) -> str:
    """Esito dell'identificazione del bersaglio di un arco.

    Pura. Precedenza: corpus > dominio UE > catalogo > perimetro.

    `catalogo_urns` è l'insieme delle URN del catalogo Normattiva
    (`atti_index`). Se è vuoto (raw non disponibile) il meglio che si può dire
    è "fuori perimetro": `in_catalogo` non viene mai emesso per caso.
    """
    if arco.get("risolto"):
        return ESITO_IN_CORPUS
    urn = (arco.get("bersaglio_urn") or "").strip()
    if not urn:
        return ESITO_SENZA_BERSAGLIO
    # Il dominio già calcolato può venire dall'evidenza (CELEX), non solo
    # dalla sintassi dell'URN: ha precedenza.
    if (arco.get("dominio_bersaglio") or dominio_urn(urn)) == DOMINIO_UE:
        return ESITO_DOMINIO_UE
    if urn in catalogo_urns:
        return ESITO_IN_CATALOGO
    return ESITO_FUORI_PERIMETRO


def _verifica_esiti(archi: list[dict], catalogo_disponibile: bool) -> None:
    """Invariante: `risolto` ed `esito` non possono divergere.

    `risolto` resta la verità sulla presenza nel corpus; `esito` la raffina.
    Se divergono, un consumer che legge l'uno o l'altro ottiene risposte
    diverse sullo stesso arco: è esattamente il bug di denominatore che questo
    campo esiste per chiudere.
    """
    incoerenti = [
        a
        for a in archi
        if bool(a.get("risolto")) != (a.get("esito") == ESITO_IN_CORPUS)
    ]
    if incoerenti:
        es = incoerenti[0]
        raise ValueError(
            f"invariante esito/risolto: {len(incoerenti)} archi incoerenti "
            f"(es. risolto={es.get('risolto')} esito={es.get('esito')} "
            f"bersaglio={es.get('bersaglio_urn')})"
        )
    senza_esito = [a for a in archi if a.get("esito") not in ESITI]
    if senza_esito:
        raise ValueError(
            f"invariante esito: {len(senza_esito)} archi con esito non valido "
            f"(es. {senza_esito[0].get('esito')!r})"
        )
    if not catalogo_disponibile:
        in_catalogo = sum(1 for a in archi if a.get("esito") == ESITO_IN_CATALOGO)
        if in_catalogo:
            raise ValueError(
                f"invariante esito: {in_catalogo} archi 'in_catalogo' senza "
                "catalogo caricato (atti_index assente): classificazione non valida"
            )


def _verifica_celex(archi: list[dict]) -> None:
    """Invariante: il CELEX si attribuisce solo ai bersagli del dominio UE.

    Un CELEX su un atto NIR sarebbe un'identità sbagliata, cioè peggio di
    nessuna identità: il consumatore farebbe un join su un nodo sbagliato.
    """
    sporchi = [
        a
        for a in archi
        if a.get("bersaglio_celex") and a.get("dominio_bersaglio") != DOMINIO_UE
    ]
    if sporchi:
        es = sporchi[0]
        raise ValueError(
            f"invariante CELEX: {len(sporchi)} archi con CELEX fuori dal dominio UE "
            f"(es. dominio={es.get('dominio_bersaglio')} urn={es.get('bersaglio_urn')})"
        )


def _stampa_metriche(archi: list[dict], file_set_size: int):
    """Stampa metriche riassuntive del grafo."""
    total = len(archi)
    if total == 0:
        print("Nessun arco estratto.")
        return

    citati = set(
        (a.get("bersaglio_urn") or a["bersaglio_filename"]) for a in archi
    )
    fonti = set(a["fonte_filename"] for a in archi)
    risolti = sum(1 for a in archi if a["risolto"])
    non_risolti = total - risolti
    fuori_corpus = sum(
        1 for a in archi if a.get("origine") == "akn" and not a["risolto"]
    )
    by_orig = Counter(a.get("origine", "regex") for a in archi)

    print("\n📊 Grafo riferimenti — metriche")
    print(f"{'='*40}")
    print(f"  Archi totali:        {total:>8,}")
    print(f"  Risolvibili:         {risolti:>8,} ({risolti/total*100:.1f}%)" if total else "")
    print(f"  Non risolvibili:     {non_risolti:>8,} ({non_risolti/total*100:.1f}%)" if total else "")
    print(f"  Di cui AKN fuori corpus (URN): {fuori_corpus:>8,}")
    print(f"  Per origine:         {dict(by_orig)}")
    print(f"  Atti citanti (fonti): {len(fonti):>8,}")
    print(f"  Atti citati (bers.): {len(citati):>8,}")
    print(f"  File nel corpus:     {file_set_size:>8,}")

    # Esito dell'identificazione: la metrica che sostituisce il binario
    # "risolto/non risolto". `in_catalogo` + `dominio_ue` sono bersagli NOTI,
    # solo fuori dal corpus: leggerli come "mancanti" gonfiava il problema.
    esiti = Counter(a.get("esito", "") for a in archi)
    print("\n  Esito identificazione bersaglio:")
    noti = 0
    for k in ESITI:
        n = esiti.get(k, 0)
        if k in (ESITO_IN_CORPUS, ESITO_IN_CATALOGO, ESITO_DOMINIO_UE):
            noti += n
        print(f"    {k:<18} {n:>8,} ({n / total * 100:5.1f}%)")
    if total:
        print(f"    {'→ identificati':<18} {noti:>8,} ({noti / total * 100:5.1f}%)")

    # Ponte CELEX: delle direttive UE citate, quante hanno un'identità CELEX.
    # È la differenza tra "atto noto" e "atto agganciabile ai nodi UE".
    ue = [a for a in archi if a.get("dominio_bersaglio") == DOMINIO_UE]
    if ue:
        con_celex = sum(1 for a in ue if a.get("bersaglio_celex"))
        bersagli = {(a.get("bersaglio_urn") or "").strip() for a in ue}
        bersagli_celex = {
            (a.get("bersaglio_urn") or "").strip() for a in ue if a.get("bersaglio_celex")
        }
        celex_distinti = {a["bersaglio_celex"] for a in ue if a.get("bersaglio_celex")}
        print("\n  Ponte CELEX (direttive UE):")
        print(f"    archi con CELEX:   {con_celex:>8,} / {len(ue):,} ({con_celex / len(ue) * 100:5.1f}%)")
        print(f"    bersagli distinti: {len(bersagli_celex):>8,} / {len(bersagli):,}")
        print(f"    CELEX distinti:    {len(celex_distinti):>8,}")

    # Top citati (solo risolti)
    if risolti > 0:
        counter = Counter()
        for a in archi:
            if a["risolto"] and a.get("rel_type") == "citation":
                counter[(a["bersaglio_filename"])] += a["peso"]
        print("\n  Top 10 atti più citati:")
        for path, count in counter.most_common(10):
            short = path[:70]
            print(f"    {count:5d}x  {short}")


def _load_urn_to_relpath() -> dict[str, str]:
    """urn -> relpath reale (con `/`) per il join AKN.

    `normativa.parquet` dà urn -> basename; il filesystem dà basename ->
    relpath. Lo stesso basename può stare in 2+ collezioni (3.128 casi sul
    corpus): si sceglie il primo path ordinato, in modo deterministico. L'URN —
    e quindi il nodo — non cambia; cambia solo il path, che deve esistere.
    """
    try:
        import pandas as pd
    except ImportError:
        return {}
    if not NORMATIVA_PARQUET.exists():
        return {}

    by_name: dict[str, list[str]] = {}
    for rel in _build_file_set():
        by_name.setdefault(Path(rel).name, []).append(rel)

    df = pd.read_parquet(NORMATIVA_PARQUET, columns=["urn", "filename"])
    df = df.dropna(subset=["urn"])
    pairs = []
    for urn, name in zip(df["urn"], df["filename"]):
        candidati = by_name.get(name)
        pairs.append((urn, sorted(candidati)[0] if candidati else name))
    # alias (slug, anno+numero, codici): vedi lab_tools/urn.py
    return expand_index(pairs)


def _chiave_arco(a: dict) -> tuple[str, str, str]:
    """Chiave dell'arco = PK del clean (fonte_source_path, bersaglio_source_path,
    origine), derivata **esattamente** come in
    `datasets/riferimenti/sql/clean.sql`.

    Attenzione al caso **regex non risolto**: `bersaglio_path` è vuoto e la PK
    usa `bersaglio_filename` (il link grezzo). Usare `bersaglio_path` nudo
    fonderebbe tutti gli unresolved di un file in una sola chiave.

    Per le citation **AKN non risolte** non esiste alcun filename: la PK usa
    `bersaglio_urn` (atto fuori corpus, es. L. 241/1990).

    La chiave include `rel_type`: citation e abroga vivono nello stesso file e
    il mart le distingue, quindi il dedup non deve collassarle.
    """
    fonte_fn = a.get("fonte_filename") or ""
    bersaglio_fn = a.get("bersaglio_filename") or ""
    fonte_col = a.get("fonte_collezione") or ""
    bersaglio_path = a.get("bersaglio_path") or ""

    if "/" in fonte_fn:
        fonte_source_path = fonte_fn
    elif fonte_col:
        fonte_source_path = f"{fonte_col}/{fonte_fn}"
    else:
        fonte_source_path = fonte_fn

    if bersaglio_path:
        bersaglio_source_path = bersaglio_path
    elif bersaglio_fn and "/" in bersaglio_fn:
        bersaglio_source_path = bersaglio_fn
    elif bersaglio_fn:
        bersaglio_source_path = f"{fonte_col}/{bersaglio_fn}" if fonte_col else bersaglio_fn
    elif a.get("bersaglio_urn"):
        # citation AKN verso un atto **fuori corpus**: non esiste un filename,
        # l'identità stabile del bersaglio è l'URN.
        bersaglio_source_path = a["bersaglio_urn"]
    elif a.get("bersaglio_id"):
        # bersaglio che non è un atto (es. articolo della Costituzione):
        # l'identità stabile è l'id del nodo, non un filename/URN NIR.
        bersaglio_source_path = a["bersaglio_id"]
    else:
        bersaglio_source_path = ""

    return (
        fonte_source_path,
        bersaglio_source_path,
        a.get("origine") or "",
        a.get("rel_type") or "citation",
    )


def _dedup_archi(archi: list[dict]) -> list[dict]:
    """Un arco per chiave (vedi `_chiave_arco`), `peso` sommato.

    L'alias URN (`lab_tools/urn.py`) risolve forme diverse della stessa
    citazione sullo stesso file: senza dedup due righe AKN produrrebbero lo
    stesso arco e la PK del clean fallirebbe.
    """
    distinti: dict[tuple[str, str, str], dict] = {}
    for a in archi:
        k = _chiave_arco(a)
        if k in distinti:
            distinti[k]["peso"] += a["peso"]
        else:
            distinti[k] = a
    return list(distinti.values())


def _verifica_pk_unica(archi: list[dict]) -> None:
    """Solleva se la PK del clean non è unica.

    Usata **dopo** `_dedup_archi`: è un'invariante di costruzione, non una
    guardia sui dati grezzi (una guardia sui grezzi fallirebbe per condizioni
    legittime, es. link regex non risolti).
    """
    chiavi = [_chiave_arco(a) for a in archi]
    if len(chiavi) != len(set(chiavi)):
        raise AssertionError(
            f"dedup incompleto: {len(chiavi) - len(set(chiavi))} archi duplicati sulla PK"
        )


def _urn_anno_tipo(urn: str) -> tuple[int, str]:
    """(anno, tipo) leggibili da un URN NIR, anche senza giorno/mese.

    Serve solo ai bersagli **fuori corpus**, per cui non c'è una riga di
    `normativa.parquet` da cui prendere anno e tipo.
    """
    m = re.match(r"^urn:nir:[^:]+:([^:]+):(\d{4})", (urn or "").strip())
    if not m:
        return (0, "")
    return (int(m.group(2)), m.group(1))


_ATTI_INDEX_PUBBLICATO = (
    "https://storage.googleapis.com/dataciviclab-clean/italia-corpus/"
    "atti_index/2026/atti_index_2026_clean.parquet"
)

# Ponte CELEX: le direttive UE citate dal corpus non hanno un URN NIR stabile.
# `direttive_ue` (fetch CELLAR) porta CELEX + le due grafie in `urn_varianti`,
# quindi il ponte è un join esatto, non una ricostruzione.
_DIRETTIVE_UE_PUBBLICATO = (
    "https://storage.googleapis.com/dataciviclab-clean/italia-corpus/"
    "direttive_ue/2026/direttive_ue_2026_clean.parquet"
)

# CELEX: 3 + anno(4) + tipo(1) + numero. Es. 31989L0391.
_CELEX_RE = re.compile(r"^3(\d{4})([A-Z])(\d+)$")
# Forma URN delle direttive: ricopre `direttivaue` e `direttiva.ue`.
_URN_UE_RE = re.compile(r"direttiva\.?ue:(\d{4});(\d+)$")


def _scarica_atti_index_pubblicato():
    """Fallback: clean pubblicato (una GET, ~11MB) quando il raw locale manca.

    Nel build il grafo gira **prima** di `make atti-index`: senza fallback la
    mappa è vuota e i bersagli restano con la URN grezza (`indice URN
    catalogo: 0 chiavi`). Usa il clean dell'ultimo publish: un atto creato
    dopo resta non canonicalizzato fino al run successivo.

    Ritorna None se non raggiungibile (grafo offline): nessun errore.
    """
    import tempfile

    import requests

    tmp: Path | None = None
    try:
        # path assegnato **prima** della richiesta: se il download muore a
        # metà, l'except può cancellare il file (delete=False).
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            tmp = Path(f.name)
            with requests.get(_ATTI_INDEX_PUBBLICATO, timeout=(10, 60), stream=True) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
    except Exception as exc:  # rete/WAF/HTTP: il grafo resta con le URN grezze
        print(f"  atti_index pubblicato non raggiungibile ({exc}): URN grezza")
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        return None
    try:
        import pandas as pd

        return pd.read_parquet(tmp, columns=["urn"])
    except Exception as exc:  # parquet corrotto
        print(f"  atti_index pubblicato illeggibile ({exc}): URN grezza")
        return None
    finally:
        tmp.unlink(missing_ok=True)


def _load_atti_index_urn() -> dict[tuple, str]:
    """Mappa -> URN canonica del catalogo, con due chiavi possibili.

    - `("full", emittente, tipo_slug, data, numero)`: risolve anche quando due
      atti condividono anno+numero ma hanno date diverse;
    - `("annual", emittente, tipo_slug, anno, numero)`: fallback per le
      citazioni senza giorno/mese.

    Solo chiavi univoche (stessa guardia di `urn.expand_index`). Se il raw
    locale manca (build: grafo prima di `make atti-index`) usa il clean
    pubblicato; se anche quello manca, il grafo resta con la URN grezza.
    """
    path = OUTDIR / "atti_index.parquet"
    df = None
    if path.exists():
        try:
            import pandas as pd

            df = pd.read_parquet(path, columns=["urn"])
        except (OSError, ValueError, KeyError) as exc:
            print(f"  atti_index.parquet illeggibile ({exc}): provo il pubblicato")
    if df is None:
        df = _scarica_atti_index_pubblicato()
    if df is None:
        return {}

    annuali: dict[tuple, list[str]] = defaultdict(list)
    completi: dict[tuple, list[str]] = defaultdict(list)
    for urn in df["urn"].dropna():
        k = annual_key(urn)
        if k:
            annuali[k].append(urn)
        fk = full_key(urn)
        if fk:
            completi[fk].append(urn)

    out: dict[tuple, str] = {}
    for k, v in completi.items():
        if len(set(v)) == 1:
            out[("full",) + k] = v[0]
    for k, v in annuali.items():
        if len(set(v)) == 1:
            out[("annual",) + k] = v[0]
    return out


def _urn_canonico(urn: str, indice: dict[tuple, str]) -> str:
    """URN canonica del catalogo per un bersaglio fuori corpus, se nota."""
    grezza = (urn or "").strip()
    if not grezza or not indice:
        return grezza
    for tag, k in (("full", full_key(grezza)), ("annual", annual_key(grezza))):
        if k and (tag,) + k in indice:
            return indice[(tag,) + k]
    return grezza


def _scarica_direttive_ue_pubblicate():
    """Fallback: clean pubblicato di `direttive_ue` se il raw locale manca.

    Nel build il grafo gira **prima** di `fetch_direttive_ue` e i raw scaricati
    dal layer non includono `direttive_ue` (`make fetch-raws` sì, ma il build
    ne salta il fetch). Senza fallback il ponte CELEX sarebbe vuoto proprio
    nel run settimanale.

    Ritorna None se non raggiungibile: il ponte degrada a "nessun CELEX".
    """
    import tempfile

    import requests

    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            tmp = Path(f.name)
            with requests.get(_DIRETTIVE_UE_PUBBLICATO, timeout=(10, 60), stream=True) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
    except Exception as exc:  # rete/WAF/HTTP: il ponte resta vuoto
        print(f"  direttive_ue pubblicate non raggiungibili ({exc}): nessun CELEX")
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        return None
    try:
        import pandas as pd

        return pd.read_parquet(tmp, columns=["celex", "urn_varianti"])
    except Exception as exc:
        print(f"  direttive_ue pubblicate illeggibili ({exc}): nessun CELEX")
        return None
    finally:
        tmp.unlink(missing_ok=True)


def _chiave_ue(anno, numero) -> tuple[int, int] | None:
    """Chiave (anno, numero) di una direttiva, da URN o da CELEX."""
    try:
        a, n = int(anno), int(numero)
    except (TypeError, ValueError):
        return None
    return (a, n) if a and n else None


def _carica_indice_celex() -> tuple[dict[str, str], dict[tuple[int, int], str]]:
    """Indice URN -> CELEX delle direttive UE, con due chiavi.

    - **esatta**: `urn_varianti` elenca già le due grafie che circolano
      nell'AKN (`direttivaue` / `direttiva.ue`) → copre il 98,5% dei bersagli;
    - **(anno, numero)**: fallback per le forme che `urn_varianti` non elenca,
      ricavate dal CELEX. Recupera ~78 bersagli su 5.229.

    Chiavi ambigue (stessa URN → CELEX diversi) vengono scartate: meglio
    nessuna identità che un'identità sbagliata. `({}, {})` se la fonte manca.
    """
    path = OUTDIR / "direttive_ue.parquet"
    df = None
    if path.exists():
        try:
            import pandas as pd

            df = pd.read_parquet(path, columns=["celex", "urn_varianti"])
        except (OSError, ValueError, KeyError) as exc:
            print(f"  direttive_ue.parquet illeggibile ({exc}): provo il pubblicato")
    if df is None:
        df = _scarica_direttive_ue_pubblicate()
    if df is None:
        return {}, {}

    per_urn: dict[str, set[str]] = defaultdict(set)
    per_chiave: dict[tuple[int, int], set[str]] = defaultdict(set)
    for celex, varianti in zip(df["celex"], df["urn_varianti"]):
        c = (celex or "").strip()
        if not c:
            continue
        for v in str(varianti or "").split("|"):
            v = v.strip()
            if v:
                per_urn[v].add(c)
        m = _CELEX_RE.match(c)
        if m:
            k = _chiave_ue(m.group(1), m.group(3))
            if k:
                per_chiave[k].add(c)

    def _unici(src: dict) -> dict:
        return {k: next(iter(v)) for k, v in src.items() if len(v) == 1}

    return _unici(per_urn), _unici(per_chiave)


def risolvi_celex(
    urn: str | None,
    per_urn: dict[str, str],
    per_chiave: dict[tuple[int, int], str],
) -> str | None:
    """CELEX della direttiva UE citata, o None. Pura.

    Precedenza: join esatto sull'URN, poi (anno, numero) ricavato dall'URN.
    Solo direttive: i regolamenti sono nello stesso dominio ma su un altro
    asse CELEX (tipo R), che `direttive_ue` non copre.
    """
    u = (urn or "").strip()
    if not u:
        return None
    if u in per_urn:
        return per_urn[u]
    m = _URN_UE_RE.search(u)
    if not m:
        return None
    k = _chiave_ue(m.group(1), m.group(2))
    return per_chiave.get(k) if k else None


def _archi_da_abrogazioni(normativa: dict[str, dict]) -> list[dict]:
    """Archi `abroga` (regex) dentro il grafo dei riferimenti.

    Fonde `abrogations_raw.parquet` in `riferimenti.parquet` con
    `rel_type='abroga'` e target URN canonico (da `normativa`): legal-graph non
    legge più l'artefatto di staging. Stessa risoluzione anno+numero e stessa
    guardia temporale del vecchio `edges_abro` nel compose.

    Se il file manca (es. run parziale) salta senza errore.
    """
    path = OUTDIR / "abrogations_raw.parquet"
    if not path.exists():
        print("  abrogations_raw.parquet assente: archi abroga non aggiunti")
        return []
    try:
        import pandas as pd
    except ImportError:
        return []

    # target: (anno, numero) -> urn, solo da normativa (parità col compose)
    target: dict[tuple[int, str], set[str]] = defaultdict(set)
    for meta in normativa.values():
        urn = (meta.get("urn") or "").strip()
        anno = meta.get("anno_atto")
        numero = meta.get("numero")
        if urn and anno and numero not in (None, ""):
            # normalizza a intero come il vecchio `TRY_CAST(numero AS INTEGER)`
            try:
                target[(int(anno), str(int(numero)))].add(urn)
            except (TypeError, ValueError):
                continue

    archi: list[dict] = []
    try:
        df = pd.read_parquet(path)
    except (OSError, ValueError, KeyError) as exc:  # parquet corrotto / colonne assenti
        print(f"  abrogations_raw.parquet illeggibile ({exc}): archi abroga non aggiunti")
        return []
    for _, row in df.iterrows():
        f_file = str(row.get("abrogating_file") or "").strip()
        f_coll = str(row.get("abrogating_collection") or "").strip()
        f_meta = normativa.get(f_file, {})
        f_urn = (f_meta.get("urn") or "").strip()
        if not f_urn:
            continue
        try:
            anno = int(row.get("abrogated_year"))
            numero = str(int(row.get("abrogated_number")))
        except (TypeError, ValueError):
            continue
        f_anno = f_meta.get("anno_atto")
        for t_urn in sorted(target.get((anno, numero), set())):
            # guardia temporale: l'abrogante non può essere anteriore all'abrogato
            if f_anno and anno and f_anno < anno:
                continue
            archi.append(
                {
                    "fonte_filename": f"{f_coll}/{f_file}" if f_coll else f_file,
                    "fonte_urn": f_urn,
                    "fonte_collezione": f_coll,
                    "fonte_anno": f_meta.get("anno_atto", 0),
                    "fonte_anno_espressione": anno_espressione(f_meta),
                    "fonte_tipo": f_meta.get("tipo", ""),
                    "fonte_materia": f_meta.get("materia", ""),
                    "fonte_stato": f_meta.get("stato", ""),
                    # il bersaglio è un atto risolto via anno+numero: nessun file
                    "bersaglio_filename": "",
                    "bersaglio_path": "",
                    "bersaglio_urn": t_urn,
                    "bersaglio_collezione": "",
                    "bersaglio_anno": anno,
                    "bersaglio_tipo": "",
                    "bersaglio_materia": "",
                    "bersaglio_stato": "",
                    "peso": 1,
                    "risolto": True,
                    "origine": "regex",
                    "rel_type": "abroga",
                    "contesto": str(row.get("context") or ""),
                    "clausola_lettura": None,
                }
            )
    print(f"  AKN/abrogazioni: {len(archi)} archi abroga")
    return archi


def _archi_citazioni(records: list[dict], normativa: dict[str, dict]) -> list[dict]:
    """Mappa le citazioni costituzionali in archi del grafo dei riferimenti.

    Il bersaglio non è un atto ma un articolo: `bersaglio_id` porta
    `costituzione:art:N`, `bersaglio_urn` resta vuota (non è una URN NIR).
    `origine='costituzione'` distingue queste righe da regex/AKN, così
    `riferimenti` resta l'unico artefatto pubblicato anche per i target
    non-atto.
    """
    archi: list[dict] = []
    for row in records:
        try:
            articolo = int(row.get("articolo"))
        except (TypeError, ValueError):
            continue
        fonte_fn = str(row.get("fonte_filename") or "")
        meta = normativa.get(fonte_fn.rsplit("/", 1)[-1], {})
        contesto = str(row.get("contesto") or "")[:300]
        archi.append(
            {
                "fonte_filename": fonte_fn,
                "fonte_urn": (meta.get("urn") or "").strip(),
                "fonte_collezione": row.get("fonte_collezione") or meta.get("collezione", ""),
                "fonte_anno": row.get("fonte_anno") or meta.get("anno_atto", 0),
                "fonte_anno_espressione": anno_espressione(meta),
                "fonte_tipo": row.get("fonte_tipo") or meta.get("tipo", ""),
                "fonte_materia": meta.get("materia", ""),
                "fonte_stato": meta.get("stato", ""),
                # il bersaglio non è un atto: nessun filename/path/URN
                "bersaglio_filename": "",
                "bersaglio_path": "",
                "bersaglio_urn": "",
                "bersaglio_id": f"costituzione:art:{articolo}",
                "bersaglio_collezione": "",
                "bersaglio_anno": 0,
                "bersaglio_tipo": "",
                "bersaglio_materia": "",
                "bersaglio_stato": "",
                "peso": 1,
                "risolto": True,
                "origine": "costituzione",
                "rel_type": "cita_costituzione",
                "contesto": contesto,
                "clausola_lettura": clausola_di_lettura(contesto),
            }
        )
    return archi


def _archi_da_citazioni_costituzionali(normativa: dict[str, dict]) -> list[dict]:
    """Archi `cita_costituzione` dallo staging di `estrai_citazioni`.

    Se lo staging manca (run parziale) salta senza errore, come le abrogazioni.
    """
    path = OUTDIR / "_citazioni_stage.parquet"
    if not path.exists():
        print("  _citazioni_stage.parquet assente: archi costituzionali non aggiunti")
        return []
    try:
        import pandas as pd
    except ImportError:
        return []
    try:
        df = pd.read_parquet(path)
    except (OSError, ValueError, KeyError) as exc:
        print(f"  _citazioni_stage.parquet illeggibile ({exc}): archi cost. non aggiunti")
        return []
    archi = _archi_citazioni(df.to_dict("records"), normativa)
    print(f"  citazioni costituzionali: {len(archi)} archi")
    return archi


def _archi_da_akn_relations(
    normativa: dict[str, dict],
    urn_to_fn: dict[str, str],
    atti_urn: dict[tuple[str, str, str, str], str] | None = None,
) -> list[dict]:
    """Citation AKN (origin=ref) con la **fonte** nel corpus.

    Il bersaglio può essere fuori corpus (leggi ordinarie assenti dalle
    collezioni, es. L. 241/1990): l'arco si emette comunque con
    ``risolto=False`` e ``bersaglio_urn`` valorizzato. Scartarlo perderebbe la
    citazione — 19.700 bersagli / ~180.000 citazioni sul corpus 2026-11 — e
    legal-graph non potrebbe agganciarla ai nodi (`atti_api`, stub).
    Se manca la fonte l'arco non è attribuibile e viene saltato.

    Aggiunge archi con origine='akn', peso=1. Non sovrascrive il grafo regex:
    il consumatore distingue da colonna `origine`.
    """
    akn_path = OUTDIR / "akn_relations.parquet"
    if not akn_path.exists() or not urn_to_fn:
        print("  akn_relations.parquet assente o nessun URN — union AKN saltata")
        return []

    try:
        import pandas as pd
    except ImportError:
        return []

    df = pd.read_parquet(akn_path)
    if df.empty or "origin" not in df.columns:
        return []
    cit = df[df["origin"] == "ref"].copy()
    if cit.empty:
        # Non uscire: il blocco `repeal` più sotto è indipendente dalle
        # citation (un atto può abrogare senza citare).
        print("  Nessuna citation AKN")

    archi: list[dict] = []
    n_skip_fonte = 0
    n_risolti = 0
    n_fuori_corpus = 0
    per_regola: Counter[str] = Counter()

    for _, row in cit.iterrows():
        f_urn, t_urn = row.get("fonte_urn"), row.get("target_urn")
        f_fn = urn_lookup(urn_to_fn, f_urn)
        if not f_fn:
            # fonte assente dal corpus: l'arco non è attribuibile a un atto
            n_skip_fonte += 1
            continue
        t_fn = urn_lookup(urn_to_fn, t_urn)
        is_risolto = bool(t_fn)
        if is_risolto:
            n_risolti += 1
            per_regola[urn_regola(urn_to_fn, t_urn) or "?"] += 1
        else:
            # atto fuori corpus: la citazione non si butta, si aggancia all'URN
            n_fuori_corpus += 1

        f_meta = normativa.get(Path(f_fn).name, {})
        t_meta = normativa.get(Path(t_fn).name, {}) if is_risolto else {}
        anno_urn, tipo_urn = _urn_anno_tipo(t_urn)
        if is_risolto:
            bersaglio_urn = (t_meta.get("urn", "") or "").strip() or (t_urn or "").strip()
        else:
            # fuori corpus: URN canonica del catalogo (full, poi annuale), altrimenti grezza
            bersaglio_urn = _urn_canonico(t_urn, atti_urn or {})
        # pandas: le righe senza contesto sono NaN (float), non None/"".
        _contesto = row.get("contesto")
        contesto = _contesto.strip() if isinstance(_contesto, str) else ""
        archi.append(
            {
                "fonte_filename": f_fn,
                "fonte_collezione": Path(f_fn).parent.name,
                "fonte_anno": f_meta.get("anno_atto", 0),
                "fonte_anno_espressione": anno_espressione(f_meta),
                "fonte_tipo": f_meta.get("tipo", ""),
                "fonte_materia": f_meta.get("materia", ""),
                "fonte_stato": f_meta.get("stato", ""),
                "fonte_urn": (f_meta.get("urn", "") or "").strip(),
                "bersaglio_filename": Path(t_fn).name if is_risolto else "",
                "bersaglio_path": t_fn or "",
                # Identità del bersaglio: URN canonica (corpus o catalogo) se
                # nota, altrimenti la forma grezza dell'AKN. legal-graph fa
                # join esatto sui nodi.
                "bersaglio_urn": bersaglio_urn,
                "bersaglio_collezione": Path(t_fn).parent.name if is_risolto else "",
                "bersaglio_anno": t_meta.get("anno_atto", anno_urn),
                "bersaglio_tipo": t_meta.get("tipo", "") or tipo_urn,
                "bersaglio_materia": t_meta.get("materia", ""),
                "bersaglio_stato": t_meta.get("stato", ""),
                "peso": 1,
                "risolto": is_risolto,
                "origine": "akn",
                "rel_type": "citation",
                # Contesto catturato da akn_relations (paragrafo del <ref>).
                # pandas restituisce NaN (float) per le righe senza testo:
                # `nan or ""` è NaN (truthy) → niente .strip() diretto.
                "contesto": contesto or f"akn:{row.get('origin', 'ref')}",
                "clausola_lettura": clausola_di_lettura(contesto),
            }
        )

    # Due metriche separate: la copertura del lookup (target trovati) e il
    # volume delle citazioni emesse (include i bersagli fuori corpus).
    n_cit = len(cit)
    # Invariante: ogni riga di input finisce in **una** classe (fonte assente,
    # risolta, fuori corpus). Un `continue` non conteggiato in futuro non deve
    # passare in silenzio: era il gate che il rewrite di questa funzione aveva
    # perso.
    classificate = n_skip_fonte + n_risolti + n_fuori_corpus
    if classificate != n_cit:
        raise ValueError(
            f"conteggi AKN incoerenti: {classificate} classificati != {n_cit} righe di input"
        )
    # La soglia è un gate sul corpus intero: su input piccoli (test, smoke) il
    # rapporto non è informativo.
    if n_cit >= 100 and n_risolti / n_cit < 0.30:
        raise ValueError(
            f"invariante AKN: lookup risolve {n_risolti}/{n_cit} target "
            f"({n_risolti / n_cit:.1%}, soglia 30%) — possibile regressione di urn.lookup"
        )
    if n_cit:
        print(
            f"  AKN target risolti: {n_risolti}/{n_cit} ({n_risolti / n_cit:.1%}) · "
            f"fuori corpus: {n_fuori_corpus} · fonti assenti: {n_skip_fonte}"
        )
    print(f"  AKN per regola (bersaglio risolto): {dict(per_regola.most_common())}")
    print(f"  AKN citations emesse: {len(archi)}")

    # --- Abrogazioni AKN (repeal) ---------------------------------------
    # Stessa tabella delle citation: `rel_type` è la **relazione** ('abroga'),
    # `origine` l'estrattore ('akn' vs 'regex'). Il bersaglio è canonicalizzato
    # come per le citation, così un consumer può creare il nodo dal catalogo e
    # collegare l'arco senza riimplementare l'identità (come già per CELEX).
    rep = df[(df["origin"] == "activeModification") & (df["rel_type"] == "repeal")]
    n_rep = len(rep)
    n_rep_skip = 0
    n_rep_archi = 0
    for _, row in rep.iterrows():
        f_urn, t_urn = row.get("fonte_urn"), row.get("target_urn")
        f_fn = urn_lookup(urn_to_fn, f_urn)
        if not f_fn:
            # fonte fuori corpus: l'arco non è attribuibile a un atto
            n_rep_skip += 1
            continue
        f_meta = normativa.get(Path(f_fn).name, {})
        t_fn = urn_lookup(urn_to_fn, t_urn)
        is_risolto = bool(t_fn)
        t_meta = normativa.get(Path(t_fn).name, {}) if is_risolto else {}
        anno_urn, tipo_urn = _urn_anno_tipo(t_urn)
        if is_risolto:
            bersaglio_urn = (t_meta.get("urn", "") or "").strip() or (t_urn or "").strip()
        else:
            bersaglio_urn = _urn_canonico(t_urn, atti_urn or {})
        _contesto = row.get("contesto")
        contesto = _contesto.strip() if isinstance(_contesto, str) else ""
        archi.append(
            {
                "fonte_filename": f_fn,
                "fonte_collezione": Path(f_fn).parent.name,
                "fonte_anno": f_meta.get("anno_atto", 0),
                "fonte_anno_espressione": anno_espressione(f_meta),
                "fonte_tipo": f_meta.get("tipo", ""),
                "fonte_materia": f_meta.get("materia", ""),
                "fonte_stato": f_meta.get("stato", ""),
                "fonte_urn": (f_meta.get("urn", "") or "").strip(),
                "bersaglio_filename": Path(t_fn).name if is_risolto else "",
                "bersaglio_path": t_fn or "",
                "bersaglio_urn": bersaglio_urn,
                "bersaglio_collezione": Path(t_fn).parent.name if is_risolto else "",
                "bersaglio_anno": t_meta.get("anno_atto", anno_urn),
                "bersaglio_tipo": t_meta.get("tipo", "") or tipo_urn,
                "bersaglio_materia": t_meta.get("materia", ""),
                "bersaglio_stato": t_meta.get("stato", ""),
                "peso": 1,
                "risolto": is_risolto,
                "origine": "akn",
                "rel_type": "abroga",
                # `contesto` è vuoto su tutti i repeal: il segnaposto resta
                # coerente con quello delle citation AKN.
                "contesto": contesto or "akn:activeModification",
                "clausola_lettura": clausola_di_lettura(contesto),
            }
        )
        n_rep_archi += 1
    print(f"  AKN abroga emesse: {n_rep_archi} (fonti assenti: {n_rep_skip} su {n_rep})")

    # Dedup per coppia (fonte, bersaglio, origine): l'alias URN
    # (lab_tools/urn.py) fa risolvere forme diverse della stessa citazione sullo
    # stesso file, quindi due righe AKN possono produrre lo stesso arco.
    distinti = _dedup_archi(archi)
    if len(distinti) != len(archi):
        print(f"  AKN archi collassati (stessa coppia via alias URN): {len(archi) - len(distinti)}")
        print(f"  AKN archi distinti: {len(distinti)}")
    return distinti


def _risolvi_bersaglio(
    link_decoded: str,
    relpath: Path,
    file_set: set[str],
    indice_identita: dict[str, str],
) -> tuple[str | None, str, bool, bool]:
    """Risolvi un link per path e, se serve, per identità.

    Il fetch aggiorna gli snapshot e **cambia il filename** (`_ORIGINALE_` →
    `_VIGENZA_2026-02-25_`): un link al nome vecchio non è nel `file_set`. In
    quel caso si ripiega su `data_codice`, che è 1:1 con l'atto.

    Returns:
        (bersaglio_path, bersaglio_filename, risolto, via_identita)
    """
    resolved = risolvi_path(link_decoded, relpath)
    bersaglio_path = str(resolved) if resolved is not None else None

    if bersaglio_path and bersaglio_path in file_set:
        return bersaglio_path, Path(bersaglio_path).name, True, False

    cod = data_codice(link_decoded) or data_codice(bersaglio_path or "")
    candidato = indice_identita.get(cod) if cod else None
    if candidato:
        return candidato, Path(candidato).name, True, True

    fn = Path(bersaglio_path).name if bersaglio_path else link_decoded
    return bersaglio_path, fn, False, False


def _verifica_invarianti(archi: list[dict], file_set: set[str]) -> None:
    """Gate sulla risoluzione: blocca il run se il corpus è degradato.

    Non basta stampare le metriche: 11 → 44.079 link non risolti è passato
    silenzioso per un intero build. Questi controlli falliscono con i numeri
    nel messaggio (stessa forma del contract check di CI).
    """
    basenames = {Path(p).name for p in file_set}

    regex = [a for a in archi if a.get("origine") == "regex"]
    non_risolti = [a for a in regex if not a.get("risolto")]
    bersagli_non_risolti = {a.get("bersaglio_filename") for a in non_risolti}
    if len(bersagli_non_risolti) > MAX_REGEX_BERSAGLI_NON_RISOLTI:
        raise ValueError(
            f"invariante: {len(bersagli_non_risolti)} bersagli regex non risolti "
            f"({len(non_risolti)} link, max {MAX_REGEX_BERSAGLI_NON_RISOLTI} bersagli) "
            f"— possibile churn di filename: i link puntano a nomi vecchi "
            f"(vedi _risolvi_bersaglio)"
        )
    if bersagli_non_risolti:
        esempi = ", ".join(sorted(bersagli_non_risolti)[:6])
        print(
            f"  ⚠ bersagli non risolti (atti assenti dal corpus): "
            f"{len(bersagli_non_risolti)} ({len(non_risolti)} link) — {esempi}"
        )

    # I bersagli AKN fuori corpus devono conservare l'identità: senza URN la
    # citazione è stata emessa ma non è agganciabile da legal-graph.
    akn_senza_urn = [
        a
        for a in archi
        if a.get("origine") == "akn" and not a.get("risolto") and not a.get("bersaglio_urn")
    ]
    if akn_senza_urn:
        raise ValueError(
            f"invariante: {len(akn_senza_urn)} citation AKN fuori corpus senza "
            f"bersaglio_urn (es. fonte {akn_senza_urn[0].get('fonte_filename')})"
        )

    fantasmi = [
        a
        for a in archi
        if a.get("rel_type", "citation") == "citation"
        and a.get("risolto")
        and a.get("bersaglio_filename") not in basenames
    ]
    if fantasmi:
        raise ValueError(
            f"invariante: {len(fantasmi)} archi risolti su bersagli inesistenti "
            f"(es. {fantasmi[0].get('bersaglio_filename')})"
        )

    fonti_fantasma = [
        a
        for a in archi
        if a.get("risolto")
        and a.get("fonte_filename") not in file_set
        and a.get("fonte_filename") not in basenames
    ]
    if fonti_fantasma:
        # Diagnosi: sapere *quale* estrattore produce la fonte fantasma evita di
        # cercare nel posto sbagliato (stage stale ≠ corpus stale ≠ raw stale).
        per_origine: Counter[str] = Counter(
            str(a.get("origine", "?")) for a in fonti_fantasma
        )
        raise ValueError(
            f"invariante: {len(fonti_fantasma)} archi con fonte inesistente "
            f"per origine {dict(per_origine)} "
            f"(es. {fonti_fantasma[0].get('fonte_filename')})"
        )


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)

    print("Costruzione file set...")
    file_set = _build_file_set()
    print(f"  {len(file_set)} file .md trovati")

    print("Caricamento normativa.parquet...")
    normativa = _load_normativa_lookup()
    print(f"  {len(normativa)} atti caricati")

    # Indice identità: data_codice -> espressione corrente. Serve al fallback
    # quando il link punta a un filename che il fetch ha rinominato.
    correnti = {fn for fn, meta in normativa.items() if meta.get("is_current")}
    indice_identita = build_indice_identita(file_set, correnti)
    print(f"  indice identità: {len(indice_identita)} atti (data_codice)")

    print("Estrazione link dai body...")
    archi: list[dict] = []
    n_fallback_identita = 0
    for col_dir in collezioni_legislative():
        nome_collezione = col_dir.name
        for f in sorted(col_dir.glob("*.md")):
            relpath = f.relative_to(COLLEZIONI_ROOT)
            try:
                raw = f.read_text("utf-8", errors="replace")
            except OSError as e:
                logger.warning("lettura fallita %s: %s", f, e)
                continue

            links_ctx = estrai_link_con_contesto(raw)
            if not links_ctx:
                continue

            # Conta occorrenze per link unico + raccogli il contesto
            # (primo contesto trovato per ogni link unico, come evidence)
            peso_counter: dict[str, int] = {}
            contesto_first: dict[str, str] = {}
            for link_decoded, contesto in links_ctx:
                peso_counter[link_decoded] = peso_counter.get(link_decoded, 0) + 1
                if link_decoded not in contesto_first and contesto:
                    contesto_first[link_decoded] = contesto

            for link_decoded, peso in peso_counter.items():
                bersaglio_path, bersaglio_fn, risolto, via_identita = _risolvi_bersaglio(
                    link_decoded, relpath, file_set, indice_identita
                )
                if via_identita:
                    n_fallback_identita += 1

                # Metadati fonte
                fonte_meta = normativa.get(relpath.name, {})
                # Metadati bersaglio (solo se risolto)
                bersaglio_meta = normativa.get(bersaglio_fn, {}) if risolto else {}
                # Path vuoto se non risolto — il consumer non deve fare ipotesi
                bp = bersaglio_path if risolto else ""

                arco = {
                    "fonte_filename": str(relpath),
                    "fonte_collezione": nome_collezione,
                    "fonte_anno": fonte_meta.get("anno_atto", 0),
                    "fonte_anno_espressione": anno_espressione(fonte_meta),
                    "fonte_tipo": fonte_meta.get("tipo", ""),
                    "fonte_materia": fonte_meta.get("materia", ""),
                    "fonte_stato": fonte_meta.get("stato", ""),
                    "bersaglio_filename": bersaglio_fn,
                    "bersaglio_path": bp or "",
                    "fonte_urn": fonte_meta.get("urn", "") or "",
                    # Bersaglio risolto: URN canonica del corpus. Non risolto:
                    # vuota (i link regex non espongono un URN).
                    "bersaglio_urn": (bersaglio_meta.get("urn", "") or "") if risolto else "",
                    "bersaglio_collezione": bersaglio_meta.get("collezione", ""),
                    "bersaglio_anno": bersaglio_meta.get("anno_atto", 0),
                    "bersaglio_tipo": bersaglio_meta.get("tipo", ""),
                    "bersaglio_materia": bersaglio_meta.get("materia", ""),
                    "bersaglio_stato": bersaglio_meta.get("stato", ""),
                    "peso": peso,
                    "risolto": risolto,
                    "origine": "regex",
                    "rel_type": "citation",
                    "contesto": contesto_first.get(link_decoded, ""),
                    "clausola_lettura": clausola_di_lettura(
                        contesto_first.get(link_decoded, "")
                    ),
                }
                archi.append(arco)

    print("Union AKN (citation strutturate)...")
    urn_to_fn = _load_urn_to_relpath()
    atti_urn = _load_atti_index_urn()
    print(f"  indice URN catalogo: {len(atti_urn)} chiavi")
    archi.extend(_archi_da_akn_relations(normativa, urn_to_fn, atti_urn))
    archi.extend(_archi_da_abrogazioni(normativa))
    archi.extend(_archi_da_citazioni_costituzionali(normativa))

    # Un arco per chiave = PK del clean (fonte_source_path, bersaglio_source_path,
    # origine). Il dedup AKN copre la causa nota (alias URN); qui si applica
    # all'**unione** (regex + AKN) perché anche due link regex diversi possono
    # risolvere allo stesso bersaglio. `peso` sommato. Così la PK regge per
    # costruzione, invece di far fallire la build su una condizione di dato.
    n_prima = len(archi)
    archi = _dedup_archi(archi)
    if len(archi) != n_prima:
        print(f"  archi collassati sull'unione (PK clean): {n_prima - len(archi)}")
    _verifica_pk_unica(archi)

    # Esito dell'identificazione del bersaglio (additivo: `risolto` resta).
    # `in_catalogo` richiede atti_index: se il raw non c'è, l'esito degrada a
    # `fuori_perimetro` invece di inventare una classificazione.
    catalogo_urns = set(atti_urn.values()) if atti_urn else set()

    # Ponte CELEX: le direttive UE citate non hanno un URN NIR stabile, quindi
    # `dominio_ue` da solo dice "fuori perimetro" pur essendo un atto noto.
    # `direttive_ue` (CELLAR) porta CELEX + le due grafie: join esatto.
    celex_per_urn, celex_per_chiave = _carica_indice_celex()
    print(
        f"  indice CELEX: {len(celex_per_urn)} URN + "
        f"{len(celex_per_chiave)} chiavi anno/numero"
    )

    # Dominio: la sintassi dell'URN è il default, ma **l'evidenza vince**. Un
    # bersaglio che risolve a un CELEX è UE anche con emettitore vuoto
    # (`urn:nir::regolamento:2016;679`). Oggi l'effetto è sulle direttive; la
    # regola è già quella giusta per i regolamenti, quando arriverà l'asse R.
    for arco in archi:
        celex = risolvi_celex(arco.get("bersaglio_urn"), celex_per_urn, celex_per_chiave)
        dom = DOMINIO_UE if celex else dominio_urn(arco.get("bersaglio_urn"))
        arco["dominio_bersaglio"] = dom
        arco["bersaglio_celex"] = celex if dom == DOMINIO_UE else None
    for arco in archi:
        arco["esito"] = esito_bersaglio(arco, catalogo_urns)
    _verifica_esiti(archi, catalogo_disponibile=bool(catalogo_urns))
    _verifica_celex(archi)

    if n_fallback_identita:
        print(f"  risolti per identità (data_codice): {n_fallback_identita}")
    _verifica_invarianti(archi, file_set)

    _stampa_metriche(archi, len(file_set))

    # Salva Parquet (il CSV è ignorato da git, solo locale)
    try:
        import pandas as pd
        df = pd.DataFrame(archi)
        # colonna origine sempre presente
        if "origine" not in df.columns:
            df["origine"] = "regex"
        pqt = OUTDIR / "riferimenti.parquet"
        df.to_parquet(pqt, index=False)
        print(f"Parquet: {pqt} ({len(df)} righe, {len(df.columns)} colonne)")
    except ImportError:
        pass


if __name__ == "__main__":
    main()
