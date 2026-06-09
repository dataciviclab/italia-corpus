.PHONY: install test extract mcp

install:
	pip install -e ".[dev,mcp]"

test:
	python -m pytest tests/ -v

extract:
	python -m lab_tools.extract

mcp:
	python -m lab_tools.mcp_server
