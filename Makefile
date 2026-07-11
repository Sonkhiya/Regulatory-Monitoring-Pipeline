.PHONY: install lint format test test-cov hooks clean

install:
	pip install -e ".[dev]"

lint:
	ruff check src tests
	black --check src tests
	mypy

format:
	ruff check --fix src tests
	black src tests

test:
	pytest -m "not integration"

test-cov:
	pytest -m "not integration" --cov=regmon --cov-report=term-missing --cov-report=html

hooks:
	pre-commit install

clean:
	rm -rf build dist .mypy_cache .pytest_cache .ruff_cache .coverage htmlcov
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	find . -type d -name '*.egg-info' -prune -exec rm -rf {} +
