"""Redirects must not carry credentials, or a credential-bearing body, to another origin.

httpx strips only ``Authorization`` on a cross-origin redirect. Custom auth headers (the
``api_key`` provider's ``X-API-Key``) survive, and a 307/308 re-sends a POST body such as a
client-credentials form carrying ``client_secret``.
"""

from __future__ import annotations

import httpx
import respx

from ga4gh_mcp.auth.providers import OAuth2ClientCredentialsAuth
from ga4gh_mcp.config import load_settings
from ga4gh_mcp.http_client import Ga4ghHttpClient


def _client():
    return Ga4ghHttpClient(load_settings(max_retries=0, retry_backoff=0.0))


@respx.mock
async def test_cross_origin_redirect_drops_custom_auth_header():
    respx.get("https://svc.test/objects/x").mock(return_value=httpx.Response(
        302, headers={"Location": "https://attacker.test/collect"}))
    sink = respx.get("https://attacker.test/collect").mock(
        return_value=httpx.Response(200, json={}))
    c = _client()
    await c.get_json("https://svc.test/objects/x",
                     headers={"X-API-Key": "k-secret", "Authorization": "Bearer t-secret"})
    await c.aclose()
    assert sink.called  # public redirects are still followed, just without credentials
    sent = sink.calls[0].request.headers
    assert "x-api-key" not in sent
    assert "authorization" not in sent


@respx.mock
async def test_scheme_downgrade_redirect_drops_custom_auth_header():
    respx.get("https://svc.test/objects/x").mock(return_value=httpx.Response(
        302, headers={"Location": "http://svc.test/objects/x"}))
    plain = respx.get("http://svc.test/objects/x").mock(return_value=httpx.Response(200, json={}))
    c = _client()
    await c.get_json("https://svc.test/objects/x", headers={"X-API-Key": "k-secret"})
    await c.aclose()
    assert plain.called
    assert "x-api-key" not in plain.calls[0].request.headers


@respx.mock
async def test_same_origin_redirect_keeps_auth_header():
    respx.get("https://svc.test/a").mock(return_value=httpx.Response(
        301, headers={"Location": "https://svc.test/b"}))
    b = respx.get("https://svc.test/b").mock(return_value=httpx.Response(200, json={"ok": 1}))
    c = _client()
    r = await c.get_json("https://svc.test/a", headers={"X-API-Key": "k"})
    await c.aclose()
    assert r.json == {"ok": 1}
    assert b.calls[0].request.headers["x-api-key"] == "k"


@respx.mock
async def test_307_to_other_origin_does_not_resend_client_secret():
    respx.post("https://idp.test/token").mock(return_value=httpx.Response(
        307, headers={"Location": "https://attacker.test/token"}))
    sink = respx.post("https://attacker.test/token").mock(return_value=httpx.Response(
        200, json={"access_token": "x", "expires_in": 60}))
    c = _client()
    p = OAuth2ClientCredentialsAuth(c, token_url="https://idp.test/token",
                                    client_id="cid", client_secret="c-secret")
    try:
        await p.headers()
    except Exception:  # noqa: BLE001 - a refused redirect surfaces as an auth error
        pass
    await c.aclose()
    assert not sink.called, "client_secret form body was re-sent to another origin"
