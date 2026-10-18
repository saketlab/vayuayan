.PHONY: help install install-dev test test-cov lint format security clean build upload upload-test docs docs-multiversion docs-serve cli-help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install package
	pip install -e .

install-dev:  ## Install package with development dependencies
	pip install -e ".[dev]"

test:  ## Run tests
	python -m pytest tests/ -v

test-cov:  ## Run tests with coverage
	python -m pytest tests/ --cov=vayuayan --cov-report=html --cov-report=term

lint:  ## Run the CI lint checks (ruff, ruff format, mypy)
	ruff check .
	ruff format --check --diff .
	mypy vayuayan/

format:  ## Format code
	ruff format .

security:  ## Run bandit as CI does (requires bandit)
	bandit -r vayuayan/ --severity-level medium

clean:  ## Clean build artifacts
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf .ruff_cache/
	rm -rf htmlcov/
	rm -rf docs/_build/
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

build: clean  ## Build package and check it with twine
	python -m build
	python -m twine check --strict dist/*

upload: build  ## Upload to PyPI (releases normally go through a version tag)
	python -m twine upload dist/*

upload-test: build  ## Upload to Test PyPI
	python -m twine upload --repository testpypi dist/*

docs:  ## Build documentation
	sphinx-build -b html docs docs/_build/html

docs-multiversion:  ## Build documentation for all versions
	cd docs && make multiversion

docs-serve:  ## Serve documentation locally
	cd docs/_build/html && python -m http.server 8000

cli-help:  ## Show CLI help
	python -m vayuayan --help
