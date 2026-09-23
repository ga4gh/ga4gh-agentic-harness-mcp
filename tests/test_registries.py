"""The registries setting: one list, each entry declaring the API it speaks."""

from __future__ import annotations

import httpx
import pytest
import respx

from ga4gh_mcp.__main__ import _parser, _registry
from ga4gh_mcp.agentic_server import build_agentic_server
from ga4gh_mcp.config import (
    GA4GH_IMPLEMENTATION_REGISTRY,
    RegistrySource,
    load_settings,
)
from ga4gh_mcp.context import ServerContext
from ga4gh_mcp.errors import ToolError

IR = "https://registry.test/api"
SR = "https://local.test/ga4gh/registry"
WES = {
    "id": "local.ga4gh-wes",
    "name": "Local WES",
    "type": {"group": "org.ga4gh", "artifact": "wes", "version": "1.1.0"},
    "url": "https://local.test/ga4gh/wes/v1",
}


def _ctx(*registries: tuple[str, str]) -> ServerContext:
    settings = load_settings(
        registries=[{"api": api, "url": url} for api, url in registries],
        max_retries=0,
        retry_backoff=0.0,
    )
    return ServerContext.create(settings)


def test_default_is_the_ga4gh_implementation_registry(monkeypatch):
    monkeypatch.delenv("GA4GH_MCP_REGISTRIES", raising=False)
    assert load_settings().registries == [GA4GH_IMPLEMENTATION_REGISTRY]


def test_registries_come_from_json_and_replace_the_default(monkeypatch):
    monkeypatch.setenv("GA4GH_MCP_REGISTRIES", f'[{{"url": "{SR}", "api": "service-registry"}}]')
    assert load_settings().registries == [RegistrySource(url=SR, api="service-registry")]


def test_registry_list_must_be_non_empty_and_name_a_known_api():
    with pytest.raises(ValueError, match="at least one registry"):
        load_settings(registries=[])
    with pytest.raises(ValueError):
        load_settings(registries=[{"url": SR, "api": "guess"}])


@respx.mock
async def test_service_registry_only_lists_its_services_and_has_no_standards():
    respx.get(SR + "/services").mock(return_value=httpx.Response(200, json=[WES]))
    ctx = _ctx(("service-registry", SR))
    services = await ctx.registry.list_services(product="WES")
    assert [s["implementationId"] for s in services] == ["local.ga4gh-wes"]
    assert await ctx.registry.standards() == []
    assert await ctx.registry.organisations() == []


@respx.mock
async def test_a_down_implementation_registry_does_not_hide_a_service_registry():
    respx.get(IR + "/services").mock(return_value=httpx.Response(503))
    respx.get(SR + "/services").mock(return_value=httpx.Response(200, json=[WES]))
    ctx = _ctx(("implementation-registry", IR), ("service-registry", SR))
    services = await ctx.registry.list_services()
    assert [s["implementationId"] for s in services] == ["local.ga4gh-wes"]


@respx.mock
async def test_implementation_registry_alone_down_is_an_error():
    respx.get(IR + "/services").mock(return_value=httpx.Response(503))
    with pytest.raises(ToolError):
        await _ctx(("implementation-registry", IR)).registry.list_services()


def test_cli_registry_flags_replace_the_default():
    parser = _parser()
    assert _registry(f"service-registry={SR}", parser) == {"url": SR, "api": "service-registry"}
    with pytest.raises(SystemExit):
        _registry(SR, parser)
    with pytest.raises(SystemExit):
        _registry(f"guess={SR}", parser)


def test_the_harness_receives_the_same_registries():
    settings = load_settings(
        registries=[
            {"url": IR, "api": "implementation-registry"},
            {"url": SR, "api": "service-registry"},
        ]
    )
    harness = build_agentic_server(settings)._ga4gh_harness  # type: ignore[attr-defined]
    assert [(r.url, r.api) for r in harness.settings.registries] == [
        (IR, "implementation-registry"),
        (SR, "service-registry"),
    ]
