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

---

## Stage (canonici)

Ordine **critico** (uguale a CI e `make pipeline`):

| # | Stage | Comando | Output |
|---|---|---|---|
| 1 | **fetch** | `python -m lab_tools.fetch_normattiva [--only …]` | MD + `akn_*.parquet` (staging + merge) |
| 2 | **extract** | `python -m lab_tools.extract` | `normativa.parquet` (metadati base) |
| 3 | **classifica** | `python -m lab_tools.classifica_tematich` | + `materia` |
| 4 | **integra** | `python -m lab_tools.integra_costituzionali` | + cit. cost. / abrogazioni |
| 5 | **citazioni/pnrr/abrogations** | moduli `estrai_*` / `extract_*` | side product parquet |
| 6 | **grafo** | `python -m lab_tools.grafo_riferimenti` | `riferimenti` (regex∪AKN, denorm materia) |
| 7 | **arricchisci** | `python -m lab_tools.arricchisci_normativa` | + `n_citazioni`, `orfano`, `qualita_score` |
| 8 | **integra-akn** | `python -m lab_tools.integra_akn_meta` | + `ingresso_in_vigore`, `akn_*` |
| 9 | **sunsetting** | `python -m lab_tools.monitor_sunsetting` | + `sunsetting_score`, `eta_anni`, … |

**Makefile**: `make pipeline` (= 2–9, senza fetch)  
**CI**: stessa sequenza + fetch + contract check (main ⊂ derived)

> `classifica` **prima** di `grafo`: altrimenti `fonte_materia`/`bersaglio_materia` restano vuote.  
> `integra-akn` **dopo** `arricchisci`: preserva qualità + aggiunge AKN.  
> `sunsetting` **per ultimo**: usa `n_citazioni` e `riferimenti` già stabili.

---

## Output pubblici (contratti)

| Artifact | Contenuto | Consumatori tipici |
|---|---|---|
| Collezioni `*.md` | testo + frontmatter URN | MCP, agenti, ricerca |
| `normativa.parquet` | atto: metadati + qualità + materia/sunsetting + EIV/AKN | legal-graph, MCP, analisi |
| `riferimenti.parquet` | archi `peso`, `risolto`, `origine` (regex\|akn) | legal-graph, debt |
| `akn_relations.parquet` | relazioni AKN tipizzate (full-corpus su fetch completo) | clean/tabella propria, debug |
| `akn_act_meta.parquet` | EIV, mod counts, ELI per atto (join `urn` 100% su fetch completo) | vigenza, quality |
| `abrogations_raw.parquet` | fallback regex abrogazioni | analisi (AKN repeal = tipizzato) |

**Non committare**: zip, XML temporanei, `_akn_stage/`, `*.csv` locali.  
**Sì in git**: derived deliberati del contratto Lab (oggi versionati nel repo).

---

## Relazione con altri sistemi

| Sistema | Rapporto |
|---|---|
| **legal-graph** | Consuma URN/testi/parquet da IC (GitHub raw `main`). Dopo merge: `make run` LG. |
| **toolkit / DI** | IC non è `dataset.yml` standard. Disciplina toolkit interna, non migrazione RAW/MART. |
| **source-observatory** | Normattiva = fonte self-managed del corpus, non catalogo SO. |
| **cruscotto igiene** | Solo con decisione umana + dashboard dedicata. |

---

## Stato AKN (2026-10-08)

- Modulo: `lab_tools/akn_relations.py` (+ `integra_akn_meta.py`)
- Wire: fetch (staging+merge) · grafo (union citation, `origine`) · integra-akn
- **Copertura**: fetch completo 20 collezioni — meta join **22.017/22.017**, EIV **10.522**, archi AKN **43.880**, `akn_relations` tipizzato (inclusi repeal/substitution)
- CI: step `integra-akn` + ordine classifica→grafo + contract check
- Tests: `tests/test_akn_relations.py` (187 totali repo)

Non è un prodotto separato: è **stage fetch + 8** della pipeline sopra.

---

## Evoluzione toolkit — verdetto

| Opzione | Giudizio |
|---|---|
| Migrazione piena a toolkit RAW/CLEAN/MART | **No** — modello tabulare, non adatto al corpus MD |
| Disciplina toolkit dentro IC | **Sì** — stage nominati, output dichiarati, test |
| Toolkit come consumer downstream | **Sì** — se un parquet IC entra nel registry |

**In sintesi**: IC resta pipeline Normattiva lineare. Toolkit resta motore tabulare. legal-graph resta l’aggregatore.

