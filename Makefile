SHELL := /bin/bash
PY ?= .venv/bin/python
PIP ?= .venv/bin/pip
export PYTHONPATH := src
export PYTHONHASHSEED := 0

.PHONY: help setup fetch-data prepare audit demo-cases calibrate eval test app api verify interactive-baseline peak-exclusion-spike

help:
	@echo "UnknownID targets"
	@echo "  make setup       create .venv and install the package + dev tools"
	@echo "  make fetch-data  sparse-clone the pinned MassBank Athens_Univ snapshot"
	@echo "  make prepare     curate, audit, split and fit the error model"
	@echo "  make audit       show the data-audit go/no-go gate"
	@echo "  make demo-cases  write anonymised demo case IDs"
	@echo "  make calibrate   select the acquisition method on the dev split"
	@echo "  make eval        run frozen test-split baselines and bootstrap intervals"
	@echo "  make test        run the synthetic test-suite (includes anti-leakage tests)"
	@echo "  make app         launch the five-screen Streamlit UI"
	@echo "  make api         launch the FastAPI backend on :8000"
	@echo "  make verify      run tests + import/config smoke checks"

setup:
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

fetch-data:
	bash scripts/fetch_data.sh

prepare:
	$(PY) scripts/prepare_data.py

audit:
	@test -f reports/data_audit.md || (echo "run 'make prepare' first" >&2; exit 1)
	@grep -E "go/no-go|PASS|FAIL|complete cases|ambiguous" reports/data_audit.md | head -30

demo-cases:
	$(PY) scripts/make_demo_cases.py

calibrate:
	$(PY) scripts/calibrate.py

eval:
	$(PY) scripts/run_eval.py

test:
	$(PY) -m pytest -q

app:
	$(PY) -m streamlit run app/streamlit_app.py

api:
	$(PY) -m uvicorn unknownid.api.app:app --host 127.0.0.1 --port 8000

verify: test
	$(PY) -c "import unknownid, unknownid.api.app, unknownid.service; print('imports ok')"
	$(PY) -c "from unknownid.config import load_config; load_config('selection'); load_config('acquisition'); print('configs ok')"

# Uses only the first three precursor-ambiguous development cases from the
# committed MultiMS2 records. Does not require a raw-data download or preparation.
interactive-baseline:
	$(PY) scripts/run_interactive_baseline.py

peak-exclusion-spike:
	$(PY) scripts/run_peak_exclusion_spike.py
