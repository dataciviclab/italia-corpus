.PHONY: install test pipeline extract grafo arricchisci classifica integra integra-akn mcp akn-relations

# Pipeline canonica nucleo (1-5) — vedi docs/PIPELINE.md
# fetch è volutamente manuale/CI: scarica da Normattiva.
pipeline: extract grafo arricchisci integra-akn

install:
	pip install -e ".[dev,mcp]"

test:
	python -m pytest tests/ -v

extract:
	python -m lab_tools.extract

grafo:
	python -m lab_tools.grafo_riferimenti

arricchisci:
	python -m lab_tools.arricchisci_normativa

integra-akn:
	python -m lab_tools.integra_akn_meta

classifica:
	python -m lab_tools.classifica_tematich

integra:
	python -m lab_tools.integra_costituzionali

sunsetting:
	python -m lab_tools.monitor_sunsetting

akn-relations:
	python -m lab_tools.akn_relations --xml-dir data/xml --outdir data/derived --merge

mcp:
	python -m lab_tools.mcp_server
