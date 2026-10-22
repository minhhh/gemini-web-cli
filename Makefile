.PHONY: sync lint test doctor

sync:
	uv sync --extra dev

lint:
	uv run ruff check .

test:
	uv run pytest

doctor:
	uv run gemini-web-cli doctor --pretty
