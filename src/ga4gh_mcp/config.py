"""Configuration for the GA4GH MCP server.

All settings are read from environment variables with the prefix ``GA4GH_MCP_``.
Nothing here holds a secret value; auth secrets are referenced by env-var *name*
via the auth config file (see ``docs/auth.md``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Transport = Literal["stdio", "streamable-http"]
RegistryApi = Literal["implementation-registry", "service-registry"]


class RegistrySource(BaseModel):
    """One registry this server discovers services from.

    ``api`` says which API the URL speaks; it is declared, never probed. Every entry feeds
    service listing, search and lookup through ``{url}/services``. Only Implementation Registry
    entries also back standards, organisations and deployments, which Service Registries lack.
    """

    url: str
    api: RegistryApi


GA4GH_IMPLEMENTATION_REGISTRY = RegistrySource(
    url="https://implementation-registry.ga4gh.org/api", api="implementation-registry"
)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GA4GH_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Registry ---
    # Every registry that feeds discovery. The default is the GA4GH Implementation Registry;
    # setting the list replaces it, so add it back explicitly to keep it. Environment:
    # GA4GH_MCP_REGISTRIES='[{"url": "http://127.0.0.1:8899/ga4gh/registry",
    #                         "api": "service-registry"}]'
    registries: list[RegistrySource] = Field(
        default_factory=lambda: [GA4GH_IMPLEMENTATION_REGISTRY.model_copy()]
    )

    @field_validator("registries")
    @classmethod
    def _at_least_one_registry(cls, value: list[RegistrySource]) -> list[RegistrySource]:
        if not value:
            raise ValueError("at least one registry is required")
        return value

    def registry_urls(self, api: RegistryApi) -> list[str]:
        return [r.url.rstrip("/") for r in self.registries if r.api == api]

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
