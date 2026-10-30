# Italia Corpus — cosa gira, in una pagina

Serve a rispondere a "cosa succede qui?" senza leggere il codice.
Dettaglio degli stage: [PIPELINE.md](PIPELINE.md). Stato attuale: `make stato`.

## Cosa produce

Tre cose, nient'altro:

| Prodotto | Dove vive | A cosa serve |
|---|---|---|
| **Testi** (markdown delle leggi) | `collezioni/` — in git | lettura, `legal_text`, analisi testuale |
| **Dati** (parquet derivati) | `data/derived/` — parzialmente in git | citazioni, metadati, qualità, stato |
| **Pubblicazione** | GCS `dataciviclab-clean/italia-corpus/` | è ciò che legal-graph legge |

## Il giro settimanale (lunedì 03:30 UTC)

```text
1. probe      → guarda quali formati offre Normattiva (1 richiesta)
2. fetch      → scarica le collezioni, converte l'XML AKN in markdown
3. arricchisce→ stato ufficiale, materia, citazioni, qualità, EIV
4. catalogo   → enumera tutti gli atti che esistono (anche quelli che non abbiamo)
5. pubblica   → clean + mart su GCS, commit dei derivati
```

Se un passo di rete fallisce (WAF), il resto prosegue con i dati del giorno
prima: `make stato` mostra l'età di ogni file.

Ogni **giorno** gira solo il probe dei formati (`probe.yml`, 4 secondi): è
l'unico che deve accorgersi subito di un cambio di formato della fonte.

## Cosa toccare per cambiare cosa

| Se vuoi cambiare… | Tocca |
|---|---|
| quali leggi scaricare | `config/collezioni.txt` |
| come è fatto il markdown | `lab_tools/akn_parser.py` |
| i metadati di un atto | `lab_tools/extract.py` |
| le citazioni / il grafo | `lab_tools/grafo_riferimenti.py` |
| lo stato vigente/abrogato | `lab_tools/integra_vigenza.py` (fonte: `fetch_status`) |
| cosa vede legal-graph | `datasets/*/sql/clean.sql` (contratto pulito) |
| la classificazione tematica | `lab_tools/classifica_tematich.py` (+ gold set) |

## Come si guarda lo stato

```bash
make stato             # una schermata: freschezza, copertura, freeze
make probe-collezioni  # formati disponibili oggi (1 richiesta)
make test              # 380 test
```

## Fragilità note (e perché esistono)

1. **I testi stanno in git** (661 MB): da qui cache, sparse-checkout e commit
   giornalieri. È la decisione aperta più grossa.
2. **I formati della fonte cambiano senza preavviso** (30/10/2026: sparito il
   formato V su 5 collezioni). Per questo esiste il probe e il pin in config.
3. **L'ordine degli stage vive in 3 posti** (Makefile, CI, questo doc): non nel
   codice. Aggiungendo uno stage, aggiornali tutti.
4. **Metà delle citazioni non ha contesto** (archi AKN): dal 30/10 l'estrattore
   lo cattura, i parquet precedenti no → `clausola_lettura` è NULL lì.

## Le tre domande che questo repo non deve dimenticare

1. **Quanto del catalogo abbiamo?** → `atti_index` (205.115 atti, 10,1%).
2. **Quanto delle citazioni è diritto e quanto è cortesia?** → `clausola_lettura`.
3. **I dati sono freschi?** → `collezioni_probe.json` + `make stato`.

Se una modifica non aiuta a rispondere a una di queste, probabilmente non serve.
