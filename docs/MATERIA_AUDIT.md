# Audit del campo `materia` — italia-corpus

**Esito**: il campo era inutilizzabile come filtro (precision 56%); dopo il fix è
all'**81,5%** su 200 atti annotati a mano, con **zero regressioni** su due campioni
indipendenti. Il fix cambia etichetta al **31,1%** del corpus (6.855 atti).

2026-10-28 · stage `classifica` (`lab_tools/classifica_tematich.py`) · PR #80

## 1. Cos'era

25 categorie / 282 keyword, match **substring case-insensitive** sull'`oggetto`,
"primo match vince" secondo l'ordine della lista. Nessun confine di parola.

| difetto | effetto misurato |
|---|---|
| match dentro altre parole | `iva` matchava "rel**ativa**", "riatt**iva**zione" (3.229 titoli, 30 legittimi); `arte` → "p**arte**"; `rai` → "contr**rai**"; `nato` → "desti**nato**"; `posta` → "im**posta**"; `sport` → "tra**sport**i" |
| parola intera senza confine destro | `comuni` → "comuni**taria**"; `pac` → "**pac**e"/"ca**pac**ità" |
| codice redazionale nel match | `5g` dentro "**15G**00065" |
| keyword morte o typo | 28 su 282 non matchavano mai (`anticorruzione`, `internet`, `pmi`, `non profit`); `iregionali` e `entrare delle entrate` erano typo |
| keyword duplicata | `inps` in `istruzione` e `previdenza`: vinceva `istruzione` |
| radici incomplete | `patente` non copriva "patenti"; `turism` non copriva "turistico" |
| keyword troppo generiche | `contribut` (contributi ≠ tributi), `civile` ("protezione civile"), `circolazione` ("libera circolazione dei dati"), `procedur`, `sociali`, `paesaggio` |
| trattati non distinti | 4 ratifiche di atti interni in `affari-esteri`, 4 trattati veri senza etichetta |

Atti flagship: Codice comunicazioni elettroniche `enti-locali`→`comunicazioni`;
Codice beni culturali `ambientale`→`cultura`; Codice privacy `fisco`→`altro`;
Codice crisi d'impresa `fisco`→`industria`.

## 2. Cosa è cambiato

Un solo file di pipeline, `lab_tools/classifica_tematich.py`. **Nessuna categoria
aggiunta o rinominata**: contratto pubblico invariato (25 valori, filtro `materia=`
del MCP legal-graph).

1. **Confine a sinistra** su tutte le keyword (radici libere a destra); **confine a
   destra** per la lista esplicita `_PAROLA_INTERA` (parole intere e acronimi).
2. **Normalizzazione**: rimosso il codice redazionale in coda.
3. **Tier trattati** → `affari-esteri` (ratifica ed esecuzione, trattato, scambio di
   note, memorandum, accordo/convenzione fra Governi, protocollo internazionale).
   La ratifica di un atto interno segue le keyword tematiche.
4. **Igiene keyword**: typo rimossi, `inps` deduplicata, radici completate
   (`patent`, `turist`, `editric`, `professor`, `teatr`, `restaur`, `dogan`,
   `agrar`, `agronom`, `scolastic`, `insegnant`, `forense`, `sequestr`,
   `impugnazion`, `valutari`), generiche ristrette (`civile`, `procedur`,
   `circolazione`, `sociali`, `impiego`, `contribut`, `paesaggio`).
5. **`strutturale` resta fallback** (conversione/delega).

## 3. Come è stato misurato

Due campioni **stratificati indipendenti da 100 atti** (unità = atto, dedup per
`urn`), allocazione proporzionale con minimo 2 per categoria, annotati a mano
leggendo il titolo (e il rinvio al decreto-legge per le conversioni). Il secondo è
disgiunto dal primo: serve a non dichiarare un guadagno da overfitting.

| campione | baseline | dopo il fix | confidenza alta |
|---|---|---|---|
| `materia_gold.csv` (sviluppo, seed 42) | 56% | **81%** | 54/82 → 75/82 |
| `materia_gold_holdout.csv` (validazione, seed 7) | 56% | **82%** | 50/76 → 71/76 |
| **totale 200 atti** | **56,0%** | **81,5%** | — |

Regressioni (atti azzeccati dalla baseline e rotti dal fix): **0**.

```bash
pytest tests/test_classifica.py tests/test_classifica_gold.py
pytest tests/test_classifica_gold.py -s   # precision per materia e causa di errore
```

## 4. Cause residue (37 errori su 200)

| causa | n | nota |
|---|---|---|
| `keyword-mancante` | 10 | il tema esiste ma non ha keyword (statuto di agenzia, controllo interno, corte di appello) |
| `gap-tassonomia` | 8 | credito/finanza, assicurazioni, privacy, casa/immobiliare, metrologia |
| `natura-atto` | 8 | conversioni il cui oggetto non ha keyword → resta `strutturale` |
| `giudizio-ambiguo` | 8 | annotazione a bassa confidenza (multi-tema, pubblico impiego) |
| `keyword-conflitto` | 3 | `militar` in "Sovrano Militare Ordine di Malta", `aeronautic` in "Arma aeronautica", `ferrovie` in "pensioni del personale FS" |

## 5. Limiti dichiarati

- n=100 per campione → IC 95% sulla precision ≈ ±8 punti; la precision **per
  categoria non è stimabile** per le classi con 2-3 atti nel campione.
- Annotazione **da agente AI** sul titolo (+ rinvio), non validazione giuridica del
  contenuto; le righe a bassa confidenza sono marcate nel CSV.
- La gold misura la tassonomia attuale: se le categorie cambiano va estesa, non riusata.

## 6. Impatto

`materia` è contratto pubblico: MCP legal-graph (`materia=`), `mart_materia_stato`,
`mart_candidati_sunsetting`, e denormalizzata in `riferimenti.parquet`
(`fonte_materia`/`bersaglio_materia`).

| | prima | dopo |
|---|---|---|
| `fisco` | 4.896 (22,2%) | 1.951 (8,9%) |
| `cultura` | 977 (4,4%) | 427 (1,9%) |
| `affari-esteri` | 2.062 (9,4%) | 3.038 (13,8%) |
| `altro` | 2.865 (13,0%) | 3.735 (17,0%) |
| `recepimento-ue` | 40 (0,2%) | 844 (3,8%) |
| `sport` | 159 | 56 |

Catena rigenerata in locale: `classifica` → `grafo` (30% dei 136.403 archi cambia
`fonte_materia`/`bersaglio_materia`) → `make toolkit-run` (clean + mart, validate ok).

## 7. Follow-up (issue #81)

1. **Natura vs materia**: `strutturale` (12,2%) e `recepimento-ue` (3,8%) descrivono
   la natura dell'atto. 822 atti sono `recepimento-ue`, di cui 270 hanno anche una
   materia nel titolo. Spostarli in coda peggiora la gold misurata (82%→81%):
   serve una colonna `natura_atto`, non uno scambio di ordine.
2. **Categorie mancanti**: credito/finanza, assicurazioni, privacy/dati personali,
   casa/immobiliare, metrologia. Aggiungerne una è un cambio di contratto.
3. **Multi-etichetta**: ~5% degli atti ha due temi co-primari; il secondo è perso
   (colonna `materia_secondaria` già nella gold).
4. `legal-graph/docs/ANALISI.md` cita "Materia IC = cultura" per il D.Lgs 33/2013
   come esempio di etichetta fuorviante: con il fix non è più vero.
