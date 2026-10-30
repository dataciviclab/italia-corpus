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
| 1 | **fetch** | `python -m lab_tools.fetch_normattiva [--only …]` | MD + `akn_*.parquet` (staging + merge) |
| 1b | **fetch-status** | `python -m lab_tools.fetch_status` | `status.parquet` (solo **abrogati**, classe 3 = lista ufficiale; no testo) |
| 2 | **extract** | `python -m lab_tools.extract` | `normativa.parquet` (metadati base) |
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

**CI**: stessa sequenza + fetch + fetch-status + lint + contract check (main ⊂ derived)
- `fetch-status` (solo classe 3, ~2 min) gira **ogni giorno**. In CI è **non fatale** (`continue-on-error`): se il WAF IPZS blocca il runner, resta lo status **in cache** (stale) e il build prosegue, con un `::warning::`. La freschezza di `stato` **non è garantita**; il vintage è in `status.parquet.fetched_at`.

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

## Output pubblici (contratti)

| Artifact | Contenuto | Consumatori tipici |
|---|---|---|
| `collezioni/**/*.md` | testo + frontmatter URN | MCP, agenti, ricerca |
| `normativa.parquet` | atto: metadati + identità (`versione`/`snapshot_data`/`is_current`) + qualità + materia/sunsetting + EIV/AKN + `stato`/`vigenza_fonte` | legal-graph, MCP, analisi |
| `status.parquet` | status atto-level autorevole (`codice_redazionale`+`data_gu` → `stato`, `classe`) | `integra-vigenza` (non pubblicato, non committato) |
| `atti_api.parquet` | leggi ordinarie fuori collezione (fetch `dettaglio-atto-urn`: vigenza + HTML) | legal-graph (nodi + target euristiche `attua_delega`) |
| `riferimenti.parquet` | archi `peso`, `risolto`, `origine` (regex\|akn) | legal-graph, debt |
| `allegati.parquet` | indice allegati AKN: `data_codice`+`doc_id` → `doc_name`, `chars`, `hash`, `versione`, `rel_path` (contenuto su GCS) | legal-graph (`legal_text`) |
| `akn_relations.parquet` | relazioni AKN tipizzate (full-corpus su fetch completo) | clean/tabella propria, debug |
| `akn_act_meta.parquet` | EIV, mod counts, ELI per atto (join `urn` 100% su fetch completo) | vigenza, quality |
| `abrogations_raw.parquet` | fallback regex abrogazioni | integra + analisi (AKN repeal = tipizzato) |

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

- Makefile: `make toolkit-check` · `make toolkit-run`
- Output: `out/data/{clean,mart}/<dataset>/2026/` (gitignored)
- **CI daily** (`build-dataset.yml`): engine + `toolkit-run` + rsync GCS
  `gs://dataciviclab-clean|mart/italia-corpus/` — **no registry PR**
- **CI schema** (`pipeline.yml`): reusable org su merge `datasets/**` + lunedì/dispatch
  → `toolkit-run` + registry draft PR (solo quando cambia il contratto)
- Dual-publish: derived resta in git per MCP; clean+mart su GCS sono il contratto Lab
- Warning attesi: `riferimenti` clean droppa denorm non usati da LG

**Perché no registry daily**: `registry.json` cambia a ogni run (`updated_at`,
`signals.run_id`) → una draft PR al giorno è rumore. Il contratto pubblico
(columns/locations) cambia solo con PR su `datasets/**`.

---

## Stato AKN (2026-10-08)

- Modulo: `lab_tools/akn_relations.py` (+ `integra_akn_meta.py`)
- Wire: fetch (staging+merge) · grafo (union citation, `origine`) · integra-akn
- **Copertura**: fetch completo 20 collezioni — meta join **22.017/22.017**, EIV **10.522**, archi AKN **43.880**, `akn_relations` tipizzato (inclusi repeal/substitution)
- CI: lint ruff · step `integra-akn` · ordine side-product→integra → grafo · contract check
- Tests: `tests/test_akn_relations.py` (187 totali repo)

Non è un prodotto separato: è **stage fetch + 8** della pipeline sopra.

---

## Evoluzione toolkit — verdetto

| Opzione | Giudizio |
|---|---|
| Migrazione piena a toolkit RAW/CLEAN/MART | **No** — modello tabulare, non adatto al corpus MD |
| Disciplina toolkit dentro IC | **Sì** — stage nominati + layer clean/mart in `datasets/` |
| Toolkit come publisher downstream | **Sì** — clean+mart → GCS + registry; legal-graph punta al clean |

**In sintesi**: IC resta pipeline Normattiva lineare. Toolkit pubblica clean + mart analitici. legal-graph resta l'aggregatore.

