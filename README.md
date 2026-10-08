# Italia Corpus — La legislazione italiana a portata di ricerca

**22.016 atti normativi, da codici a decreti-legge, in formato aperto e interrogabile.**

Il corpus della legislazione italiana: leggi, decreti legislativi,
decreti-legge, regolamenti, DPCM, testi unici, codici e atti di recepimento UE.
Scaricati direttamente dall'API Normattiva OpenData, convertiti da Akoma Ntoso XML
a Markdown. Tutto cercabile per testo, struttura e materia.

## Cosa contiene

| | |
|---|---|
| **Atti normativi** | 22.016 (12.901 vigenti, 7.354 abrogati, 1.761 decaduti) |
| **Collezioni** | 20 (DL e conversioni, decreti legislativi, codici, testi unici, DPCM...) |
| **Riferimenti incrociati** | 92.580 archi tra atti |
| **Materie** | 25 categorie (fisco, ambientale, lavoro, giustizia, etc.) |
| **Aggiornamento** | Fetch giornaliero diretto dall'API Normattiva |

## Esempi di domande

- **Quali decreti-legge non sono ancora stati convertiti?**
- **Quali leggi italiane recepiscono direttive UE?** E con quanto ritardo?
- **Quali atti normativi citano il Codice Penale?**
- **Quali atti sulla sicurezza lavoro sono ancora vigenti?**
- **Quali norme fiscali hanno qualità più alta?**

## Tre modi per accedere ai dati

### 1. Via MCP — ricerca in linguaggio naturale

Collega il server MCP del corpus al tuo assistente AI:

```
"Trova i decreti-legge che citano ambiente ed energia"
"Mostrami il testo del D.Lgs. 231/2001"
"Cerca solo atti vigenti con qualità alta"
```

Ogni risultato include `stato` (vigente/abrogato/decaduto), `qualita_score` (0-100),
`materia`, `orfano`, `n_citazioni`, `duplicato` e `sunsetting_score`.
Filtri disponibili: `stato`, `min_score`, `materia`, `max_sunsetting`.

### 2. Via SQL su parquet

```python
import duckdb
duckdb.sql("""
    SELECT tipo, anno_atto, COUNT(*) AS n
    FROM read_parquet('data/derived/normativa.parquet')
    WHERE stato = 'vigente'
    GROUP BY tipo, anno_atto
    ORDER BY anno_atto DESC
    LIMIT 20
""").show()
```

### 3. Via download parquet

- `data/derived/normativa.parquet` — 22.016 atti, 26 colonne
- `data/derived/riferimenti.parquet` — 92.580 riferimenti, 15 colonne

## Approfondimenti

