# Relay SDK tests (REL-41): the same pinned Python base image as the api; no ports, no secrets.
FROM python:3.12.15-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /sdk
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[dev]"
COPY . .
RUN useradd --create-home relay
USER relay
CMD ["sh", "-c", "ruff check . && ruff format --check . && mypy src && pytest"]
