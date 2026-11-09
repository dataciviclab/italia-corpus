# Italia Corpus — la legislazione italiana in formato aperto

**20.790 atti normativi (22.410 espressioni), 367.544 riferimenti incrociati e il testo integrale di ogni atto.**

Italia Corpus raccoglie leggi, decreti legislativi, decreti-legge, regolamenti, DPCM, testi unici, codici e atti di recepimento delle direttive UE. I testi arrivano dall'API Normattiva OpenData in formato Akoma Ntoso, vengono convertiti in Markdown e pubblicati anche come parquet: cercabili per testo, struttura, materia e stato di vigenza.

Serve a rispondere a domande sulla legislazione con dati aperti e verificabili, senza dipendere da un portale.

## Cosa contiene

| | |
|---|---|
| **Atti normativi** | 22.410 espressioni / **20.790 atti distinti** (12.249 vigenti, 8.400 abrogati, 1.761 decaduti) |
| **Testo integrale** | 22.410 atti in Markdown e in parquet (~88 MB compressi) |
| **Riferimenti incrociati** | 367.544 archi tra atti (citazioni e abrogazioni) |
| **Allegati** | documenti allegati di 5.496 atti; indice parquet da 135.015 righe (963 documenti distinti) |
| **Materie** | 25 categorie tematiche (fisco, ambiente, lavoro, giustizia, …) |
| **Collezioni** | 20 collezioni ufficiali (decreti-legge e conversioni, decreti legislativi, codici, testi unici, DPCM, …) |
| **Copertura del catalogo** | **20.790 atti su 205.117** del catalogo Normattiva (10,1%) — denominatore da `atti_index`, non stimato |
| **Aggiornamento** | settimanale, il lunedì |

## Domande a cui risponde

- Quali decreti-legge non sono ancora stati convertiti?
- Quali leggi italiane recepiscono direttive UE, e con quanto ritardo?
- Quali atti normativi citano il Codice penale?
- Quali norme sulla sicurezza sul lavoro sono ancora vigenti?
- Quali norme fiscali hanno la qualità più alta?

## Come accedervi

### 1. MCP del Lab

Ricerca, testo e grafo sono esposti dal MCP **[legal-graph](https://github.com/dataciviclab/legal-graph)**: `legal_search`, `legal_node`, `legal_text`, `legal_query`, `legal_insights`.

```text
legal_search("decreti-legge ambiente energia")
legal_text("urn:nir:stato:decreto.legislativo:2001-06-08;231")
```

Ogni risultato porta con sé `stato` (vigente, abrogato, decaduto), `vigenza_fonte`, `materia`, `qualita_score`, `n_citazioni`, `orfano` e `sunsetting_score`. I filtri disponibili sono `stato`, `vigenza_fonte`, `materia`, `min_score` e `collezione`.

### 2. Parquet pubblici

I dataset sono su Google Cloud Storage, interrogabili con DuckDB anche da remoto:

```python
import duckdb

duckdb.sql("""
    SELECT tipo, anno_atto, COUNT(*) AS n
    FROM read_parquet(
      'https://storage.googleapis.com/dataciviclab-clean/italia-corpus/normativa/2026/normativa_2026_clean.parquet'
    )
    WHERE stato = 'vigente'
    GROUP BY tipo, anno_atto
    ORDER BY anno_atto DESC
    LIMIT 20
""").show()
```

| Dataset | Path GCS | Contenuto |
|---|---|---|
| `normativa` | `italia-corpus/normativa/2026/normativa_2026_clean.parquet` | metadati, stato di vigenza, materia, qualità |
| `riferimenti` | `italia-corpus/riferimenti/2026/riferimenti_2026_clean.parquet` | citazioni e abrogazioni tra atti |
| `testi` | `italia-corpus/testi/2026/testi_2026_clean.parquet` | testo integrale per atto |
| `atti_index` | `italia-corpus/atti_index/2026/atti_index_2026_clean.parquet` | catalogo ufficiale (205.117 atti) |
| `atti_api` | `italia-corpus/atti_api/2026/atti_api_2026_clean.parquet` | atti fuori collezione, con vigenza |
| `allegati` | `italia-corpus/allegati.parquet` | indice degli allegati (135.015 righe), testo sotto `allegati/` |

### 3. Testo in Markdown

I testi integrali sono anche nel repo, sotto `collezioni/<Collezione>/`, con frontmatter URN: si leggono e si citano direttamente da GitHub.

## Come è fatto

```text
API Normattiva (Akoma Ntoso XML)
  → conversione in Markdown + estrazione metadati
  → parquet derivati (normativa, riferimenti, testi)
  → clean e mart pubblicati su GCS, consumati da legal-graph e dal Lab
```

La pipeline è lineare e settimanale; i dettagli su stage, contratti e CI sono in **[docs/PIPELINE.md](docs/PIPELINE.md)**, il quadro in una pagina in **[docs/COSA_GIRA.md](docs/COSA_GIRA.md)**, la tassonomia delle materie in **[docs/MATERIA_AUDIT.md](docs/MATERIA_AUDIT.md)**.

## Limiti

- **Copertura**: 20.790 atti su 205.117 del catalogo (10,1%). Il corpus copre bene il diritto statale recente e "di sistema", non l'intero archivio storico.
- **Vigenza**: `stato` è formale e a livello di atto (lista ufficiale Normattiva); non distingue abrogazioni implicite o parziali. `esclusione` significa "non risulta abrogato", non certezza di vigenza.
- **Riferimenti**: derivano dai link Akoma Ntoso della fonte. Sui titoli generici possono puntare all'atto sbagliato: non sono rinvii verificati.
- **Testo**: il grano è il documento, non il singolo articolo (quest'ultimo è un follow-up). Il testo è quello pubblicato, non un consolidato con le modifiche.
- **Bersagli non risolti**: 26.410 URN citati non trovano un file nel corpus (direttive UE, URN ambigui o assenti dal catalogo).

## Partecipa

- **Hai una domanda sulla legislazione?** Apri una [Discussion](https://github.com/orgs/dataciviclab/discussions/new?category=Domanda).
- **Vuoi contribuire?** Vedi [come contribuire al Lab](https://github.com/dataciviclab/dataciviclab/blob/main/docs/come-contribuire.md).
- **Stato attuale, senza aprire il codice**: `make stato`.

## Licenza

- **Dati**: pubblico dominio (Normattiva).
- **Codice**: MIT.

Progetto del [DataCivicLab](https://github.com/dataciviclab).
