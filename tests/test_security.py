"""Regression tests for credential scoping and outbound-destination safety.

Each test here reproduces a confused-deputy or SSRF path in the registry-oriented tool
surface (``server.py`` / ``tools.py`` / ``http_client.py``): a URL that comes from a
registry entry, an upstream response, or the model must not receive credentials issued for a
different origin, and must not reach loopback, private, or cloud-metadata addresses.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from ga4gh_mcp import http_client as http_mod
from ga4gh_mcp import tools
from ga4gh_mcp.config import load_settings
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
