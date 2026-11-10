.PHONY: install test lint pipeline pipeline-core extract grafo arricchisci classifica integra integra-vigenza integra-akn sunsetting citazioni abrogations fetch-status akn-relations atti-index direttive-ue probe-collezioni stato \
 toolkit-check toolkit-run toolkit-all run-batch fetch-raws check verify-smoke

# Pipeline completa (senza fetch — fetch è CI/manuale)
# Ordine onesto, coerente con build-dataset.yml:
#   classifica → side product → integra (legge da disco) → grafo → …
pipeline: extract classifica citazioni abrogations integra integra-vigenza grafo arricchisci integra-akn sunsetting

# Minimo per MCP / legal-graph: materia + grafo denorm + qualità + AKN + sunsetting.
# SENZA classifica perde materia e denorm grafo — non usarlo come contratto LG.
# Nota: senza `integra` (side product) manca abrogato_da → integra-vigenza
# applica solo gli override AKN (niente candidati regex).
pipeline-core: extract classifica integra-vigenza grafo arricchisci integra-akn sunsetting

TOOLKIT ?= python3 -m toolkit.cli.app
TOOLKIT_CONFIGS := $(wildcard datasets/*/dataset.yml)

# --- Layer toolkit (clean pubblico da data/derived → out/) ---

check: toolkit-check

toolkit-check:
	@for f in $(TOOLKIT_CONFIGS); do \
		echo "→ $$f"; \
		$(TOOLKIT) run preflight --config "$$f"; \
	done

# I raw stanno sul layer GCS, non in git: se uno manca (layer non ancora
# popolato, download fallito) il dataset va saltato, non deve far fallire la
# pubblicazione degli altri. Il warning è esplicito: se salta, il registry non
# si aggiorna per quel dataset.
toolkit-run:
	@if [ -z "$(BATCH)" ]; then $(MAKE) fetch-raws; fi
	@for f in $(if $(BATCH),$(shell cat $(BATCH) 2>/dev/null),$(TOOLKIT_CONFIGS)); do \
		case "$$f" in \
			*atti-index*) \
				if [ ! -f data/derived/atti_index.parquet ]; then \
					echo "⚠ salto $$f (atti_index.parquet assente)"; continue; \
				fi ;; \
			*direttive-ue*) \
				if [ ! -f data/derived/direttive_ue.parquet ]; then \
					echo "⚠ salto $$f (direttive_ue.parquet assente)"; continue; \
				fi ;; \
		esac; \
		echo "→ $$f"; \
		$(TOOLKIT) run --config "$$f" || exit 1; \
	done

toolkit-all: toolkit-run

# Raw derivati: `data/derived` non è più in git. Il publish (batch o full) e
# derive-smoke li scaricano dal raw layer pubblico su GCS. `testi` (98 MB)
# resta generato da `extract --testi-only`: rigenerarlo costa meno che
# scaricarlo. In locale: `make fetch-raws` prima di `make toolkit-run`.
RAWS := normativa riferimenti akn_relations akn_act_meta abrogations_raw atti_api direttive_ue atti_index allegati status
RAW_BASE ?= https://storage.googleapis.com/dataciviclab-clean/italia-corpus/_raw/2026

fetch-raws:
	@mkdir -p data/derived
	@for f in $(RAWS); do \
		if [ ! -s "data/derived/$$f.parquet" ]; then \
			echo "→ raw $$f"; \
			curl -fsSL "$(RAW_BASE)/$$f.parquet" -o "data/derived/$$f.parquet" \
				|| { echo "⚠ $$f non disponibile sul raw layer"; rm -f "data/derived/$$f.parquet"; continue; }; \
			python -c "import pyarrow.parquet as pq,sys; pq.read_schema(sys.argv[1])" "data/derived/$$f.parquet" 2>/dev/null \
				|| { echo "⚠ $$f illeggibile (download troncato)"; rm -f "data/derived/$$f.parquet"; }; \
		fi; \
	done

# Batch selettivo: il reusable scrive batch.txt con i dataset.yml cambiati.
# Scarica dal raw layer SOLO il raw del dataset toccato (non 50 MB).
run-batch:
	@test -s batch.txt || { echo "batch.txt mancante o vuoto"; exit 1; }
	@raws=""; for f in $$(cat batch.txt); do \
		case "$$f" in \
			*akn-act-meta*) raws="$$raws akn_act_meta" ;; \
			*akn-relations*) raws="$$raws akn_relations" ;; \
			*atti-api*) raws="$$raws atti_api" ;; \
			*atti-index*) raws="$$raws atti_index" ;; \
			*direttive-ue*) raws="$$raws direttive_ue" ;; \
			*normativa*) raws="$$raws normativa" ;; \
			*riferimenti*) raws="$$raws riferimenti" ;; \
		esac; \
	done; \
	$(MAKE) fetch-raws RAWS="$$raws"; \
	$(MAKE) toolkit-run BATCH=batch.txt

# Gate pre-push rapido: le stesse stage del derive-smoke CI (grafo + arricchisci).
# Non fa fetch. Sovrascrive data/derived/{normativa,riferimenti}.parquet:
# dopo il check, `git checkout -- data/derived` per tornare puliti.
verify-smoke:
	python -m lab_tools.grafo_riferimenti
	python -m lab_tools.arricchisci_normativa

install:
	pip install -e ".[dev,pipeline]"

test:
	python -m pytest tests/ -v

lint:
	python -m ruff check lab_tools/ tests/

extract:
	python -m lab_tools.extract

classifica:
	python -m lab_tools.classifica_tematich

integra:
	python -m lab_tools.integra_costituzionali

integra-vigenza:
	python -m lab_tools.integra_vigenza

fetch-status:
	python -m lab_tools.fetch_status

# Backfill manuale dell'indice allegati AKN (il fetch quotidiano lo aggiorna
# già via `allegati.scrivi_atto`; questo serve per una ricostruzione completa)
fetch-allegati:
	python -m lab_tools.fetch_allegati

# Stato del corpus in una schermata (nessuna rete, nessuna scrittura)
stato:
	python -m lab_tools.stato

# Una richiesta: formati disponibili per collezione (O/V/M) + storia dei freeze
probe-collezioni:
	python -m lab_tools.collezioni_probe

# Indice del catalogo Normattiva (metadati, nessun testo) — richiede normativa.parquet
atti-index:
	python -m lab_tools.atti_index

# Identità e misure nazionali delle direttive UE citate (CELLAR) — cache in out/
direttive-ue:
	python -m lab_tools.fetch_direttive_ue

citazioni:
	python -m lab_tools.estrai_citazioni_costituzionali

abrogations:
	python -m lab_tools.extract_abrogations

grafo:
	python -m lab_tools.grafo_riferimenti

arricchisci:
	python -m lab_tools.arricchisci_normativa

integra-akn:
	python -m lab_tools.integra_akn_meta

sunsetting:
	python -m lab_tools.monitor_sunsetting

akn-relations:
	python -m lab_tools.akn_relations --xml-dir data/xml --outdir data/derived --merge
