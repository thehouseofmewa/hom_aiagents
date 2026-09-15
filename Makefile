# HOM Voice Bot Backend - Local Development Setup
#
# Targets:
#   make setup          - create venv + install dependencies (dev)
#   make compile        - compile requirements.in -> requirements.txt (pip-tools)
#   make run            - run the FastAPI + Pipecat server locally
#   make run-pipeline   - run a single voice-agent pipeline directly
#   make lint           - run linters / type checks
#   make clean          - remove build artifacts

PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
APP ?= api.v1.main:app
PORT ?= 8080

.PHONY: setup compile dev run run-pipeline lint clean

## Create a virtualenv and install dependencies
setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements.in
	$(BIN)/pip install -r requirements-dev.in

## Compile requirements.in into a pinned requirements.txt (pip-tools)
compile:
	$(BIN)/pip install pip-tools
	$(BIN)/pip-compile requirements.in --output-file requirements.txt
	$(BIN)/pip-compile requirements-dev.in --output-file requirements-dev.txt

## Run the FastAPI + Pipecat server locally (auto-reload)
run:
	$(BIN)/uvicorn $(APP) --host 0.0.0.0 --port $(PORT) --reload

## Run a single voice-agent pipeline directly (edit run.py for the config)
run-pipeline:
	$(BIN)/python -m pipeline_building.run

## Lint and type check
lint:
	$(BIN)/ruff check .
	$(BIN)/mypy .

## Remove build artifacts and caches
clean:
	rm -rf $(VENV) __pycache__ .pytest_cache .mypy_cache
	find . -name "*.pyc" -delete