.PHONY: check test lint typecheck demo

PYTHON ?= python3
export PYTHONPATH := src

DEV_TOOLS_HINT = Install the development tools with: $(PYTHON) -m pip install -e '.[dev]'

check: lint typecheck test

test:
	$(PYTHON) -m unittest discover -s tests -t .

lint:
	@command -v ruff >/dev/null 2>&1 || { echo "ruff is not installed. $(DEV_TOOLS_HINT)"; exit 1; }
	ruff check src tests

typecheck:
	@command -v mypy >/dev/null 2>&1 || { echo "mypy is not installed. $(DEV_TOOLS_HINT)"; exit 1; }
	mypy --strict src tests

demo:
	$(PYTHON) -m hekswerk_scry demo
