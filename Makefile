.PHONY: install test lint pipeline pipeline-core extract grafo arricchisci classifica integra integra-vigenza integra-akn sunsetting citazioni pnrr abrogations fetch-status akn-relations atti-index probe-collezioni stato \
 toolkit-check toolkit-run toolkit-all check

# Pipeline completa (senza fetch — fetch è CI/manuale)
# Ordine onesto, coerente con build-dataset.yml:
#   classifica → side product → integra (legge da disco) → grafo → …
pipeline: extract classifica citazioni pnrr abrogations integra integra-vigenza grafo arricchisci integra-akn sunsetting

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

# atti-index dipende da un artefatto non committato (drift, come status):
# in un contesto dove non è stato generato (es. registry workflow su checkout
# pulito) il dataset va saltato, non deve far fallire la pubblicazione degli
# altri. Il warning è esplicito: se salta, il registry non si aggiorna.
toolkit-run:
	@for f in $(TOOLKIT_CONFIGS); do \
		case "$$f" in \
			*atti-index*) \
				if [ ! -f data/derived/atti_index.parquet ]; then \
					echo "⚠ salto $$f (atti_index.parquet assente)"; continue; \
				fi ;; \
		esac; \
		echo "→ $$f"; \
		$(TOOLKIT) run --config "$$f" || exit 1; \
	done

toolkit-all: toolkit-run

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

citazioni:
	python -m lab_tools.estrai_citazioni_costituzionali

pnrr:
	python -m lab_tools.extract_pnrr_refs

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
