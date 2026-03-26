.PHONY: test lint typecheck install install-all clean

test:  ## Run all tests
	python -m pytest tests/ -q

test-verbose:  ## Run tests with verbose output
	python -m pytest tests/ -v

lint:  ## Run ruff linter
	ruff check src/ tests/

typecheck:  ## Run mypy type checking
	mypy --strict src/open_web_retrieval/

install:  ## Install in editable mode (base only)
	pip install -e .

install-extract:  ## Install with trafilatura for extraction
	pip install -e ".[extract]"

install-all:  ## Install with all optional deps
	pip install -e ".[all]"

clean:  ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info .pytest_cache __pycache__
	find . -type d -name __pycache__ -exec rm -rf {} +

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