- [Grafo dei riferimenti normativi](https://github.com/dataciviclab/italia-corpus) — quale atto cita cosa, con peso
- [Normattiva](https://www.normattiva.it) — fonte originale dei testi

## Partecipa

- **Hai una domanda sulla legislazione?** Apri una [Discussion](https://github.com/orgs/dataciviclab/discussions/new?category=Domanda)
- **Vuoi contribuire?** Vedi [come contribuire al Lab](https://github.com/dataciviclab/dataciviclab/blob/main/docs/come-contribuire.md)

## Documentazione tecnica

Pipeline canonica (stage lineari, output dichiarati): **[docs/PIPELINE.md](docs/PIPELINE.md)**.

### Tooling

| Stage | Tool | Output |
|---|---|---|
| fetch | **Fetch Normattiva** | MD in `collezioni/` + `akn_relations` / `akn_act_meta` (merge) |
| extract | **Extract metadati** | `normativa.parquet` |
| grafo | **Grafo riferimenti** | `riferimenti.parquet` (`origine`: regex\|akn) |
| arricchisci | **Qualità grafo** | `n_citazioni`, `orfano`, `qualita_score` |
| integra-akn | **Join AKN meta** | `ingresso_in_vigore`, `akn_*` (se presenti) |
| classifica | **Classifica tematico** | `materia` (downstream) |
| integra | **Costituzionali** | cit. cost. / abrogazioni (downstream) |
| — | **MCP server** | ricerca full-text sul corpus MD |

### CI / Manutenzione

- **Build** (06:30): fetch → extract → classifica → integra → side product → grafo → arricchisci → **integra-akn** → sunsetting
- **Locale**: `make pipeline` (stesso ordine, senza fetch)
- **Test**: `pytest tests/ -v` su ogni push/PR
- **Ruolo Lab**: IC produce MD+parquet; **legal-graph** li aggrega — non duplicare grafi qui
- Contratto: `normativa` ⊇ colonne main CI + campi AKN (`ingresso_in_vigore`, `akn_*`)

### Schema `normativa.parquet` (colonne base + enrichment AKN)

Base atto: `collezione`, `filename`, `tipo`, `data`, `numero`, `oggetto`, `celex`,
`anno_atto`, `anno_dir`, `ritardo`, `urn`, `codice_redazionale`,
`stato`, `vigente`, `lunghezza_caratteri`, `lunghezza_parole`,
`riferimenti_interni`, `duplicato`, `n_citazioni`, `orfano`, `qualita_score`

Downstream: `materia`, `n_articoli_cost`, `articoli_cost`, `abrogato_da`, `n_abrogazioni`, …

Enrichment AKN (da stage integra-akn, se artifact presenti):
`ingresso_in_vigore`, `akn_n_refs`, `akn_n_active_mods`, `akn_n_passive_ref`,
`akn_n_repeal_events`, `akn_mod_types`, `akn_has_workflow`, `akn_meta_source`

Colonne di qualità:

| Colonna | Tipo | Significato |
|---|---|---|
| `stato` | string | `vigente` \| `abrogato` \| `decaduto` — dai marker Normattiva nel body. ⚠️ Rilevato solo per atti con snapshot VIGENZA; gli atti solo ORIGINALE risultano `vigente` per costruzione |
| `vigente` | bool | `stato == 'vigente'` (il frontmatter MD di Normattiva è inaffidabile) |
| `duplicato` | bool | Stesso atto (data+numero) presente più volte nel corpus |
| `n_citazioni` | int | Citazioni in ingresso dal grafo riferimenti |
| `orfano` | bool | Nessuna citazione in uscita né in ingresso |
| `qualita_score` | int | 0-100, più alto = migliore (penalizza duplicati, orfani, stato non vigente) |
| `materia` | string | Classificazione tematica: fisco, ambientale, lavoro, etc. (25 categorie) |
| `n_articoli_cost` | int | Numero di articoli costituzionali citati dall'atto |
| `articoli_cost` | string | Articoli costituzionali citati (separati da virgola) |
| `abrogato_da` | string | File che abrogano questo atto |
| `n_abrogazioni` | int | Numero di abrogazioni che riguardano questo atto |
| `eta_anni` | int | Anni dall'atto (anno corrente - anno_atto) |
| `sunsetting_score` | int | 0-100, più alto = più candidato alla decadenza automatica |

### Schema `riferimenti.parquet` (15 colonne)

`fonte_filename`, `fonte_collezione`, `fonte_anno`, `fonte_tipo`,
`fonte_materia`, `fonte_stato`,
`bersaglio_filename`, `bersaglio_path`, `bersaglio_collezione`,
`bersaglio_anno`, `bersaglio_tipo`, `bersaglio_materia`, `bersaglio_stato`,
`peso`, `risolto`

Path nei campi path: relativi a `collezioni/` (es. `Codici/x.md`).
`bersaglio_filename` e `normativa.filename` sono basename.
Vedi [docs/PIPELINE.md](docs/PIPELINE.md) per le convenzioni path complete.

## Licenza

- **Dati**: Pubblico dominio (Normattiva)
- **Codice**: MIT

Progetto del [DataCivicLab](https://github.com/dataciviclab).
