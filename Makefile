.PHONY: install test pipeline pipeline-core extract grafo arricchisci classifica integra integra-akn sunsetting citazioni pnrr abrogations mcp akn-relations

# Pipeline completa (senza fetch — fetch è CI/manuale)
# Ordine coerente con .github/workflows/build-dataset.yml
# classifica PRIMA di grafo (denorm materia); integra-akn DOPO arricchisci
pipeline: extract classifica integra citazioni pnrr abrogations grafo arricchisci integra-akn sunsetting

# Nucleo tabulari senza side-product (minimo per MCP/LG)
pipeline-core: extract grafo arricchisci integra-akn

install:
	pip install -e ".[dev,mcp]"

test:
	python -m pytest tests/ -v

extract:
	python -m lab_tools.extract

classifica:
	python -m lab_tools.classifica_tematich

integra:
	python -m lab_tools.integra_costituzionali

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

mcp:
	python -m lab_tools.mcp_server
