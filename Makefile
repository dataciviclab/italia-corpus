.PHONY: install test extract grafo arricchisci classifica integra mcp

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

classifica:
	python -m lab_tools.classifica_tematich

integra:
	python -m lab_tools.integra_costituzionali

sunsetting:
	python -m lab_tools.monitor_sunsetting

mcp:
	python -m lab_tools.mcp_server
