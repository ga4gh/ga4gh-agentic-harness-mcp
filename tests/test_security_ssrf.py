"""Hosted (streamable-http) deployments must not fetch internal / metadata addresses.

``get_service_info(url=...)`` fetches any URL the caller names, and registry entries or
redirects can name any host. Run as a hosted server, that reaches the cloud metadata service
(169.254.169.254) and other internal-only endpoints and returns their bodies to the caller.
"""

from __future__ import annotations

import httpx
import respx

from ga4gh_mcp import tools
from ga4gh_mcp.config import load_settings
from ga4gh_mcp.context import ServerContext

META = "http://169.254.169.254/latest/meta-data/iam/security-credentials/"


def _ctx(**kw):
    s = load_settings(registry_base_url="https://registry.test/api", max_retries=0,
                      retry_backoff=0.0, **kw)
    return ServerContext.create(s)


@respx.mock
async def test_hosted_server_refuses_metadata_address():
    route = respx.get(META).mock(return_value=httpx.Response(200, json={"AccessKeyId": "AK"}))
    ctx = _ctx(transport="streamable-http")
    try:
        r = await tools.get_service_info(ctx, url=META)
    finally:
        await ctx.aclose()
    assert not route.called
    assert r["ok"] is False


@respx.mock
async def test_hosted_server_refuses_loopback():
    route = respx.get("http://127.0.0.1:9000/admin").mock(return_value=httpx.Response(200, json={}))
    ctx = _ctx(transport="streamable-http")
    try:
        await tools.get_service_info(ctx, url="http://127.0.0.1:9000/admin")
    finally:
        await ctx.aclose()
    assert not route.called


@respx.mock
async def test_hosted_server_refuses_redirect_into_metadata_address():
    respx.get("https://public.test/service-info").mock(return_value=httpx.Response(
        302, headers={"Location": META}))
    route = respx.get(META).mock(return_value=httpx.Response(200, json={"AccessKeyId": "AK"}))
    ctx = _ctx(transport="streamable-http")
    try:
        await tools.get_service_info(ctx, url="https://public.test/service-info")
    finally:
        await ctx.aclose()
    assert not route.called


@respx.mock
async def test_stdio_default_and_explicit_opt_out_still_reach_private_addresses():
    route = respx.get("http://127.0.0.1:9000/service-info").mock(return_value=httpx.Response(
        200, json={"id": "x", "name": "n", "type": {"artifact": "drs", "version": "1.2.0"},
                   "version": "1.2.0", "organization": {"name": "o", "url": "https://o"}}))
    for kw in ({}, {"transport": "streamable-http", "block_private_addresses": False}):
        ctx = _ctx(**kw)
        try:
            r = await tools.get_service_info(ctx, url="http://127.0.0.1:9000/service-info")
        finally:
            await ctx.aclose()
        assert r["ok"] is True
    assert route.call_count == 2
