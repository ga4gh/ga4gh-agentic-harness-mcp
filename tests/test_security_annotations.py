"""Tools declare MCP ToolAnnotations, and state-changing HTTP methods are opt-in.

``call_service_endpoint`` accepted POST/PUT/PATCH/DELETE against any registered service with
the configured credentials attached (e.g. TES POST /tasks, POST /tasks/{id}:cancel, WES
DELETE /runs/{id}), and no tool carried annotations, so a host had no signal to confirm.
"""

from __future__ import annotations

import httpx
import respx

from ga4gh_mcp import tools
from ga4gh_mcp.config import load_settings
from ga4gh_mcp.context import ServerContext
from ga4gh_mcp.server import build_server

READ_ONLY_EXCEPT = {"auth_device_login"}


async def _tools(**kw):
    settings = load_settings(**kw)
    ctx = ServerContext.create(settings)
    mcp = build_server(settings, ctx=ctx)
    listed = {t.name: t for t in await mcp.list_tools()}
    await ctx.aclose()
    return listed


async def test_every_tool_is_annotated():
    for name, t in (await _tools()).items():
        a = t.annotations
        assert a is not None, name
        for hint in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
            assert getattr(a, hint) is not None, (name, hint)
        if name in READ_ONLY_EXCEPT:
            assert a.readOnlyHint is False, name
        else:
            assert a.readOnlyHint is True and a.destructiveHint is False, name


async def test_generic_endpoint_annotated_destructive_only_when_writes_enabled():
    t = (await _tools(allow_write_methods=True))["call_service_endpoint"]
    assert t.annotations.readOnlyHint is False
    assert t.annotations.destructiveHint is True
    assert t.annotations.idempotentHint is False


TES = {"id": "u", "implementationId": "org.test.tes", "serviceInfoUrl":
       "https://tes.test/ga4gh/tes/v1/service-info",
       "standardVersion": {"ga4ghProduct": "TES", "version": "1.1"}}


@respx.mock
async def test_state_changing_methods_refused_by_default():
    route = respx.post("https://tes.test/ga4gh/tes/v1/tasks/t1:cancel").mock(
        return_value=httpx.Response(200, json={}))
    ctx = ServerContext.create(load_settings(max_retries=0))
    ctx.registry._cache.set("services", [TES])
    ctx.registry._cache.set("deployments", [])
    try:
        r = await tools.call_service_endpoint(ctx, service_id="org.test.tes",
                                              path="/tasks/t1:cancel", method="POST")
    finally:
        await ctx.aclose()
    assert r["ok"] is False and r["error"]["type"] == "validation"
    assert not route.called


@respx.mock
async def test_state_changing_methods_allowed_when_operator_opts_in():
    route = respx.post("https://tes.test/ga4gh/tes/v1/tasks/t1:cancel").mock(
        return_value=httpx.Response(200, json={}))
    ctx = ServerContext.create(load_settings(max_retries=0, allow_write_methods=True))
    ctx.registry._cache.set("services", [TES])
    ctx.registry._cache.set("deployments", [])
    try:
        r = await tools.call_service_endpoint(ctx, service_id="org.test.tes",
                                              path="/tasks/t1:cancel", method="POST")
    finally:
        await ctx.aclose()
    assert r["ok"] is True and route.called
