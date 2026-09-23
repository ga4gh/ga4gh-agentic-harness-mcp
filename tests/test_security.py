"""Regression tests for credential scoping and outbound-destination safety.

Each test here reproduces a confused-deputy or SSRF path in the registry-oriented tool
surface (``server.py`` / ``tools.py`` / ``http_client.py``): a URL that comes from a
registry entry, an upstream response, or the model must not receive credentials issued for a
different origin, and must not reach loopback, private, or cloud-metadata addresses.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from ga4gh_mcp import http_client as http_mod
from ga4gh_mcp import tools
from ga4gh_mcp.auth.resolver import AuthResolver
from ga4gh_mcp.config import load_settings
from ga4gh_mcp.context import ServerContext
from ga4gh_mcp.errors import Liveness
from ga4gh_mcp.http_client import Ga4ghHttpClient


def _client(**overrides):
    return Ga4ghHttpClient(load_settings(max_retries=0, retry_backoff=0.0, **overrides))


# ------------------------------------------------------------------ redirects + credentials

@respx.mock
async def test_custom_auth_header_not_forwarded_on_cross_origin_redirect():
    # httpx strips only `Authorization` on a cross-origin redirect. An api_key provider's
    # custom header (docs/auth.md shows X-API-Key) used to be re-sent to the redirect target.
    respx.get("https://svc.test/objects/1").mock(return_value=httpx.Response(
        302, headers={"Location": "https://attacker.test/collect"}))
    sink = respx.get("https://attacker.test/collect").mock(
        return_value=httpx.Response(200, json={}))
    c = _client()
    res = await c.request("GET", "https://svc.test/objects/1", headers={"X-API-Key": "s3cret"})
    await c.aclose()
    assert not sink.called
    assert res.liveness == Liveness.BLOCKED


@respx.mock
async def test_same_origin_redirect_keeps_credentials():
    respx.get("https://svc.test/a").mock(return_value=httpx.Response(
        301, headers={"Location": "/b"}))
    target = respx.get("https://svc.test/b").mock(return_value=httpx.Response(200, json={"k": 1}))
    c = _client()
    res = await c.request("GET", "https://svc.test/a", headers={"X-API-Key": "s3cret"})
    await c.aclose()
    assert res.liveness == Liveness.LIVE and res.json == {"k": 1}
    assert target.calls.last.request.headers["x-api-key"] == "s3cret"


@respx.mock
async def test_uncredentialed_cross_origin_redirect_is_followed():
    respx.get("https://svc.test/service-info").mock(return_value=httpx.Response(
        302, headers={"Location": "https://mirror.test/service-info"}))
    respx.get("https://mirror.test/service-info").mock(
        return_value=httpx.Response(200, json={"id": "x"}))
    c = _client()
    res = await c.get_json("https://svc.test/service-info")
    await c.aclose()
    assert res.liveness == Liveness.LIVE and res.url == "https://mirror.test/service-info"


# -------------------------------------------------------------------------------- SSRF

@respx.mock
async def test_redirect_to_cloud_metadata_is_blocked():
    respx.get("https://svc.test/service-info").mock(return_value=httpx.Response(
        302, headers={"Location": "http://169.254.169.254/latest/meta-data/iam/"}))
    meta = respx.get("http://169.254.169.254/latest/meta-data/iam/").mock(
        return_value=httpx.Response(200, json={"role": "x"}))
    c = _client()
    res = await c.get_json("https://svc.test/service-info")
    await c.aclose()
    assert not meta.called
    assert res.liveness == Liveness.BLOCKED


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",
    "http://127.0.0.1:8080/admin",
    "http://localhost/admin",
    "http://[::1]/admin",
    "http://10.1.2.3/",
    "http://192.168.0.10/",
    "http://0.0.0.0/",
    "file:///etc/passwd",
    "https://user:pw@svc.test/service-info",
])
@respx.mock
async def test_model_supplied_url_cannot_reach_internal_targets(ctx, url):
    route = respx.route().mock(return_value=httpx.Response(200, json={"secret": "internal"}))
    out = await tools.get_service_info(ctx, url=url)
    assert not route.called
    assert out["ok"] is False


@respx.mock
async def test_hostname_resolving_to_private_address_is_blocked(monkeypatch):
    async def private(host, port):
        return ["10.0.0.7"]
    monkeypatch.setattr(http_mod, "_resolve_addresses", private)
    route = respx.get("https://internal.test/service-info").mock(
        return_value=httpx.Response(200, json={"id": "x"}))
    c = _client()
    res = await c.get_json("https://internal.test/service-info")
    await c.aclose()
    assert not route.called and res.liveness == Liveness.BLOCKED


@respx.mock
async def test_private_hosts_allowed_with_explicit_local_development_flag():
    route = respx.get("http://127.0.0.1:18080/service-info").mock(
        return_value=httpx.Response(200, json={"id": "x"}))
    c = _client(agentic_allow_private_hosts=True)
    res = await c.get_json("http://127.0.0.1:18080/service-info")
    await c.aclose()
    assert route.called and res.liveness == Liveness.LIVE


# ------------------------------------------------------------ credentials bound to origin

CGC = {
    "id": "2432a48d-99b6-4b9c-98f7-c5cbc074f680",
    "implementationId": "com.sb.cgc.drs",
    "serviceInfoUrl": "https://cgc-ga4gh-api.sbgenomics.com/ga4gh/drs/v1/service-info",
    "url": "https://cgc-ga4gh-api.sbgenomics.com",
    "standardVersion": {"ga4ghProduct": "DRS", "version": "1.2.0"},
}
# A second entry (another registry record, a deployment, or a federated registry) that reuses
# the implementationId but points at a different host.
IMPOSTOR = {
    **CGC,
    "id": "99999999-0000-4000-8000-000000000000",
    "serviceInfoUrl": "https://collector.test/ga4gh/drs/v1/service-info",
    "url": "https://collector.test",
}


async def _ctx_with(tmp_path, monkeypatch, services, specs, **overrides):
    monkeypatch.setenv("CGC_TOKEN", "cgc-secret")
    cfg = tmp_path / "auth.json"
    cfg.write_text(json.dumps({"services": specs}))
    settings = load_settings(registry_base_url="https://registry.test/api", max_retries=0,
                             retry_backoff=0.0, auth_config=str(cfg), **overrides)
    c = ServerContext.create(settings)
    c.registry._cache.set("services", services)
    c.registry._cache.set("deployments", [])
    return c


@respx.mock
async def test_implementation_id_credential_not_sent_to_other_host(tmp_path, monkeypatch):
    c = await _ctx_with(tmp_path, monkeypatch, [CGC, IMPOSTOR],
                        {"com.sb.cgc.drs": {"kind": "bearer", "token_env": "CGC_TOKEN",
                                            "host": "cgc-ga4gh-api.sbgenomics.com"}})
    sink = respx.get("https://collector.test/ga4gh/drs/v1/objects/o1").mock(
        return_value=httpx.Response(200, json={"id": "o1"}))
    await tools.drs_get_object(c, service_id=IMPOSTOR["id"], object_id="o1")
    await c.aclose()
    assert sink.called
    assert "authorization" not in sink.calls.last.request.headers


@respx.mock
async def test_implementation_id_credential_sent_to_its_own_host(tmp_path, monkeypatch):
    c = await _ctx_with(tmp_path, monkeypatch, [CGC],
                        {"com.sb.cgc.drs": {"kind": "bearer", "token_env": "CGC_TOKEN",
                                            "host": "cgc-ga4gh-api.sbgenomics.com"}})
    route = respx.get("https://cgc-ga4gh-api.sbgenomics.com/ga4gh/drs/v1/objects/o1").mock(
        return_value=httpx.Response(200, json={"id": "o1"}))
    out = await tools.drs_get_object(c, service_id=CGC["id"], object_id="o1")
    await c.aclose()
    assert out["ok"] is True
    assert route.calls.last.request.headers["authorization"] == "Bearer cgc-secret"


@respx.mock
async def test_implementation_id_spec_without_host_sends_nothing(tmp_path, monkeypatch):
    # An implementationId alone names no destination, so it cannot scope a credential.
    c = await _ctx_with(tmp_path, monkeypatch, [IMPOSTOR],
                        {"com.sb.cgc.drs": {"kind": "bearer", "token_env": "CGC_TOKEN"}})
    sink = respx.get("https://collector.test/ga4gh/drs/v1/objects/o1").mock(
        return_value=httpx.Response(200, json={"id": "o1"}))
    await tools.drs_get_object(c, service_id=IMPOSTOR["id"], object_id="o1")
    status = await tools.auth_status(c)
    await c.aclose()
    assert "authorization" not in sink.calls.last.request.headers
    assert status["data"]["configured_specs"][0]["host"] is None
    assert "implementationId match sends nothing" in status["data"]["configured_specs"][0]["note"]


@respx.mock
async def test_global_bearer_not_sent_over_plain_http(ctx):
    ctx.settings.bearer_token = "glob"
    ctx.settings.bearer_hosts = "allowed.test"
    svc = {"id": "plain-1", "implementationId": "plain-1",
           "serviceInfoUrl": "http://allowed.test/ga4gh/drs/v1/service-info",
           "standardVersion": {"ga4ghProduct": "DRS", "version": "1.2.0"}}
    ctx.registry._cache.set("services", [svc])
    route = respx.get("http://allowed.test/ga4gh/drs/v1/objects/o1").mock(
        return_value=httpx.Response(200, json={"id": "o1"}))
    await tools.drs_get_object(ctx, service_id="plain-1", object_id="o1")
    assert "authorization" not in route.calls.last.request.headers


async def test_bound_provider_only_yields_headers_for_its_origin():
    settings = load_settings(bearer_token="glob", bearer_hosts="allowed.test")
    c = Ga4ghHttpClient(settings)
    auth = AuthResolver(settings, c).resolve(
        {"implementationId": "a", "serviceInfoUrl": "https://allowed.test/x"})
    assert await auth.headers_for("https://allowed.test/y") == {"Authorization": "Bearer glob"}
    assert await auth.headers_for("https://ALLOWED.test:443/y") == {"Authorization": "Bearer glob"}
    for url in ("http://allowed.test/y", "https://allowed.test.evil.test/y",
                "https://evil.test/y", "https://sub.allowed.test/y"):
        assert await auth.headers_for(url) == {}, url
    await c.aclose()


# ---------------------------------------------------------- DRS access capabilities

DRS_BASE = "https://drs.test/ga4gh/drs/v1"
SIGNED = {"url": "https://s3.test/obj?X-Amz-Signature=sig123&X-Amz-Credential=cred456",
          "headers": {"Authorization": "Bearer storage-token-789"}}


def _drs_ctx(ctx):
    svc = {"id": "drs-sec", "implementationId": "drs-sec",
           "serviceInfoUrl": f"{DRS_BASE}/service-info",
           "standardVersion": {"ga4ghProduct": "DRS", "version": "1.2.0"}}
    ctx.registry._cache.set("services", [svc])
    return ctx


@pytest.mark.parametrize("inline", [True, False])
@respx.mock
async def test_drs_access_url_capabilities_are_not_returned_to_the_model(ctx, inline):
    # DRS AccessURL.headers and pre-signed query strings are bearer capabilities for the storage
    # host. The Harness SDK redacts them; the registry-oriented tool returned them verbatim.
    method = ({"type": "https", "access_url": SIGNED} if inline
              else {"type": "s3", "access_id": "a1"})
    respx.get(f"{DRS_BASE}/objects/o1").mock(return_value=httpx.Response(
        200, json={"id": "o1", "access_methods": [method]}))
    respx.get(f"{DRS_BASE}/objects/o1/access/a1").mock(
        return_value=httpx.Response(200, json=SIGNED))
    out = await tools.drs_get_access_url(_drs_ctx(ctx), service_id="drs-sec", object_id="o1")
    blob = json.dumps(out)
    assert out["ok"] is True
    for secret in ("storage-token-789", "sig123", "cred456"):
        assert secret not in blob
    assert out["data"]["access_url"]["url"] == "https://s3.test/obj"
    assert out["data"]["access_url"]["headers"] == {"redacted": True}


@respx.mock
async def test_drs_object_inline_access_url_capabilities_are_redacted(ctx):
    respx.get(f"{DRS_BASE}/objects/o1").mock(return_value=httpx.Response(200, json={
        "id": "o1", "access_methods": [{"type": "https", "access_url": SIGNED}]}))
    out = await tools.drs_get_object(_drs_ctx(ctx), service_id="drs-sec", object_id="o1")
    blob = json.dumps(out)
    assert out["ok"] is True and out["data"]["id"] == "o1"
    for secret in ("storage-token-789", "sig123", "cred456"):
        assert secret not in blob
