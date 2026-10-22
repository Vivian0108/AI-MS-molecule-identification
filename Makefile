SHELL := /bin/bash
PY ?= .venv/bin/python
PIP ?= .venv/bin/pip
export PYTHONPATH := src
export PYTHONHASHSEED := 0

.PHONY: help setup fetch-data prepare audit demo-cases calibrate eval test app api verify spectrapilot-eval v3-audit v3-failures v3-train v3-eval v3-demo v3-test v3

help:
	@echo "UnknownID targets"
	@echo "  make setup       create .venv and install the package + dev tools"
	@echo "  make fetch-data  sparse-clone the pinned MassBank Athens_Univ snapshot"
	@echo "  make prepare     curate, audit, split and fit the error model"
	@echo "  make audit       show the data-audit go/no-go gate"
	@echo "  make demo-cases  write anonymised demo case IDs"
	@echo "  make calibrate   select the acquisition method on the dev split"
	@echo "  make eval        run frozen test-split baselines and bootstrap intervals"
	@echo "  make spectrapilot-eval  run the SpectraPilot v2 subset benchmark (ambiguous test cohort)"
	@echo ""
	@echo "SpectraPilot v3 (see SpectraPilot_v3_Code_Audit_and_Implementation_Handoff.md)"
	@echo "  make v3-train    fit the risk calibrator + ranker artefact, validate fragments"
	@echo "  make v3-audit    reproduce v2 and write coverage_regression_cases.csv"
	@echo "  make v3-failures failure atlas + oracle-ceiling diagnosis"
	@echo "  make v3-eval     M0-M7 matrix, ablations, paired stats, open world, plots"
	@echo "  make v3-demo     six-screen precommit dossier"
	@echo "  make v3-test     v3 regression tests"
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

spectrapilot-eval:
	PYTHONPATH=src $(PY) scripts/run_spectrapilot_eval.py --cohort ambiguous --resamples 2000
	PYTHONPATH=src $(PY) scripts/run_spectrapilot_eval.py --cohort all --limit 80 --resamples 2000
	PYTHONPATH=src $(PY) scripts/run_spectrapilot_eval.py --split dev,test --cohort all --limit 200 --resamples 2000

test:
	$(PY) -m pytest -q

app:
	$(PY) -m streamlit run app/streamlit_app.py

api:
	$(PY) -m uvicorn unknownid.api.app:app --host 127.0.0.1 --port 8000

verify: test
	$(PY) -c "import unknownid, unknownid.api.app, unknownid.service; print('imports ok')"
	$(PY) -c "from unknownid.config import load_config; load_config('selection'); load_config('acquisition'); print('configs ok')"

# ---------------------------------------------------------------------------
# SpectraPilot v3 (additive; the targets above are unchanged)
# ---------------------------------------------------------------------------
v3-train:
	PYTHONPATH=src $(PY) scripts/train_spectrapilot_v3.py

v3-audit:
	PYTHONPATH=src $(PY) scripts/audit_spectrapilot_v3.py

v3-failures:
	PYTHONPATH=src $(PY) scripts/analyze_failures_v3.py

v3-eval:
	PYTHONPATH=src $(PY) scripts/eval_spectrapilot_v3.py

v3-demo:
	PYTHONPATH=src $(PY) scripts/run_demo_case_v3.py

v3-test:
	$(PY) -m pytest -q tests/test_spectrapilot_v3.py

# Full v3 pipeline. Ordered: train -> audit -> failures -> eval -> demo.
v3: v3-train v3-audit v3-failures v3-eval v3-demo
	@echo "v3 pipeline complete; see reports/v3/"
