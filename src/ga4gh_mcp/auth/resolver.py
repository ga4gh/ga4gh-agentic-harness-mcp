"""Selects the right auth provider per service and interprets 401 challenges."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import httpx

from ..config import Settings
from ..http_client import Ga4ghHttpClient
from ..models import AuthHint
from .base import AuthProvider, AuthSpec
from .providers import NoAuth, StaticBearerAuth, build_provider

_TOKEN_STORE_DIR = os.path.expanduser("~/.ga4gh-mcp/tokens")


_LOOPBACK = {"localhost", "127.0.0.1", "::1"}

Origin = tuple[str, str, int | None]


def _origin(url: str | None) -> Origin | None:
    """(scheme, host, port) parsed with httpx, i.e. exactly where a request will be sent."""
    if not url:
        return None
    try:
        u = httpx.URL(url)
    except Exception:  # noqa: BLE001
        return None
    host = u.host.lower().rstrip(".")
    if not host:
        return None
    return u.scheme, host, u.port or {"https": 443, "http": 80}.get(u.scheme)


def _may_carry_credentials(origin: Origin) -> bool:
    """Credentials travel only over TLS (plain http is tolerated for loopback dev servers)."""
    scheme, host, _ = origin
    return scheme == "https" or (scheme == "http" and host in _LOOPBACK)


# WWW-Authenticate token = token68 or key="quoted" / key=token pairs.
_PARAM_RE = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|([^\s,]+))')


def parse_www_authenticate(header: str | None) -> AuthHint:
    """Parse a ``WWW-Authenticate`` header into an actionable :class:`AuthHint`."""
    if not header:
        return AuthHint(required=False)
    scheme = header.split(" ", 1)[0].strip() or None
    params: dict[str, str] = {}
    for m in _PARAM_RE.finditer(header):
        params[m.group(1).lower()] = m.group(2) if m.group(2) is not None else m.group(3)
    hint = AuthHint(
        required=True,
        scheme=scheme,
        realm=params.get("realm"),
        scope=params.get("scope"),
        authorization_uri=params.get("authorization_uri")
        or params.get("as_uri")
        or params.get("authorization_endpoint"),
        www_authenticate=header,
    )
    if scheme and scheme.lower() == "bearer":
        hint.guidance = (
            "Service requires an OAuth2/OIDC bearer token. Configure a provider in the auth "
            "config (kind=bearer with token_env, or kind=oauth2_client_credentials / "
            "oauth2_device_code). See docs/auth.md."
        )
    elif scheme:
        hint.guidance = f"Service requires '{scheme}' authentication. See docs/auth.md."
    return hint


class AuthResolver:
    """Maps a registry service entry to an :class:`AuthProvider`.

    Resolution order: explicit config match (by implementationId, then host) → global
    static bearer (only for allow-listed hosts) → NoAuth. Providers are cached per
    (implementationId, origin) so OAuth token caches survive across calls, and a decision made
    for one origin is never reused for another.

    Credentials are bound to where they were configured, not to what a registry entry claims:
    nothing is attached over plain http (except loopback); a spec's ``hosts`` list, when set,
    restricts it to those hosts; and an entry from a federated registry (which mints its own
    ids) cannot match a spec by implementationId unless that spec pins ``hosts``.
    """

    def __init__(self, settings: Settings, http: Ga4ghHttpClient) -> None:
        self._settings = settings
        self._http = http
        self._specs: list[AuthSpec] = self._load_specs(settings.auth_config)
        self._cache: dict[str, AuthProvider] = {}

    @staticmethod
    def _load_specs(path: str | None) -> list[AuthSpec]:
        if not path:
            return []
        p = Path(path)
        if not p.exists():
            return []
        data = json.loads(p.read_text())
        raw = data.get("services", data) if isinstance(data, dict) else data
        specs: list[AuthSpec] = []
        if isinstance(raw, dict):  # {match: spec}
            for match, spec in raw.items():
                s = AuthSpec.from_dict(spec)
                s.match = s.match or match
                specs.append(s)
        elif isinstance(raw, list):
            specs = [AuthSpec.from_dict(s) for s in raw]
        return specs

    def _find_spec(self, impl_id: str | None, host: str, *, federated: bool) -> AuthSpec | None:
        def pinned_ok(s: AuthSpec) -> bool:
            return not s.hosts or host in {h.strip().lower() for h in s.hosts}

        for s in self._specs:
            if s.match and impl_id and s.match == impl_id and pinned_ok(s):
                if federated and not s.hosts:
                    continue
                return s
        for s in self._specs:
            if s.match and s.match.lower() == host and pinned_ok(s):
                return s
        return None

    def resolve(self, service: dict[str, Any]) -> AuthProvider:
        impl_id = service.get("implementationId")
        origin = _origin(service.get("serviceInfoUrl") or service.get("url"))
        key = (impl_id, origin)
        if key in self._cache:
            return self._cache[key]

        secure = origin is not None and _may_carry_credentials(origin)
        host = origin[1] if origin else ""
        federated = str(service.get("source") or "").startswith("federated:")
        spec = self._find_spec(impl_id, host, federated=federated) if secure else None
        if not secure:
            provider = NoAuth()
        elif spec is not None:
            provider = build_provider(spec, self._http, token_store_dir=_TOKEN_STORE_DIR)
        elif self._settings.bearer_token and host in self._settings.bearer_host_set():
            provider = StaticBearerAuth(self._settings.bearer_token)
        else:
            provider = NoAuth()
        self._cache[key] = provider
        return provider

    def describe(self) -> dict[str, Any]:
        return {
            "configured_specs": [
                {"match": s.match, "kind": s.kind, "hosts": s.hosts} for s in self._specs
            ],
            "global_bearer_configured": bool(self._settings.bearer_token),
            "global_bearer_hosts": sorted(self._settings.bearer_host_set()),
            "auth_config_path": self._settings.auth_config,
            "token_store_dir": _TOKEN_STORE_DIR,
        }
