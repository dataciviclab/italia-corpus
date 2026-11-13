# Pipeline italia-corpus

**Ruolo nel Lab**: pipeline **Normattiva → MD + parquet**.  
Non è il grafo normativa del Lab (quel lavoro è di **legal-graph**, che *consuma* questi output).  
Non è una piattaforma di igiene/cruscotto.

## Principio

```
Fonte (API Normattiva)
        ↓
   1 FETCH      scarica AKN XML per collezione
        ↓
   2 INGEST     MD nel corpus + relazioni AKN (se disponibili)
        ↓
   3 TABLES     parquet derivati da MD/AKN
        ↓
   4 QUALITY    colonne di utilità (non policy giuridica)
        ↓
Ecosistema     MCP · legal-graph · analisi · Explorer (a valle)
```

**Regole**
1. Il **prodotto primario** è il corpus MD (cercabile, ispezionabile).
2. I **parquet** sono prodotti tabulari per il Lab — contratti stabili, non speculazioni.
3. L’**AKN strutturato** è *enrichment* della stessa pipeline, non un secondo motore.
4. **Niente** dashboard igiene dentro IC, salvo esplicita decisione umana.
5. **Non** migriamo IC su toolkit RAW/CLEAN/MART: il modello toolkit è tabulare; qui la fonte è un corpus testuale + side parquet. Restiamo `corpus-project` con stage lineari.
6. I MD del corpus vivono sotto **`collezioni/<Nome Collezione>/`** — path contratto cross-repo (MCP, CI, legal-graph). Costanti: `lab_tools/_paths.py`.

---

## Stage (canonici)

Ordine **critico** (uguale a CI e `make pipeline`):

| # | Stage | Comando | Output |
|---|---|---|---|
| 0 | **probe-collezioni** | `python -m lab_tools.collezioni_probe` | `collezioni_probe.json` (formati O/V/M per collezione + freeze, una richiesta) |
| 1 | **fetch** | `python -m lab_tools.fetch_normattiva [--only …] [--force]` | MD + `akn_*.parquet` (staging + merge); `--force` ignora il manifest e riprocessa tutte le collezioni (re-parse AKN) |
| 1b | **fetch-status** | `python -m lab_tools.fetch_status` | `status.parquet` (solo **abrogati**, classe 3 = lista ufficiale; no testo) |
| 2 | **extract** | `python -m lab_tools.extract` | `normativa.parquet` (metadati) + `testi.parquet` (filename, urn, testo) |
| 2a | **akn-canonicalizza** | `python -m lab_tools.akn_canonicalizza` | URN canonici in `akn_relations` (alias `codice.*`, `regiodecreto`, `decretodelpresidentedellarepubblica`), dedup sulla chiave del clean e **sulla chiave normalizzata** (le forme URN diverse dello stesso arco diventano una riga, con `contesto`/`locator` uniti) |
| 2b | **atti-index** | `python -m lab_tools.atti_index` | `atti_index.parquet` (catalogo ufficiale, ~205k atti: identità, `stato` da classe 3, `in_corpus`, `materia`) |
| 3 | **classifica** | `python -m lab_tools.classifica_tematich` | + `materia` (vedi [MATERIA_AUDIT.md](MATERIA_AUDIT.md)) |
| 4 | **citazioni/abrogations** | moduli `estrai_*` / `extract_*` | side product su disco |
| 5 | **integra** | `python -m lab_tools.integra_costituzionali` | + cit. cost. / abrogazioni **da side product** |
| 5b | **integra-vigenza** | `python -m lab_tools.integra_vigenza` | `stato` da `status.parquet` + `vigenza_fonte` |
| 6 | **grafo** | `python -m lab_tools.grafo_riferimenti` | `riferimenti` (regex∪AKN, denorm materia) |
| 7 | **arricchisci** | `python -m lab_tools.arricchisci_normativa` | + `n_citazioni`, `orfano`, `qualita_score` |
| 8 | **integra-akn** | `python -m lab_tools.integra_akn_meta` | + `ingresso_in_vigore`, `akn_*` |
| 9 | **sunsetting** | `python -m lab_tools.monitor_sunsetting` | + `sunsetting_score`, `eta_anni`, … |
| 10 | **atti API** | `python -m lab_tools.fetch_urn_acts` | `atti_api.parquet` (leggi fuori collezione; input legal-graph) |

