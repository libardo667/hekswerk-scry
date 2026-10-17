.PHONY: check test lint typecheck demo mutation-check lean-setup lean-test lean-demo

# Use the project's virtual environment when there is one (see README), else python3.
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
export PYTHONPATH := src

DEV_TOOLS_HINT = Install the development tools with: $(PYTHON) -m pip install -e '.[dev]'

check: lint typecheck test

test:
	$(PYTHON) -m unittest discover -s tests -t .

lint:
	@$(PYTHON) -m ruff --version >/dev/null 2>&1 || { echo "ruff is not installed. $(DEV_TOOLS_HINT)"; exit 1; }
	$(PYTHON) -m ruff check src tests lean_tests scripts

typecheck:
	@$(PYTHON) -m mypy --version >/dev/null 2>&1 || { echo "mypy is not installed. $(DEV_TOOLS_HINT)"; exit 1; }
	$(PYTHON) -m mypy --strict src tests lean_tests scripts

demo:
	$(PYTHON) -m hekswerk_scry demo

mutation-check:
	$(PYTHON) scripts/mutation_check.py

# --- Lean (see "Setting up Lean" in README.md) ---------------------------------------

LAKE ?= $(shell command -v lake 2>/dev/null || echo $(HOME)/.elan/bin/lake)
LEAN_HINT = Lean is not installed. Install elan from https://github.com/leanprover/elan, then run make lean-setup.

lean-setup:
	@test -x "$(LAKE)" || { echo "$(LEAN_HINT)"; exit 1; }
	cd lean && "$(LAKE)" exe cache get
	cd lean && "$(LAKE)" build scry-export

lean-test:
	@test -x "$(LAKE)" || { echo "$(LEAN_HINT)"; exit 1; }
	$(PYTHON) -m unittest discover -s lean_tests -t . -v

lean-demo:
	$(PYTHON) -m hekswerk_scry lean-demo
