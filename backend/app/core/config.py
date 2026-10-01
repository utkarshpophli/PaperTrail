"""Application settings.

Required settings (``database_url``, ``jwt_secret_key``) have no defaults on
purpose — Pydantic Settings raises a ``ValidationError`` at import time if
they are missing from the environment or ``.env`` file, so the app fails to
start rather than running with an insecure implicit default (SECURITY.md:
"no bundled keys, no defaults").
"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    cors_allow_origins: list[str] = ["http://localhost:3000"]
    # Single-user, run-it-on-your-own-machine mode: no login, every request acts as
    # one fixed local user (app.auth.dependencies). Only safe while the API is
    # reachable from this machine alone -- keep it bound to loopback.
    local_mode: bool = True
    # Read timeout for a single provider generation call. A full-document
    # extraction on a large model routinely exceeds a minute before the first
    # byte, so this is generous by design (connect/write stay short). HTTPX
    # applies this to the interval between response bytes, not the lifetime
    # of the whole request -- a gateway that keeps a connection alive with
    # intermittent traffic can reset this timeout indefinitely without ever
    # producing a usable completion (confirmed live against NVIDIA NIM: a
    # 33+ minute hang with no success, error, or retry). See
    # ``provider_operation_timeout_seconds`` for the real circuit breaker.
    provider_read_timeout_seconds: float = 600.0
    # Hard upper bound on one whole public provider operation (generate,
    # stream, or embed), including HTTP retries and the one structured-output
    # repair attempt. Unlike the read timeout above, this bounds total
    # elapsed time even if the upstream sends keepalive bytes without ever
    # completing a response -- see docs/NIM_HANG_FIX.md. 30 min because a
    # live NIM reasoning-model pass over a ~150k-char paper took ~16.5 min
    # (~5 min queue before the first token, then minutes of reasoning).
    provider_operation_timeout_seconds: float = 1800.0

    @model_validator(mode="after")
    def _operation_timeout_exceeds_read_timeout(self) -> "Settings":
        if self.provider_operation_timeout_seconds <= self.provider_read_timeout_seconds:
            raise ValueError(
                "provider_operation_timeout_seconds must be greater than provider_read_timeout_seconds "
                f"({self.provider_operation_timeout_seconds} <= {self.provider_read_timeout_seconds})"
            )
        return self

    # Per-paper source PDFs + extracted figures live under
    # {storage_dir}/{paper_id}/ — relative default is fine for dev, the
    # directory is gitignored.
    storage_dir: str = "./storage"
    max_upload_size_bytes: int = 50 * 1024 * 1024
    arxiv_api_timeout_seconds: float = 15.0
    github_api_timeout_seconds: float = 15.0
    openalex_api_timeout_seconds: float = 15.0
    # Polite-pool contact email for OpenAlex's `mailto` param -- optional,
    # never required (OpenAlex works fully unauthenticated); only improves
    # rate-limit treatment when an operator sets it (ARCHITECTURE.md's Phase
    # 7 slice 2 decisions).
    openalex_contact_email: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