**Makefile**
- `make pipeline` = stage 2–9 (senza fetch)
- `make pipeline-core` = 2,3,5b,6,7,8,9 — minimo **MCP/legal-graph** (inclusa `classifica`)
- `make fetch-status` = stage 1b (network, WAF IPZS → pacing)

**CI**: due cadenze separate.
- **Pipeline settimanale** (`pipeline.yml`, lunedì 03:30 UTC): job `build` (raw precedenti da GCS → fetch → **gate d'identità URN** → commit `collezioni/` → fetch-status → derive → `atti-index` + `direttive_ue` → **raw layer** + allegati su GCS) e job `publish` (toolkit + clean/mart su GCS + registry PR). ~26 min: `atti-index` e `direttive_ue` stanno nel build (dove il raw è fresco) e il publish li riusa via cache.
- **Contract change** (merge su `datasets/**`): gira solo `publish`, in **batch** sui dataset toccati (`detect-paths: datasets` + `make run-batch`), dal raw layer GCS — niente fetch, niente `atti-index`/CELLAR (~3 min). Limite noto: se il merge tocca `datasets/atti-index`, il catalogo pubblicato è quello dell'**ultimo build** (fino a una settimana); la freschezza la paga la weekly.
- **Ordine del commit**: il corpus si committa **dopo** il gate d'identità, mai prima. `main` non riceve un corpus con URN spariti (classe 29/10) e, se un derive fallisce dopo, il fetch è già salvo: la run dopo non lo ripaga.
- **Probe formati quotidiano** (`probe.yml`, 05:30 UTC): una richiesta a `collection-predefinite`, scrive `collezioni_probe.json` e committa **solo se lo stato cambia**. È il watchdog dei formati (freeze V del 30/10).
- `fetch-status` (classe 3, ~2 min) è **non fatale**: se il WAF blocca, resta lo status in cache e il build prosegue con un `::warning::`. Il vintage è in `status.parquet.fetched_at`.

**`stato` / `vigenza_fonte`**

Lo `stato` atto-level è un **metadato ufficiale**, non va derivato dal testo.
Fonte: `status.parquet` (stage 1b), da `POST /ricerca/avanzata` con filtro
`classeProvvedimento` (tipologia **ufficiale IPZS**). La **classe 3** ("abrogato")
coincide con la collezione ufficiale **"Atti normativi abrogati"** (~124k atti)
→ è la lista autorevole. La classe 2 ("aggiornato") **non** è "vigente".

`integra-vigenza` (stage 5b), in cascata:
1. join `normativa` ↔ `status` su **(codice_redazionale, data GU)** — il filename
   del corpus porta la data GU. Chiave **esatta, senza fallback**: il codice
   redazionale è **riciclato** (stesso codice/anno/numero per atti diversi, es.
   `072U0670` = regio decreto 1872 *e* DPR 670/1972). Il join è **atto-level**:
   ORIGINALE e VIGENZA della stessa legge condividono la chiave → stesso `stato`
   (fix #67);
2. **classe 3** (lista ufficiale) → `abrogato`, `vigenza_fonte='normattiva'`;
3. **nota whole-act** `PROVVEDIMENTO ABROGATO` nel testo (markup ufficiale,
   assente dalla lista: es. D.Lgs 220/1995) → `abrogato`,
   `vigenza_fonte='non_coperto'`;
4. altrimenti → `vigente`, `vigenza_fonte='esclusione'`;
5. collezione **'DL decaduti'** → `decaduto` (la ricerca non distingue `decaduto`).

`vigenza_fonte` = `normattiva` | `non_coperto` | `esclusione`.

> **Rimosso** (2026-10-25): tombstone (per lo `stato`) e override dagli eventi AKN.
> Gli eventi AKN `repeal`/`substitution` sono **article-level** → marcavano l'atto
> intero (falsi positivi: Codice Civile, Codice Penale).

> `classifica` **prima** di `grafo`: altrimenti `fonte_materia`/`bersaglio_materia` restano vuote.  
> `classifica` usa confini di parola e un tier per i trattati (`affari-esteri`): ogni modifica
> alle keyword si verifica con `pytest tests/test_classifica_gold.py` (gold set 200 atti,
> vedi [MATERIA_AUDIT.md](MATERIA_AUDIT.md)).
> Side product **prima** di `integra`: `integra_costituzionali` legge `_citazioni_stage.parquet` e `abrogations_raw.parquet` da `data/derived/`.  
> `integra-vigenza` **dopo** `fetch-status` e `extract`, e **prima** di `grafo`/`arricchisci` (così `fonte_stato` negli edge e `qualita_score` usano lo stato corretto).  
> Su CI il checkout di `data/derived/` può ancora fornire side product del giorno prima se lo step è saltato — meglio rigenerarli nello stesso run.  
> `integra-akn` **dopo** `arricchisci`. `sunsetting` **per ultimo**.

---

## Staging vs contratti

Regola unica:

> `data/derived/` è **staging**: forma libera, può cambiare senza preavviso e
> **nessun repo esterno lo legge**. Se un repo esterno lo legge, deve esistere
> `datasets/<nome>` e il consumer usa `slug` + `layer` (`clean`/`mart`) dal
> registry.

### Contratti (pubblicati, letti da altri repo)

| Dataset (`datasets/`) | Slug registry | Grain | Consumatori |
|---|---|---|---|
| `normativa` | `normativa` | atto (metadati, stato, materia, qualità, EIV) | legal-graph, MCP, analisi |
| `riferimenti` | `riferimenti` | arco fonte→bersaglio (citation + abroga) | legal-graph, debt |
| `akn_relations` | `akn_relations` | relazione AKN tipizzata, con `locator`/`articolo` (frammento dell'href) | legal-graph |
| `akn_act_meta` | `akn_act_meta` | atto (EIV, modifiche, ELI) | legal-graph |
| `atti_index` | `atti_index` | atto del catalogo (~205k), `materia` inclusa | legal-graph, analisi di copertura |
| `atti_api` | `atti_api` | atto fuori collezione (vigenza, materia) | legal-graph (nodi + `attua_delega`) |
| `testi` | `testi` | espressione (`filename`, `urn`, testo document-level) | legal-graph (full-text, `legal_text`) |
| `direttive_ue` | `direttive_ue` | direttiva UE (CELEX, titolo, scadenza, misure ITA, ritardo) | legal-graph (nodi UE, analisi recepimento) |

`riferimenti` espone anche **`mart_riferimenti_urn`** (`fonte_urn`, `bersaglio_urn`,
`rel_type`, `peso`, `fonte_anno`, `bersaglio_anno`, `contesto`,
`clausola_lettura`, `da_regex`): è il contratto **URN-based** che usa legal-graph
(join esatto sui nodi, nessuna normalizzazione nel compose). Il clean
filename-based resta per coverage e mart analitici.

`atti_index` ha il raw sul **layer GCS** come gli altri: lo genera il build
(`make atti-index`, con `rm` prima per non sovrascrivere la copia buona in
caso di WAF) e il publish lo legge dal layer. La `materia` del catalogo usa lo
stesso classificatore del corpus: i gap di tassonomia sono tracciati in #81
(multi-etichetta, natura dell'atto).

### Staging (`data/derived/`, interno — **non in git**)

| Artifact | Uso | Note |
|---|---|---|
| `status.parquet` | `integra-vigenza` | status autorevole, non pubblicato |
| `abrogations_raw.parquet` | `integra` + coverage | **fuso** in `riferimenti` come `rel_type='abroga'` (2026-11); resta letto solo dalla coverage come misura della fonte |
| `_citazioni_stage.parquet` | `integra` + `grafo` | **gitignored**: fuso in `riferimenti` (`origine='costituzione'`, `rel_type='cita_costituzione'`, `bersaglio_id='costituzione:art:N'`) |
| `atti_api.parquet` | `datasets/atti-api` | promosso a contratto (2026-11) |
| `testi.parquet` | `datasets/testi` | **gitignored** (~98MB), rigenerato dal publish con `python -m lab_tools.extract --testi-only` |
| `allegati.parquet` | consumer esterni | **indice pubblicato su GCS** (2026-11, #112): i MD (188,8 MB) sono già lì |
| `collezioni_probe.json` | probe/CI | **committato**: storia dei formati |

### Testi

| Artifact | Stato |
|---|---|
| `collezioni/**/*.md` | testo + frontmatter URN; servito da `legal_text` via GitHub raw |
| `testi` (dataset) | **pubblicato** (2026-11): `filename, urn, testo` dal body dei MD, ~98 MB, zero fetch — #111 |
| `articoli` (dataset) | **mancante**: grano articolo, da AKN XML (commi, `eId`, `ins`/`del`). Raffinamento successivo di `testi` |

### Nomi (convenzione)

- directory: trattino (`akn-relations/`, `atti-index/`)
- slug registry e file sorgente: underscore (`akn_relations`, `atti_index`, `akn_relations.parquet`)
- `normativa` è **atto-level metadata**: non contiene il testo (che è `collezioni/` oggi, `testi`/`articoli` domani). Il nome è storico; una rinomina a `atti` sarebbe un cambio di contratto (shim necessario).

### Debiti dichiarati

1. `citazioni_costituzionali` è **fuso** in `riferimenti` (`origine='costituzione'`, `bersaglio_id='costituzione:art:N'`): legal-graph legge un solo artefatto. `pnrr_references` è stato **rimosso** (stub senza identità canonica; se serve, si ricostruisce sulle misure di `open-pnrr`). I consumer leggono `riferimenti` per le citazioni: nessun derived IC via GitHub raw. `abrogations_raw` è **fuso** in `riferimenti` (`rel_type='abroga'`).
2. `allegati.parquet` è l'indice di un contenuto già pubblicato (5.492 MD su GCS): va pubblicato lui (#112), non rimosso.
3. ~~`data/derived` è in git **e** su GCS~~: **chiuso** (2026-11). I derivati stanno solo sul **raw layer** `gs://dataciviclab-clean/italia-corpus/_raw/2026/`, pubblicato dal build; `publish` e `derive-smoke` li riportano in `data/derived/` con `make fetch-raws`. Il gate confronta raw vs raw dal layer. In git restano codice, config, corpus e `collezioni_probe.json`.

### Convenzioni path (contratto)

| Superficie | Formato | Esempio |
|---|---|---|
| File su disco | `collezioni/<Collezione>/<file>.md` | `collezioni/Codici/x.md` |
| MCP `path` | relativo a `collezioni/` | `Codici/x.md` |
| MCP `filename` / `normativa.filename` | basename | `x.md` |
| `riferimenti.fonte_filename`, `bersaglio_path` | relativo a `collezioni/` (stabile pre/post move) | `Codici/x.md` |
| `riferimenti.bersaglio_filename` | basename | `x.md` |
| Link MD interni | `../<Collezione>/<file>.md` | `../Codici/x.md` |

Costanti: `lab_tools/_paths.py` (`COLLEZIONI_ROOT`).  
I parquet derived **non** sono rigenerati in questa PR: al prossimo build CI il formato path di `riferimenti` resta quello sopra (nessun prefisso `collezioni/` nei campi path).

**Non committare**: zip, XML temporanei, `_akn_stage/`, `*.csv` locali.  
**Sì in git**: derived deliberati del contratto Lab (oggi versionati nel repo).
**No in git**: `testi.parquet`, `atti_index.parquet`, `status.parquet` (rigenerati nel publish).

### Schema `normativa` (colonne base + enrichment AKN)

Base atto: `collezione`, `filename`, `tipo`, `data`, `numero`, `oggetto`, `celex`,
`anno_atto`, `anno_dir`, `ritardo`, `urn`, `codice_redazionale`,
`versione`, `snapshot_data`, `is_current`,
`stato`, `vigente`, `vigenza_fonte`, `lunghezza_caratteri`, `lunghezza_parole`,
`riferimenti_interni`, `duplicato`, `n_citazioni`, `orfano`, `qualita_score`

Identità dell'atto: `urn` può ripetersi (espressioni diverse dello stesso atto);
`is_current` marca **l'espressione corrente** (una sola per `urn`), `versione`
(`ORIGINALE`|`VIGENZA`) e `snapshot_data` dicono quale. Regola: `VIGENZA` con
snapshot più recente → altrimenti `ORIGINALE`.

Downstream: `materia`, `n_articoli_cost`, `articoli_cost`, `abrogato_da`, `n_abrogazioni`, …

Enrichment AKN (da stage `integra-akn`, se gli artifact sono presenti):
`ingresso_in_vigore`, `akn_n_refs`, `akn_n_active_mods`, `akn_n_passive_ref`,
`akn_n_repeal_events`, `akn_mod_types`, `akn_has_workflow`, `akn_meta_source`

| Colonna | Tipo | Significato |
|---|---|---|
| `stato` | string | `vigente` \| `abrogato` \| `decaduto` — status autorevole Normattiva, atto-level (classe 3 = lista ufficiale "Atti normativi abrogati", o nota whole-act). `decaduto` = collezione "DL decaduti" |
| `vigente` | bool | `stato == 'vigente'` (il frontmatter MD di Normattiva è inaffidabile) |
| `vigenza_fonte` | string | Origine di `stato`: `normattiva` (lista ufficiale abrogati, `classeProvvedimento` 3) \| `non_coperto` (assente dalla lista ma con nota whole-act) \| `esclusione` (assente, `vigente` per esclusione) \| `atti_api` (atto fuori collezione) |
| `duplicato` | bool | Più espressioni **correnti** per lo stesso atto (oggi 0: guardia). Le versioni storiche non sono duplicati |
| `n_citazioni` | int | Citazioni in ingresso **per atto**: il totale sta sulla riga corrente, le altre 0 |
| `orfano` | bool | **Atto-level**: solo la riga corrente può essere orfana (nessuna citazione in uscita né in ingresso) |
| `qualita_score` | int | 0–100, più alto = migliore (penalizza duplicati, orfani, stato non vigente) |
| `materia` | string | Classificazione tematica dal titolo: 25 categorie. Semantica e limiti in [MATERIA_AUDIT.md](MATERIA_AUDIT.md) |
| `n_articoli_cost` | int | Numero di articoli costituzionali citati dall'atto |
| `articoli_cost` | string | Articoli costituzionali citati (separati da virgola) |
| `abrogato_da` | string | File che abrogano questo atto |
| `n_abrogazioni` | int | Numero di abrogazioni che riguardano questo atto |
| `eta_anni` | int | Anni dall'atto (anno corrente − anno_atto) |
| `sunsetting_score` | int | 0–100, più alto = più candidato alla decadenza automatica |

### Schema `riferimenti` (clean pubblicato: 20 colonne)

`fonte_source_path`, `bersaglio_source_path`, `fonte_source_file`,
`bersaglio_source_file`, `fonte_filename`, `fonte_urn`, `bersaglio_filename`,
`bersaglio_urn`, `fonte_anno`, `bersaglio_anno`, `fonte_stato`,
`bersaglio_stato`, `fonte_materia`, `bersaglio_materia`, `peso`, `risolto`,
`origine`, `rel_type`, `contesto`, `clausola_lettura`

Il clean pubblicato è il contratto: usa i campi `*_source_path`/`*_source_file`,
non i `path`/`collezione` del derived. Il **derived**
`data/derived/riferimenti.parquet` ha 21 colonne: in più
`fonte_collezione`, `fonte_tipo`, `bersaglio_path`, `bersaglio_collezione`,
`bersaglio_tipo`, e in meno i quattro `*_source_*`. Il contratto URN-based per
legal-graph è `mart_riferimenti_urn` (vedi sopra).

`clausola_lettura`: `TRUE` = rinvio di sola lettura ("al solo fine di
facilitare la lettura delle disposizioni"), non una citazione; `FALSE` =
contesto presente senza quella clausola; `NULL` = contesto assente (archi AKN
prodotti prima del 2026-10-30) → non classificabile.

Il mart URN-based consumato da legal-graph è `mart_riferimenti_urn` (vedi sopra).

---

## Relazione con altri sistemi

| Sistema | Rapporto |
|---|---|
| **legal-graph** | Consuma URN/testi/parquet da IC. Dopo publish GCS: support `type: external` su HTTPS clean. Oggi ancora GitHub raw derived. |
| **toolkit** | Engine resta corpus-project. **Layer toolkit** in `datasets/` → clean contract (`local_file` su `data/derived` → `out/data/clean`). |
| **source-observatory** | Normattiva = fonte self-managed del corpus (inventario SO separato). |
| **cruscotto igiene** | Solo con decisione umana + dashboard dedicata. |

### Layer toolkit (2026-10-08)

| Dataset | PK clean | Mart |
|---|---|---|
| `normativa` | `filename` | `mart_atti_per_tipo`, `mart_materia_stato`, `mart_candidati_sunsetting` |
| `riferimenti` | `fonte_source_path + bersaglio_source_path + origine` | `mart_debt_legale`, `mart_citazioni_per_origine`, `mart_top_bersagli` |
| `akn-act-meta` | `fonte_file` | `mart_eiv_per_decennio`, `mart_modifiche_anno` |
| `akn-relations` | `edge_id` (md5) | `mart_relazioni_per_tipo`, `mart_modifiche_tipizzate` |

- Makefile: `make toolkit-check` · `make toolkit-run` · `make verify-smoke`
- Output: `out/data/{clean,mart}/<dataset>/2026/` (gitignored)
- **CI settimanale** (`pipeline.yml`, lunedì 03:30 UTC, due job):
  - `build`: fetch + gate URN + commit `collezioni/` + derive + `atti-index`/`direttive_ue` (cache) + commit dati + `allegati/` su GCS
  - `publish`: `extract --testi-only` pre-run + `toolkit-run` (raw dal layer, selettivo nel batch) + rsync
    `gs://dataciviclab-clean|mart/italia-corpus/` + registry draft PR
  - merge di `datasets/**`: solo `publish`, in batch sui dataset cambiati (`make run-batch`)
- `workflow_dispatch` ha tre input: **`skip_fetch`** salta fetch Normattiva, status e atti API (~4 min invece di ~15), per validare/ripubblicare una correzione — `status`/`atti_api` vengono dalla cache del build (TTL 30g), quindi su cache fredda `integra_vigenza` fallisce e non è un percorso "da checkout pulito"; **`force_fetch`** passa `--force` al fetch e riprocessa tutte le collezioni ignorando il manifest — serve dopo un cambio di parser (es. `locator`/`contesto` di #142), perché le collezioni invariate verrebbero altrimenti saltate; **`only`** limita il fetch a una o più collezioni (nomi esatti, separati da virgola) — riparare un buco di parser su una collezione costa pochi MB invece di un run completo
- **Backfill allegati (#141)**: input `backfill_allegati` (+ `allegati_only`) → `make fetch-allegati`. Legge l'espressione disponibile **anche `O`** e non tocca il corpus: serve per le collezioni congelate (pin `V`) e per gli atti fetchati prima della feature. Sul corpus 2026-11-12: **5.514 → 6.189** atti con allegati (+675), 146.055 → 173.695 doc. One-off; la weekly copre i nuovi atti delle collezioni vive.
- **Diagnostica locator**: il fetch logga, per collezione, `rel_type loc/n` e avverte se un `rel_type` con ≥10 righe ha **0** locator (sintomo di un formato href non gestito: è così che `repeal` 0/221 con la sintassi `~art_...` non si vede più solo a fine run)
- **`derive-smoke`** (`derive-smoke.yml`): sulle PR che toccano `lab_tools/`, `datasets/`, `config/`, `data/derived/`, `collezioni/`, `.github/` esegue **grafo + contract check + arricchisci** sui raw scaricati dal layer GCS (`make fetch-raws`), senza fetch (~6-8 min). È il gate che avrebbe preso l'invariante delle abroga e il churn dei link regex, non coperti dai test unitari
- **Locale, prima di un push su `lab_tools`**: `make verify-smoke` (grafo + arricchisci; il contract check è nella CI). Sovrascrive `data/derived/{normativa,riferimenti}.parquet` (gitignored: nessun checkout da fare)
- `toolkit-run` salta `datasets/atti-index` se l'artefatto manca (guardia esplicita)
- Il clean `atti-index` richiede la colonna `materia` nel parquet derivato: in CI lo genera il `build` e lo pubblica sul layer; il publish lo scarica con `make fetch-raws` (che valida il parquet). **In locale**: `make fetch-raws` prima di `make toolkit-run`.
- Dual-publish: derived resta in git per MCP; clean+mart su GCS sono il contratto Lab
- Warning attesi: `riferimenti` clean droppa denorm non usati da LG

**Perché settimanale**: il consumatore (legal-graph) ricostruisce il grafo il
lunedì, e la fonte rigenera snapshot ogni giorno anche quando le leggi non
cambiano (centinaia/migliaia di file riscritti). Il quotidiano pagava ~25 min e
il churn git per un prodotto che resta settimanale. Il probe resta quotidiano
perché è l'unico che deve accorgersi subito di un cambio di formato.
**Perché no registry daily**: `registry.json` cambia a ogni run (`updated_at`,
`signals.run_id`) → una draft PR al giorno è rumore.

---

## Stato AKN (2026-11-09)

- Modulo: `lab_tools/akn_relations.py` (+ `integra_akn_meta.py`)
- Wire: fetch (staging+merge) · grafo (union citation, `origine`) · integra-akn
- **Copertura** (2026-11-13, prima del re-parse 3.2): meta join **20.791/20.791**, EIV su **9.936 atti**; raw `akn_relations` **443.653** righe dopo canonicalizzazione URN e dedup — `citation` 284.280 (226.396 con `contesto`, 109.440 con `articolo`), `insertion` 101.113 (78.576 con `articolo`), `repeal` 731 (377), `substitution` 613 (426)
- CI: lint ruff · step `integra-akn` · ordine side-product→integra → grafo · contract check
- **Locator (#142)**: `locator` è il fragment grezzo dell'href, nelle **due sintassi AKN**: hash (`1`, `art_47-com1`, `Ordinamento-art. 6` — citazioni ed eId) e path (`.../!main/~art_8-ter__para_3` → `art_8-ter__para_3` — la usano quasi tutte le `repeal`/`substitution` e le `insertion` di alcune collezioni). `articolo` è la forma normalizzata `art_N[-suffisso][-comM]`. I suffissi che cambiano l'identità (`bis`, `ter`, `quater`, `quinquies`, `sexies`, `septies`, `octies`, `novies`, `decies`, `undecies`, `duodecies`, `terdecies`, `quaterdecies`, `quindecies`, `sedecies`, `septendecies`, `octodecies`, `novodecies`, `vicies`) sono **conservati** (`art_47-bis` ≠ `art_47`, `art_5-terdecies` non è `art_5-ter`); una coda non riconosciuta ricade sull'articolo base, mai su un suffisso sbagliato.
- **Locator: sotto-articolo**. Il comma resta nel valore (`art_47-com1`), il resto è scartato (`-leta`, `-num2`, `-par1`). Anche il suffisso del comma si perde: `art_47-com4bis` → `art_47-com4`, perché `com4` e `com4bis` sono commi diversi e il valore normalizzato tiene solo il numero. La distinzione resta in `locator`, che è il fragment integro.
- **Locator: granularità**. Sulle `textualMod` è l'articolo del lato target; sulle citazioni dipende dal fragment presente nell'AKN. Il merge aggrega i locator di più articoli in **una lista ordinata** (`art_3,art_47`, formato stringa con virgole) mantenendo il grano `(fonte, target, rel_type, origin)`. Di conseguenza `detail`, `contesto` e la `clausola_lettura` calcolata da `grafo_riferimenti` sono **per edge**, non per articolo: con più articoli sullo stesso edge il contesto salvato è uno solo e **non è attribuibile** al singolo articolo. Il contesto per-articolo non esiste con questo grano — `locator` dice *quali* articoli, non *con quale contesto*.
- **Alias URN e contesto (#109)**: il merge non può sostituire una riga orfana il cui `target_urn` è in una forma che il parser non produce più (`decretodelpresidentedellarepubblica` vs `decreto.del.presidente.della.repubblica`). La canonicalizzazione le raggruppa sulla chiave normalizzata e tiene la riga con `contesto`, unendo `locator`/`articolo`: sul corpus 2026-11-11 collassa **23.933** righe alias e porta la quota di citazioni con contesto dal 52,0% al **54,5%**.
- **Tipo AKN vs effetto (#3.2)**: `type` è il *meccanismo* AKN, non l'effetto. Il taglia-leggi (D.Lgs 212/2010) ha **211.563** `textualMod` tutte `insertion`, ma abroga: nel grafo finivano in `modifica` e `abroga` restava sottostimato. Sulle `activeModifications` l'effetto sta nel testo di `<new>`: una `insertion`/`replacement` con clausola `) l'abrogazione` diventa `repeal`. Forme reali coperte: `ha disposto (…)`, `ha disposto(…)` (senza spazio), `ha disposto con (…)`, `ha confermato (…)`, `, nell'abrogare … ha conseguentemente disposto (…)`. Restano `insertion`: il testo inserito (`((…))` — citare un'abrogazione non è abrogare), le annotazioni **miste** («la modifica dell'art. 16 e l'abrogazione del comma 4», dove l'atto modifica *e* abroga lo stesso target) e le `passiveModifications`, dove `<new>` è la modifica fatta da un altro atto. Effetto atteso sul solo DLgs: `repeal` da 466 a **41.394**, `insertion` da 48.957 a **9.001** (+85 coppie che restano anche `insertion` perché miste).
- **Meta per file**: se la fonte corregge l'URN di un file (es. `26G00056`: `;38` → `;39`), l'upsert per `fonte_urn` lascerebbe due righe con lo stesso `fonte_file` e romperebbe la PK del clean. Dopo l'upsert si deduplica per `fonte_file` (tieni l'ultima).
- Tests: **480** nel repo (`tests/test_akn_relations.py` copre questo stage; un fixture blocca i fragment reali)

Non è un prodotto separato: è **stage fetch + 8** della pipeline sopra.

---

## Evoluzione toolkit — verdetto

| Opzione | Giudizio |
|---|---|
| Migrazione piena a toolkit RAW/CLEAN/MART | **No** — modello tabulare, non adatto al corpus MD |
| Disciplina toolkit dentro IC | **Sì** — stage nominati + layer clean/mart in `datasets/` |
| Toolkit come publisher downstream | **Sì** — clean+mart → GCS + registry; legal-graph punta al clean |

**In sintesi**: IC resta pipeline Normattiva lineare. Toolkit pubblica clean + mart analitici. legal-graph resta l'aggregatore.

