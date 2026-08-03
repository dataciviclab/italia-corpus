# Italia Corpus — La legislazione italiana a portata di ricerca

**20.716 atti normativi, da codici a decreti-legge, in formato aperto e interrogabile.**

Il corpus della legislazione italiana vigente da Normattiva: leggi, decreti
legislativi, decreti-legge, regolamenti, DPCM, testi unici, codici e atti di
recepimento UE. Tutto in Markdown, cercabile per testo e struttura.

## Cosa contiene

| | |
|---|---|
| **Atti normativi** | 20.716 (da ~25.000 file) |
| **Collezioni** | 20 (DL e conversioni, decreti legislativi, codici, testi unici, DPCM...) |
| **Riferimenti incrociati** | 108.490 archi tra atti |
| **Atti con CELEX** | 757 (collegati alla normativa UE) |
| **Atti più citato** | Codice Penale (7.815 riferimenti) |
| **Aggiornamento** | Sincronizzazione automatica giornaliera da Normattiva |

## Esempi di domande

- **Quali decreti-legge non sono ancora stati convertiti?**
- **Quali leggi italiane recepiscono direttive UE?** E con quanto ritardo?
- **Quali atti normativi citano il Codice Penale?**
- **Come è cambiato il numero di decreti-legge negli anni?**
- **Quali testi unici sono ancora vigenti?**

## Tre modi per accedere ai dati

### 1. Via MCP — ricerca in linguaggio naturale

Collega il server MCP del corpus al tuo assistente AI:

```
"Trova i decreti-legge che citano ambiente ed energia"
"Mostrami il testo del D.Lgs. 231/2001"
```

### 2. Via SQL su parquet

```python
import duckdb
duckdb.sql("""
    SELECT tipo, anno_atto, COUNT(*) AS n
    FROM read_parquet('data/derived/normativa.parquet')
    GROUP BY tipo, anno_atto
    ORDER BY anno_atto DESC
    LIMIT 20
""").show()
```

### 3. Via download parquet

- `data/derived/normativa.parquet` — metadati di 20.716 atti (14 colonne)
- `data/derived/riferimenti.parquet` — 108.490 riferimenti tra atti (10 colonne)

## Approfondimenti

- [Grafo dei riferimenti normativi](https://github.com/dataciviclab/italia-corpus) — quale atto cita cosa, con peso
- [Normattiva](https://www.normattiva.it) — fonte originale dei testi

## Partecipa

- **Hai una domanda sulla legislazione?** Apri una [Discussion](https://github.com/orgs/dataciviclab/discussions/new?category=Domanda)
- **Vuoi contribuire?** Vedi [come contribuire al Lab](https://github.com/dataciviclab/dataciviclab/blob/main/docs/come-contribuire.md)

## Documentazione tecnica

### Tooling

| Tool | Cosa fa |
|---|---|
| **MCP server** | Ricerca full-text, recupero documenti, elenco collezioni |
| **Estrattore metadati** | Parsa i Markdown → `normativa.parquet` (tipo, data, URN, CELEX...) |
| **Grafo riferimenti** | Costruisce gli archi fonte → bersaglio tra atti |

### CI / Manutenzione

- **Sync giornaliero** (7:00): aggiorna le collezioni da Normattiva
- **Build dataset**: rigenera i parquet dopo ogni sync
- **Test**: `pytest tests/ -v` su ogni push/PR

### Schema `normativa.parquet`

`collezione`, `filename`, `tipo`, `data`, `numero`, `oggetto`, `celex`,
`anno_atto`, `anno_dir`, `ritardo`, `urn`, `codice_redazionale`,
`lunghezza_caratteri`, `lunghezza_parole`, `riferimenti_interni`

### Schema `riferimenti.parquet`

`fonte_filename`, `fonte_collezione`, `fonte_anno`, `fonte_tipo`,
`bersaglio_filename`, `bersaglio_path`, `risolto`, `bersaglio_collezione`,
`bersaglio_anno`, `bersaglio_tipo`, `peso`

## Licenza

- **Dati**: Pubblico dominio (Normattiva)
- **Codice**: MIT

Progetto del [DataCivicLab](https://github.com/dataciviclab).
