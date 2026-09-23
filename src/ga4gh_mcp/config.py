"""Configuration for the GA4GH MCP server.

All settings are read from environment variables with the prefix ``GA4GH_MCP_``.
Nothing here holds a secret value; auth secrets are referenced by env-var *name*
via the auth config file (see ``docs/auth.md``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Transport = Literal["stdio", "streamable-http"]
Surface = Literal["agentic", "legacy"]
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GA4GH_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Registry ---
    registry_base_url: str = "https://implementation-registry.ga4gh.org/api"
    # Comma-separated GA4GH Service Registry `/services` URLs to federate alongside the public
    # Implementation Registry (e.g. a ga4gh-aws-opendata deployment). Their services appear in
    # list_services / get_service / health / DRS / Data Connect exactly like registered ones.
    extra_registries: str = ""

    def extra_registry_urls(self) -> list[str]:
        return [u.strip() for u in self.extra_registries.split(",") if u.strip()]

    # --- Tool surface ---
    # agentic: the Agentic Harness tools (agentic_server.py). legacy: the registry, DRS, Data
    # Connect, TRS, TES and Beacon tools (server.py).
    surface: Surface = "agentic"

    # --- Transport ---
    transport: Transport = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    http_path: str = "/mcp"
    stateless_http: bool = True  # friendly to serverless (Vertex/Bedrock/Cloud Run)

    # --- HTTP client behaviour ---
    connect_timeout: float = 5.0
    read_timeout: float = 15.0
    max_retries: int = 2  # retries on transient failures (429/5xx/connect)
    retry_backoff: float = 0.5  # base seconds; exponential
    verify_tls: bool = True
    user_agent: str = "ga4gh-agentic-harness-mcp/0.1 (+https://github.com/ga4gh/ga4gh-agentic-harness-mcp)"
    max_response_bytes: int = 2_000_000  # cap on any single upstream body we buffer
    # Exceptions for explicit local development. Disabled by default. allow_private_hosts also
    # governs the registry-oriented client in http_client.py (loopback/private/metadata targets).
    agentic_allow_http: bool = False
    agentic_allow_private_hosts: bool = False
    agentic_allowed_hosts: str = ""
    agentic_write_scopes: str = ""

    def agentic_allowed_host_list(self) -> list[str]:
        return [h.strip().lower() for h in self.agentic_allowed_hosts.split(",") if h.strip()]

    def agentic_write_scope_list(self) -> list[str]:
        return [s.strip() for s in self.agentic_write_scopes.split(",") if s.strip()]

    # call_service_endpoint sends only GET/HEAD unless this is set. The registry-oriented tools
    # have no per-call confirmation, so mutating methods need an operator decision up front.
    allow_write_methods: bool = False

    # --- Caching ---
    registry_cache_ttl: float = 300.0  # seconds; registry lists change slowly
    liveness_cache_ttl: float = 30.0  # seconds; per-service probe results

    # --- Auth ---
    auth_config: str | None = None  # path to JSON auth config (see docs/auth.md)
    bearer_token: str | None = Field(default=None, repr=False)  # global static bearer
    # Comma-separated hosts the global bearer_token may be sent to. Empty => never auto-send.
    bearer_hosts: str = ""

    def bearer_host_set(self) -> set[str]:
        return {h.strip().lower() for h in self.bearer_hosts.split(",") if h.strip()}


def load_settings(**overrides) -> Settings:
    return Settings(**overrides)
