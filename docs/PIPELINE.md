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
| 1 | **fetch** | `python -m lab_tools.fetch_normattiva [--only …]` | MD + `akn_*.parquet` (staging + merge) |
| 1b | **fetch-status** | `python -m lab_tools.fetch_status` | `status.parquet` (solo **abrogati**, classe 3 = lista ufficiale; no testo) |
| 2 | **extract** | `python -m lab_tools.extract` | `normativa.parquet` (metadati) + `testi.parquet` (filename, urn, testo) |
| 2b | **atti-index** | `python -m lab_tools.atti_index` | `atti_index.parquet` (catalogo ufficiale, ~205k atti: identità, `stato` da classe 3, `in_corpus`, `materia`) |
| 3 | **classifica** | `python -m lab_tools.classifica_tematich` | + `materia` (vedi [MATERIA_AUDIT.md](MATERIA_AUDIT.md)) |
| 4 | **citazioni/pnrr/abrogations** | moduli `estrai_*` / `extract_*` | side product su disco |
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
- **Pipeline settimanale** (`pipeline.yml`, lunedì 03:30 UTC): job `build` (fetch + fetch-status + derive + commit dati + allegati su GCS) e job `publish` (toolkit + clean/mart su GCS + registry PR). ~25 min.
- **Contract change** (merge su `datasets/**`): gira solo `publish`, dal raw già committato — niente fetch.
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
> Side product **prima** di `integra`: `integra_costituzionali` legge `citazioni-costituzionali.parquet` e `abrogations_raw.parquet` da `data/derived/`.  
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
| `akn_relations` | `akn_relations` | relazione AKN tipizzata | legal-graph |
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

`atti_index` è l'unico con il raw **non committato** (rigenerato da
`make atti-index` prima del publish). La `materia` del catalogo usa lo stesso
classificatore del corpus: i gap di tassonomia sono tracciati in #81
(multi-etichetta, natura dell'atto).

### Staging (`data/derived/`, interno)

| Artifact | Uso | Note |
|---|---|---|
| `status.parquet` | `integra-vigenza` | status autorevole, non pubblicato |
| `abrogations_raw.parquet` | `integra` + coverage | **fuso** in `riferimenti` come `rel_type='abroga'` (2026-11); resta letto solo dalla coverage come misura della fonte |
| `citazioni-costituzionali.parquet` | `integra` + legal-graph | **debito**: fondere in `riferimenti` come `cita_costituzione` |
| `pnrr_references.parquet` | legal-graph | **debito**: fondere in `riferimenti` |
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

1. `citazioni_costituzionali` e `pnrr_references` sono ancora letti da legal-graph via `path:` (fuori contratto): target non-atto (`costituzione:art:N`, `pnrr:missione:N`), da promuovere a dataset. `abrogations_raw` è **fuso** in `riferimenti` (`rel_type='abroga'`).
2. `allegati.parquet` è l'indice di un contenuto già pubblicato (5.492 MD su GCS): va pubblicato lui (#112), non rimosso.
3. `data/derived` è in git **e** su GCS: doppio canale. Quando i debiti 1-2 sono chiusi, il derived può essere interamente gitignored (il contract check va ribasato su GCS).

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
  - `build`: engine + commit dati + `allegati/` su GCS
  - `publish`: `make atti-index` (pre-run, artefatto non committato) + `toolkit-run` + rsync
    `gs://dataciviclab-clean|mart/italia-corpus/` + registry draft PR
- `workflow_dispatch` ha l'input **`skip_fetch`**: salta fetch Normattiva, status e atti API (~4 min invece di ~15), per validare/ripubblicare una correzione. `status`/`atti_api` vengono dalla cache del build (TTL 30g): su cache fredda `integra_vigenza` fallisce, quindi non è un percorso "da checkout pulito" 
- **`derive-smoke`** (`derive-smoke.yml`): sulle PR che toccano `lab_tools/`, `datasets/`, `config/`, `data/derived/`, `collezioni/`, `.github/` esegue **grafo + contract check + arricchisci** sui dati committati, senza fetch (~6-8 min). È il gate che avrebbe preso l'invariante delle abroga e il churn dei link regex, non coperti dai test unitari
- **Locale, prima di un push su `lab_tools`**: `make verify-smoke` (grafo + arricchisci; il contract check è nella CI). Sovrascrive `data/derived/{normativa,riferimenti}.parquet`: `git checkout -- data/derived` dopo
- `toolkit-run` salta `datasets/atti-index` se l'artefatto manca (guardia esplicita)
- Il clean `atti-index` richiede la colonna `materia` nel parquet derivato: in CI c'è `make atti-index` prima del publish, **in locale** un `atti_index.parquet` vecchio fa fallire `make toolkit-run` finché non si rigenera
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
- **Copertura** (2026-11-09): fetch completo 20 collezioni — meta join **20.790/20.790**, EIV su **9.936 atti** (10.729 espressioni), riferimenti con origine `akn` **267.636** su **501.753** relazioni AKN estratte, `akn_relations` tipizzato (inclusi repeal/substitution)
- CI: lint ruff · step `integra-akn` · ordine side-product→integra → grafo · contract check
- Tests: **408** nel repo (`tests/test_akn_relations.py` copre questo stage)

Non è un prodotto separato: è **stage fetch + 8** della pipeline sopra.

---

## Evoluzione toolkit — verdetto

| Opzione | Giudizio |
|---|---|
| Migrazione piena a toolkit RAW/CLEAN/MART | **No** — modello tabulare, non adatto al corpus MD |
| Disciplina toolkit dentro IC | **Sì** — stage nominati + layer clean/mart in `datasets/` |
| Toolkit come publisher downstream | **Sì** — clean+mart → GCS + registry; legal-graph punta al clean |

**In sintesi**: IC resta pipeline Normattiva lineare. Toolkit pubblica clean + mart analitici. legal-graph resta l'aggregatore.

