# Italia Corpus — DataCivicLab

Fork Lab di [ahmeabd/italia-corpus](https://github.com/ahmeabd/italia-corpus). Corpus della legislazione italiana in Markdown da Normattiva, con tooling per estrazione metadati e ricerca full-text via MCP.

## Collezioni

Il fork Lab mantiene solo le **collezioni di attualità normativa** (~25.000 file, ~1.2 GB):

`DL e leggi di conversione` · `Decreti Legislativi` · `Leggi di ratifica` · `Regolamenti ministeriali` · `Regolamenti governativi` · `DPCM` · `Atti di recepimento direttive UE` · `Atti di attuazione Regolamenti UE` · `DL decaduti` · `DL proroghe` · `Decreti legislativi luogotenenziali` · `Leggi delega e relativi provvedimenti delegati` · `Leggi costituzionali` · `Leggi finanziarie e di bilancio` · `Leggi contenenti deleghe` · `Regolamenti di delegificazione` · `Regi decreti legislativi` · `Testi Unici` · `Codici`

(Il full corpus upstream ha 288.000+ file, il 90% dei quali è legislazione storica: atti abrogati, regi decreti, DPR.)

## Tooling Lab

### MCP server (`lab_tools/mcp_server.py`)

Due tool per agenti AI:

- **`italia-corpus_legal_search(query, limit, collezione)`** — cerca con ripgrep nel corpus. Case-insensitive, risponde in ~0.2s. Parametro `collezione` opzionale per limitare a una directory.
- **`italia-corpus_list_collections()`** — elenca le 20 collezioni disponibili.

### Estrattore metadati (`lab_tools/extract.py`)

Parsa tutti i file Markdown delle 20 collezioni ed estrae: tipo atto, data, numero, oggetto, entrata in vigore, CELEX, anno direttiva (dal CELEX più recente L/R), ritardo di recepimento.

Output: `data/derived/normativa.parquet` (20.711 atti deduplicati, 2.867 con CELEX).

```sh
pip install -e ".[dev]"
python -m lab_tools.extract
```

### CI / Workflow

| Workflow | Trigger | Cosa fa |
|---|---|---|
| `test.yml` | push / PR | pytest tests/ -v |
| `build-dataset.yml` | workflow_dispatch | test → extract → commit parquet |
| `sync-upstream.yml` | daily 7:00 + manuale | merge upstream → trigger build-dataset |

## Schema dataset

| Colonna | Tipo | Descrizione |
|---|---|---|
| `collezione` | str | Collezione d'origine (separatore `;` se multi-collezione) |
| `filename` | str | Nome file .md |
| `tipo` | str | DECRETO LEGISLATIVO, LEGGE, DECRETO-LEGGE, DPR, DPCM, ecc. |
| `data` | str | Data atto (ISO) |
| `numero` | str | Numero atto |
| `oggetto` | str | Oggetto / titolo |
| `entrata_vigore` | str | Data entrata in vigore (ISO, se disponibile) |
| `celex` | str | Riferimenti CELEX separati da `;` |
| `anno_atto` | int | Anno di pubblicazione |
| `anno_dir` | int | Anno della direttiva/regolamento UE collegato (dal CELEX L/R più recente, 0 se assente) |
| `ritardo` | float | Gap anni tra atto e direttiva (solo se anno_dir > 0) |

## Manutenzione

- Il sync upstream è automatico ogni giorno alle 7:00. Se il merge fallisce (conflitto), il workflow abortisce senza pushare.
- Dopo ogni sync, `build-dataset` rigenera automaticamente il parquet.
- Il dataset è committato su `main` (`data/derived/normativa.parquet`).

## Fork info

- **Upstream**: [ahmeabd/italia-corpus](https://github.com/ahmeabd/italia-corpus) — MIT license
- **Dati**: Pubblico dominio (Normattiva)
- **Lab**: [DataCivicLab](https://github.com/dataciviclab)
