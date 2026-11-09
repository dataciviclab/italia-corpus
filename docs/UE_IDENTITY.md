# Direttive UE — identity-fetch (prototipo)

Stato: branch locale `feat/direttive-ue-identity`, **non pubblicato**. Dataset in
`out/direttive_ue/` (gitignored), nessuna modifica a `datasets/` o al compose.

## Perché

Le leggi italiane citano direttive UE che `atti_index` (catalogo italiano) non
contiene: oggi non hanno nodo e il compose le esclude, per scelta (#124).

- **5.144 URN UE** distinti → **2.672 direttive** distinte: la stessa direttiva
  compare come `urn:nir:eu:direttivaue:YYYY;N` (2.672) e
  `urn:nir:eu:direttiva.ue:YYYY;N` (2.472, tutte duplicate).
- **49.406 citazioni** verso direttive, su 26.410 bersagli non risolti.

## Fonte

SPARQL **CELLAR** del Publications Office (ontologia CDM), senza testi:

- scan per anno (`STRSTARTS(?celex, "3YYYY")`) con resource type
  `DIR`/`DIR_IMPL`/`DIR_DEL`: **4.408 direttive base in ~51s**;
- titoli ITA/ENG per URI del work, batch da 100: **~20s** per 2.323 work;
- mappatura `urn:nir:eu:direttiva(ue|.ue):YYYY;N` → CELEX `3YYYYL{NNNN}`:
  **0 URN non mappati**.

Non si usa il lookup per CELEX: la join diretta sul letterale non funziona e
`FILTER(STR(...))` costa ~50s per 20. Il bulk per anno è la via.

## Risultato (2026-11-09)

| | |
|---|---:|
| CELEX distinti | 2.672 |
| Risolti in Cellar | **2.343 (87,7%)** |
| Con titolo italiano | 2.343 (100% dei risolti) |
| Citazioni coperte | **48.349 / 49.406 (97,9%)** |
| Con scadenza di recepimento | 2.071 (88,4% dei risolti) |
| Non risolti | 329 (1.057 citazioni, 2,1%) |

25 scadenze segnaposto di Cellar (`1001-01-01`, `1002-02-02`) sono state
scartate: 9 direttive restano senza una scadenza valida.

I 329 non risolti includono direttive inesistenti (anni 1921-1942) e atti che
Normattiva cita come direttive ma in Cellar sono regolamenti (es.
`32017L2394` è il regolamento 2017/2394): da verificare prima di un eventuale
fallback R/D, per non attribuire l'identità sbagliata.

## Output

`out/direttive_ue/direttive_ue.parquet`:

| Colonna | Contenuto |
|---|---|
| `celex` | `3YYYYLNNNN` |
| `urn_varianti` | URN italiani, `;`-separati (1 o 2) |
| `n_citazioni` | citazioni in ingresso nel corpus |
| `stato` / `motivo` | `risolto` / `non_risolto` · `non_in_cellar` |
| `work_uri` | URI Cellar del work |
| `titolo_ita` / `titolo_eng` / `titolo` | titolo (ITA, fallback ENG) |
| `data` | data dell'atto |
| `scadenza_recepimento` | **minima** tra le scadenze valide (`scadenze` le elenca, `n_scadenze` le conta) |
| `in_vigore` | `true`/`false`; `null` = non risolto |
| `eurlex_url` / `eli_url` | link al testo e all'ELI |

Cache: `out/direttive_ue/{cellar_scan,titoli}.json`.

## Uso

```bash
python -m lab_tools.fetch_direttive_ue             # scan + titoli (cache)
python -m lab_tools.fetch_direttive_ue --refresh   # ignora la cache
python -m lab_tools.fetch_direttive_ue --limit 20  # prova veloce
```

## Cosa non funziona (ancora): il ritardo di recepimento

La scadenza da sola non basta: serve la **data della misura nazionale** che
recepisce. Verificato che non è disponibile per due vie:

1. **SPARQL**: le misure nazionali (`cdm:measure_national_implementing`,
   `cdm:resource_legal_implemented_by_measure_national_implementing`,
   `cdm:country_implements_measure_national_implementing`) ci sono nel RDF
   scaricato per singolo atto, ma **non** nell'endpoint: la query sul CELEX
   restituisce 0 predicati, e 0 anche passando dal work id.
2. **Citazioni nel grafo**: la prima legge italiana che cita una direttiva non è
   la legge di recepimento. Per il 2019/1937 il primo citatore risulta un atto
   del **2001** — un `akn:ref` senza contesto risolto male. Lo stesso problema
   noto dei riferimenti generici: non è una base affidabile per il ritardo.

Per la misura nazionale servono i RDF per atto (~12 MB × 2.343 ≈ 28 GB) o le
pagine NIM di EUR-Lex (HTML, anti-bot), oppure una fonte dedicata. Senza questa,
l'analisi "ritardo" non si fa: il dataset resta utile per nodi e citazioni, non
per il ritardo.

## Prossimi passi (se si decide A)

1. promuovere a dataset `datasets/direttive_ue` + registry (contratto clean);
2. in legal-graph: support `type: external`, nodi `source='ue'` con chiave CELEX
   e edge `riferimento` (le due grafie collassano su un nodo);
3. analisi sul **ritardo di recepimento**: **bloccata** finché non c'è una fonte
   per la misura nazionale (vedi sopra). Senza, resta solo copertura di nodi e
   citazioni;
4. decidere i 329 (fallback R/D con verifica del titolo, o esclusione
   dichiarata);
5. licenza/attribuzione dei documenti UE prima del publish.

## Limiti

- Nessun testo scaricato: `legal_text` resta su EUR-Lex.
- `scadenza_recepimento` è la minima, non l'unica: per gli atti con più
  scadenze (359 casi) serve la lettura per articolo.
- L'endpoint CELLAR è lento sulle query per CELEX: usare sempre il bulk per anno
  e la cache.
