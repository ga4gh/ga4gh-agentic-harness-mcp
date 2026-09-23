"""Credentials are bound to the origin they were configured for, not to registry-supplied ids.

Registry entries (and federated Service Registry entries) are remote data. The URL an entry
names, and the implementationId it claims, must not be able to steer a configured credential
to another host or over plaintext.
"""

from __future__ import annotations

import json

import httpx
import respx

from ga4gh_mcp import tools
from ga4gh_mcp.auth.resolver import AuthResolver
from ga4gh_mcp.config import load_settings
from ga4gh_mcp.context import ServerContext
from ga4gh_mcp.http_client import Ga4ghHttpClient


def _resolver(**kw):
    settings = load_settings(**kw)
    http = Ga4ghHttpClient(settings)
    return AuthResolver(settings, http), http


def _cfg(tmp_path, services):
    p = tmp_path / "auth.json"
    p.write_text(json.dumps({"services": services}))
    return str(p)


async def test_global_bearer_allowlist_not_bypassed_by_cached_implementation_id():
    resolver, http = _resolver(bearer_token="glob", bearer_hosts="allowed.test")
    first = resolver.resolve({"implementationId": "svc", "serviceInfoUrl": "https://allowed.test/x"})
    assert await first.headers_for("https://allowed.test/x") == {"Authorization": "Bearer glob"}
    # Same implementationId, entry now points elsewhere (edited entry, second registry, ...).
    moved = resolver.resolve({"implementationId": "svc", "serviceInfoUrl": "https://other.test/x"})
    assert await moved.headers_for("https://other.test/x") == {}
    await http.aclose()


async def test_global_bearer_not_sent_over_plain_http():
    resolver, http = _resolver(bearer_token="glob", bearer_hosts="allowed.test")
    p = resolver.resolve({"implementationId": "svc", "serviceInfoUrl": "http://allowed.test/x"})
    assert await p.headers_for("http://allowed.test/x") == {}
    await http.aclose()


async def test_host_matched_spec_not_sent_over_plain_http(tmp_path, monkeypatch):
    monkeypatch.setenv("TOK", "s3cret")
    resolver, http = _resolver(auth_config=_cfg(tmp_path, {
        "drs.test": {"kind": "bearer", "token_env": "TOK"}}))
    assert await resolver.resolve({"serviceInfoUrl": "https://drs.test/x"}).headers_for(
        "https://drs.test/x") == {"Authorization": "Bearer s3cret"}
    assert await resolver.resolve({"serviceInfoUrl": "http://drs.test/x"}).headers_for(
        "http://drs.test/x") == {}
    await http.aclose()


async def test_loopback_http_allowed_with_local_development_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("TOK", "s3cret")
    resolver, http = _resolver(agentic_allow_http=True, auth_config=_cfg(tmp_path, {
        "localhost": {"kind": "bearer", "token_env": "TOK"}}))
    p = resolver.resolve({"serviceInfoUrl": "http://localhost:8080/service-info"})
    assert await p.headers_for("http://localhost:8080/service-info") == {"Authorization": "Bearer s3cret"}
    await http.aclose()


async def test_implementation_id_spec_honours_hosts_pin(tmp_path, monkeypatch):
    monkeypatch.setenv("TOK", "s3cret")
    resolver, http = _resolver(auth_config=_cfg(tmp_path, {
        "org.test.drs": {"kind": "bearer", "token_env": "TOK", "host": "drs.test"}}))
    good = resolver.resolve({"implementationId": "org.test.drs",
                             "serviceInfoUrl": "https://drs.test/ga4gh/drs/v1/service-info"})
    bad = resolver.resolve({"implementationId": "org.test.drs",
                            "serviceInfoUrl": "https://attacker.test/ga4gh/drs/v1/service-info"})
    assert await good.headers_for("https://drs.test/ga4gh/drs/v1/service-info") \
        == {"Authorization": "Bearer s3cret"}
    assert await bad.headers_for("https://attacker.test/ga4gh/drs/v1/service-info") == {}
    await http.aclose()


FED = "https://fed.test/ga4gh/registry/services"


@respx.mock
async def test_federated_entry_cannot_claim_a_configured_implementation_id(tmp_path, monkeypatch):
    """A federated registry mints its own ids. With the core registry down, an entry claiming
    the configured id 'org.test.drs' must not receive that service's token."""
    monkeypatch.setenv("TOK", "s3cret")
    settings = load_settings(
        registry_base_url="https://registry.test/api", extra_registries=FED,
        max_retries=0, retry_backoff=0.0,
        auth_config=_cfg(tmp_path, {"org.test.drs": {"kind": "bearer", "token_env": "TOK"}}))
    respx.get("https://registry.test/api/services").mock(return_value=httpx.Response(503))
    respx.get(FED).mock(return_value=httpx.Response(200, json=[{
        "id": "org.test.drs", "name": "lookalike",
        "type": {"group": "org.ga4gh", "artifact": "drs", "version": "1.4.0"},
        "url": "https://attacker.test/ga4gh/drs/v1"}]))
    sink = respx.get("https://attacker.test/ga4gh/drs/v1/objects/o1").mock(
        return_value=httpx.Response(200, json={"id": "o1"}))
    ctx = ServerContext.create(settings)
    try:
        await tools.drs_get_object(ctx, service_id="org.test.drs", object_id="o1")
    finally:
        await ctx.aclose()
    assert sink.called
    assert "authorization" not in sink.calls[0].request.headers
