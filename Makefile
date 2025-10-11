.PHONY: help install install-dev test test-cov lint format clean build upload docs docs-multiversion

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

lint:  ## Run linting
	flake8 vayuayan/
	mypy vayuayan/

format:  ## Format code
	black vayuayan/

clean:  ## Clean build artifacts
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf htmlcov/
	find . -type d -name __pycache__ -delete
	find . -name "*.pyc" -delete

build:  ## Build package
	python -m build

upload:  ## Upload to PyPI (requires twine)
	python -m twine upload dist/*

upload-test:  ## Upload to Test PyPI
	python -m twine upload --repository testpypi dist/*

docs:  ## Build documentation
	cd docs && make html

docs-multiversion:  ## Build documentation for all versions
	cd docs && make multiversion

docs-serve:  ## Serve documentation locally
	cd docs/_build/html && python -m http.server 8000

example-basic:  ## Run basic usage example
	python examples/basic_usage.py

example-batch:  ## Run batch processing example
	python examples/batch_processing.py

cli-help:  ## Show CLI help
	python -m vayuayan --help

setup-dev:  ## Set up development environment
	pip install -e ".[dev]"
	pre-commit install
