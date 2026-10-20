# AlgaeCast-7 Makefile — 타깃 표는 docs/08_PIPELINE_SPEC.md 2절.
# 아직 구현되지 않은 타깃은 TODO 와 예정 명령을 출력한다 (담당 태스크 번호 표기).
.DEFAULT_GOAL := help

ifeq ($(OS),Windows_NT)
  # PowerShell 에서 make 를 띄우면 sh 가 없어 cmd.exe 로 떨어진다. 어느 터미널에서든 동일하게 동작하도록 cmd.exe 로 고정.
  # => 레시피에 sh 전용 문법($$(...), /dev/null, 작은따옴표 인용) 금지. 복잡한 로직은 python -c / scripts/ 로.
  SHELL    := cmd.exe
  SYS_PY   ?= py -3.11
  VENV_BIN := .venv\Scripts
  PY       := $(VENV_BIN)\python.exe
else
  SYS_PY   ?= python3.11
  VENV_BIN := .venv/bin
  PY       := $(VENV_BIN)/python
endif

START ?= 2012-01-01
END   ?= today

.PHONY: help venv setup lock test lint format collect align features eda tune train evaluate predict upload submission reproduce clean

help:
	@echo AlgaeCast-7 make targets
	@echo   setup       create .venv, install requirements, editable install, pre-commit install
	@echo   test        pytest -q  incl. no-leakage tests
	@echo   lint        ruff + black --check
	@echo   format      ruff --fix + black
	@echo   lock        freeze installed versions to requirements.lock.txt
	@echo   collect     [T1] fetch public data        align      [T3] calendar join + imputation
	@echo   features    [T3] build features           eda        [T2] run notebooks
	@echo   tune        [T4] optuna                   train      [T4] fit models
	@echo   evaluate    [T5] evaluation report        predict    [T8] forecast as-of today
	@echo   upload      [T6] supabase upload          submission [T9] submission.csv
	@echo   reproduce   [T9] features+train+submission then diff

venv: $(PY)

$(PY):
	$(SYS_PY) -m venv .venv
	$(PY) -m pip install --upgrade pip

setup: $(PY)
	$(PY) -m pip install -r requirements.txt
	$(PY) scripts/install_hooks.py

lock:
	$(PY) scripts/freeze_lock.py

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check src tests scripts
	$(PY) -m black --check src tests scripts

format:
	$(PY) -m black src tests scripts
	$(PY) -m ruff check --fix src tests scripts

collect:
	$(PY) -m algaecast.collect.run --start $(START) --end $(END)

align:
	$(PY) -m algaecast.align.run --strategy S1,S2,S3

features:
	$(PY) -m algaecast.features.run --strategy S1,S2,S3
	$(PY) scripts/leakage_audit.py --strategy S1 --sample 300

eda:
	$(PY) -m jupytext --to notebook --execute notebooks/02_stats.py

tune:
	@echo TODO [T4-b] $(PY) -m algaecast.models.tune --model lgbm --trials 300

train:
	@echo TODO [T4-b] $(PY) -m algaecast.models.train --config config/model.yaml

evaluate:
	@echo TODO [T5] $(PY) -m algaecast.eval.report

predict:
	@echo TODO [T8] $(PY) -m algaecast.models.predict --as-of $(END)

upload:
	@echo TODO [T6] $(PY) -m algaecast.db.upload

submission:
	@echo TODO [T9-b] $(PY) -m algaecast.models.predict --sample data/raw/competition/sample_submission.csv

reproduce: features train submission
	@echo TODO [T9-b] diff submission/submission.csv submission/submission_final.csv

clean:
	$(PY) -c "import shutil,pathlib; [shutil.rmtree(p, ignore_errors=True) for p in map(pathlib.Path, ['.pytest_cache', '.ruff_cache', 'build', 'src/algaecast.egg-info'])]"
