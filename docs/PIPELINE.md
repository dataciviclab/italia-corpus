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

| # | Stage | Comando | Output |
|---|---|---|---|
| 1 | **fetch** | `python -m lab_tools.fetch_normattiva [--only …]` | MD nelle collezioni · `data/derived/akn_*.parquet` (merge) |
| 2 | **extract** | `python -m lab_tools.extract` | `normativa.parquet` |
| 3 | **grafo** | `python -m lab_tools.grafo_riferimenti` | `riferimenti.parquet` (`origine`: regex\|akn) |
| 4 | **arricchisci** | `python -m lab_tools.arricchisci_normativa` | + `n_citazioni`, `orfano`, `qualita_score` |
| 5 | **integra-akn** | `python -m lab_tools.integra_akn_meta` | + `ingresso_in_vigore`, `akn_*` (se artifact presenti) |
| 6 | **classifica** | `python -m lab_tools.classifica_tematich` | + `materia` |
| 7 | **integra** | `python -m lab_tools.integra_costituzionali` | + cit. costituzionali / abrogazioni |
| 8 | **sunsetting** *(opz)* | `python -m lab_tools.monitor_sunsetting` | + `sunsetting_score` |

**Makefile**: `make extract grafo arricchisci integra-akn classifica integra`  
**CI**: fetch automatico → stessi stage tabulari.

Stage 6–8 sono **downstream** opzionali per le analisi; 1–5 sono il nucleo “dati utili all’ecosistema”.

---

## Output pubblici (contratti)

| Artifact | Contenuto | Consumatori tipici |
|---|---|---|
| Collezioni `*.md` | testo + frontmatter | MCP, agenti, ricerca |
| `normativa.parquet` | una riga per atto (metadati + qualità) | analisi, Explorer, compose |
| `riferimenti.parquet` | archi fonte→bersaglio (`peso`, `risolto`, `origine`) | legal-graph, debt, grafi |
| `akn_relations.parquet` | relazioni AKN tipizzate (quando presenti) | arricchimenti, debug fonte |
| `akn_act_meta.parquet` | EIV, mod counts, ELI per atto (quando presenti) | vigenza più onesta |
| `abrogations_raw.parquet` | fallback regex abrogazioni | analisi legacy |

**Non committare**: zip, XML temporanei, output runtime.  
**Sì in git se fanno parte del contratto**: solo se il repo li versiona deliberatamente (oggi i parquet derived sono prodotti CI/locali — verificare `.gitignore`).

---

## Relazione con altri sistemi

| Sistema | Rapporto |
|---|---|
| **legal-graph** | Consuma URN/testi/relazioni da IC (e altre fonti). Non duplicare grafi dentro IC. |
| **toolkit / DI** | IC non è un `dataset.yml` standard. Se mai servisse registro, va come *corpus project* dichiarato, non forzato in CLEAN/MART. |
| **source-observatory** | Normattiva è fonte self-managed del corpus, non catalogo scoutato SO. |
| **cruscotto igiene** | Solo se decisione umana + dashboard dedicata. Altrimenti analisi in `_local/` o Discussion. |

---

## Stato AKN (2026-10-07)

- Modulo: `lab_tools/akn_relations.py`
- Wire: fetch (merge) + grafo (union citation) + `integra_akn_meta`
- Copertura: parziale finché non si refetchano tutte le collezioni **V**
- Tests: `tests/test_akn_relations.py`

Non è un prodotto separato: è **stage 1 + 5** della pipeline sopra.

---

## Evoluzione toolkit — verdetto

| Opzione | Giudizio |
|---|---|
| Migrazione piena a toolkit RAW/CLEAN/MART | **No** — modello tabulare, non adatto al corpus MD; perdita di chiarezza |
| Disciplina toolkit dentro IC | **Sì** — stage nominati, output dichiarati, test, niente magia |
| Toolkit come consumer downstream | **Sì** — se un giorno un parquet IC diventa dataset registry |

**In sintesi**: IC resta pipeline Normattiva lineare. Toolkit resta motore tabulare del Lab. legal-graph resta l’aggregatore. Non li sovrappiamo.
