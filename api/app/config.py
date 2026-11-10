"""Settings read from the environment (.env via docker compose); see docs/architecture/containers.md."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    relay_api_key: str
    database_url: str
    redis_url: str
    # The api appends one JSON line per request here (REL-52); the api-logs volume is mounted at /var/log/relay.
    request_log_path: str = "/var/log/relay/api-requests.jsonl"
    # Idempotency keys (data-model.md): kept for the TTL; a first request holds its key for the lease.
    idempotency_ttl_hours: int = 24
    idempotency_lease_seconds: int = 30
    # Local model (ADR-0010): Ollama on the host, reached from containers through host.docker.internal.
    ollama_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "granite3.3:2b"
    explain_timeout_seconds: float = 5.0
    # REL-30 results file, mounted read-only by compose (REL-37); absent means the baseline is unavailable.
    baseline_results_path: str = "/app/baseline/results.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
