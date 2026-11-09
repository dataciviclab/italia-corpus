# Direttive UE — identity-fetch e dataset

Stato: **PR #127** — dataset `direttive_ue` in `datasets/direttive-ue/`, staging
`data/derived/direttive_ue.parquet`; non ancora pubblicato (registry al publish).
Il compose legal-graph è in un branch separato (`feat/ue-nodes`).

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
- titoli ITA/ENG per URI del work, batch da 100: **~20s** per 2.343 work;
- misure nazionali italiane per anno (link inverso): **~2 min** per 5.004
  misure su 3.097 direttive;
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
| Con scadenza di recepimento | 2.025 (86,4% dei risolti) |
| Non risolti | 329 (1.057 citazioni, 2,1%) |

Scartate 25 scadenze segnaposto di Cellar (`1001-01-01`, `1002-02-02`) e 17
scadenze precedenti all'atto: 318 direttive risolte restano senza una scadenza
valida.

I 329 non risolti includono direttive inesistenti (anni 1921-1942) e atti che
Normattiva cita come direttive ma in Cellar sono regolamenti (es.
`32017L2394` è il regolamento 2017/2394): da verificare prima di un eventuale
fallback R/D, per non attribuire l'identità sbagliata.

## Output

`data/derived/direttive_ue.parquet` (staging; clean e mart via toolkit in
`out/data/{clean,mart}/direttive_ue/2026/`):

| Colonna | Contenuto |
|---|---|
| `celex` | `3YYYYLNNNN` |
| `urn_varianti` | URN italiani, separati da `|` (1 o 2) |
| `n_citazioni` | citazioni in ingresso nel corpus |
| `stato` / `motivo` | `risolto` / `non_risolto` · `non_in_cellar` |
| `work_uri` | URI Cellar del work |
| `titolo_ita` / `titolo_eng` / `titolo` | titolo (ITA, fallback ENG) |
| `data` | data dell'atto |
| `scadenza_recepimento` | **minima** tra le scadenze valide (`scadenze` le elenca, `n_scadenze` le conta) |
| `in_vigore` | `true`/`false`; `null` = non risolto |
| `n_misure_ita` | misure nazionali italiane trovate |
| `prima_notifica_ita` | prima data di notifica (può contenere segnaposto) |
| `prima_misura_ita_data` | data della prima misura italiana (≥ data dell'atto) |
| `ritardo_recepimento_giorni` | `prima_misura_ita_data − scadenza` (negativo = in tempo) |
| `ritardo_plausibile` | `true` se il ritardo è ≤ 3 anni (oltre, spesso manca la prima misura) |
| `misura_ita_titolo` | titolo della prima misura |
| `eurlex_url` / `eli_url` | link al testo e all'ELI |

Cache: `out/direttive_ue/{cellar_scan,titoli}.json`.

## Uso

```bash
python -m lab_tools.fetch_direttive_ue             # scan + titoli (cache)
python -m lab_tools.fetch_direttive_ue --refresh   # ignora la cache
python -m lab_tools.fetch_direttive_ue --limit 20  # prova veloce
```

## Ritardo di recepimento: si può fare, con cautele

Il link direttiva→misura nazionale non è esposto in avanti nell'endpoint, ma
esiste quello inverso: `cdm:measure_national_implementing_implements_resource_legal`
+ `..._implemented_by_country <.../country/ITA>` + `cdm:work_date_document`.
Una query per anno restituisce **5.004 misure italiane per 3.097 direttive**
(~2 min); **1.861 delle nostre 2.343** (79,4%) hanno almeno una misura.

| | |
|---|---:|
| Con misura italiana | 1.861 |
| Ritardo calcolabile | 1.640 |
| In ritardo (grezzo) | 1.295 (79,0%) |
| Ritardo mediano (grezzo) | 248 giorni |

**Validazione su 18 direttive** con recepimento noto nel corpus (oggetto che
cita la direttiva): **10 coincidono** entro 120 giorni, **8 divergono**. I casi
divergenti sono quasi tutti NIM che **non contengono la prima misura**: 97/81
(manca il D.Lgs 61/2000), 2008/98 (manca il 205/2010), 2006/123 (manca il
59/2010), 95/46 (nessuna misura), 83/349 (manca il 127/1991); in un caso
(2009/138) c'è l'atto giusto ma una data sbagliata.

**Stima conservativa** (esclusi i ritardi > 3 anni, dove è quasi certo che manchi
la prima misura): **1.392 direttive, 1.047 in ritardo (75,2%), mediana dei
ritardi 282 giorni**. Per decennio: 69% (70), 71% (80), 75% (90), 84% (2000),
77% (2010), 56% (2020).

Il claim difendibile è quindi: *circa tre quarti delle direttive con una misura
italiana plausibile è stata recepita in ritardo, con una mediana di ~9 mesi*. I
248 casi con ritardo > 3 anni restano un limite superiore da non usare.

Esempi verificati a mano: 89/391 → D.Lgs 626/1994, **+681 giorni**; 2019/1937 →
D.Lgs 24/2023, **+453**; 2016/680 → D.Lgs 51/2018, **+18**; 2006/123 → **+793**.

**Cautela**: l'elenco NIM di Cellar può non contenere la prima misura di
recepimento. Per la 97/81 (part-time) c'è solo una misura del 2015 (il D.Lgs
61/2000 manca), per la 2008/98 solo una legge del 2024 (manca il D.Lgs
205/2010): il ritardo è quindi un **limite superiore**, non una misura esatta.
Le date di notifica contengono segnaposto (1992-12-30 su misure del 1994), per
questo il ritardo usa la data dell'atto, non la notifica. Prima di pubblicare un
claim serve un controllo su un campione di direttive con recepimento noto.

## Prossimi passi

1. pubblicare (publish + registry): il support legal-graph `slug: direttive_ue`
   si risolve solo dopo il publish;
2. in legal-graph: nodi `source='ue'` con chiave CELEX e edge `riferimento`
   (le due grafie collassano su un nodo);
3. **validare il ritardo** su un campione più ampio, poi pubblicare l'analisi
   (il metodo c'è; il limite sono i NIM incompleti);
4. decidere i 329 (fallback R/D con verifica del titolo, o esclusione
   dichiarata);
5. licenza/attribuzione dei documenti UE prima di un uso pubblico esteso.

## Limiti

- Nessun testo scaricato: `legal_text` resta su EUR-Lex.
- `scadenza_recepimento` è la minima, non l'unica: per gli atti con più
  scadenze (350 casi) serve la lettura per articolo.
- L'endpoint CELLAR è lento sulle query per CELEX: usare sempre il bulk per anno
  e la cache.
- In CI, se il fetch Cellar fallisce, il publish usa il parquet committato
  (`data/derived/direttive_ue.parquet`): il dataset è **stale**, con un warning
  esplicito. Non è un percorso a dati freschi.
