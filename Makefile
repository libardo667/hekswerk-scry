.PHONY: check test lint typecheck demo lean-setup lean-test lean-demo

PYTHON ?= python3
export PYTHONPATH := src

DEV_TOOLS_HINT = Install the development tools with: $(PYTHON) -m pip install -e '.[dev]'

check: lint typecheck test

test:
	$(PYTHON) -m unittest discover -s tests -t .

lint:
	@command -v ruff >/dev/null 2>&1 || { echo "ruff is not installed. $(DEV_TOOLS_HINT)"; exit 1; }
	ruff check src tests lean_tests

typecheck:
	@command -v mypy >/dev/null 2>&1 || { echo "mypy is not installed. $(DEV_TOOLS_HINT)"; exit 1; }
	mypy --strict src tests lean_tests

demo:
	$(PYTHON) -m hekswerk_scry demo

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
