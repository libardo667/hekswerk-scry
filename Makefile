.PHONY: check test lint typecheck demo serve mutation-check lean-setup lean-test lean-demo ai-test openai-setup openai-test

# Use the project's virtual environment when there is one (see README), else python3.
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
export PYTHONPATH := src

DEV_TOOLS_HINT = Install the development tools with: $(PYTHON) -m pip install -e '.[dev]'

check: lint typecheck test

test:
	$(PYTHON) -m unittest discover -s tests -t .

lint:
	@$(PYTHON) -m ruff --version >/dev/null 2>&1 || { echo "ruff is not installed. $(DEV_TOOLS_HINT)"; exit 1; }
	$(PYTHON) -m ruff check src tests lean_tests ai_tests openai_tests scripts

typecheck:
	@$(PYTHON) -m mypy --version >/dev/null 2>&1 || { echo "mypy is not installed. $(DEV_TOOLS_HINT)"; exit 1; }
	$(PYTHON) -m mypy --strict src tests lean_tests ai_tests openai_tests scripts

demo:
	$(PYTHON) -m hekswerk_scry demo

serve:
	$(PYTHON) -m hekswerk_scry serve

mutation-check:
	$(PYTHON) scripts/mutation_check.py

# --- Lean (see "Setting up Lean" in README.md) ---------------------------------------

LAKE ?= $(shell command -v lake 2>/dev/null || echo $(HOME)/.elan/bin/lake)
LEAN_HINT = Lean is not installed. Install elan from https://github.com/leanprover/elan, then run make lean-setup.

lean-setup:
	@test -x "$(LAKE)" || { echo "$(LEAN_HINT)"; exit 1; }
	cd lean && "$(LAKE)" exe cache get
	cd lean && "$(LAKE)" build scry-export
	cd lean-exporters/v4.34.1 && "$(LAKE)" build scry-export

lean-test:
	@test -x "$(LAKE)" || { echo "$(LEAN_HINT)"; exit 1; }
	cd lean && "$(LAKE)" build scry-export
	$(PYTHON) -m unittest discover -s lean_tests -t . -v

lean-demo:
	$(PYTHON) -m hekswerk_scry lean-demo

# --- AI helper (needs OPENROUTER_API_KEY in .env, and Lean) ----------------------------

ai-test:
	@test -x "$(LAKE)" || { echo "$(LEAN_HINT)"; exit 1; }
	@echo "This calls the real model through OpenRouter and costs about \$$0.20."
	$(PYTHON) -m unittest discover -s ai_tests -t . -v


# --- OpenAI's mathematics repository (Lean v4.34.1; about 10 GB with Mathlib) ---------

openai-setup:
	@test -x "$(LAKE)" || { echo "$(LEAN_HINT)"; exit 1; }
	$(PYTHON) -m hekswerk_scry fetch-openai-math
	cd lean-exporters/v4.34.1 && "$(LAKE)" build scry-export
	cd "$$($(PYTHON) -c 'from hekswerk_scry.lean.openai_math import lean_project; print(lean_project())')" && "$(LAKE)" exe cache get

openai-test:
	@test -x "$(LAKE)" || { echo "$(LEAN_HINT)"; exit 1; }
	cd lean-exporters/v4.34.1 && "$(LAKE)" build scry-export
	$(PYTHON) -m unittest discover -s openai_tests -t . -v
