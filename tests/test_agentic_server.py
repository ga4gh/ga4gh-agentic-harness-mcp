"""Contract tests for the MCP projection over the Agentic Harness SDK."""

from __future__ import annotations

from typing import Any

import pytest
from ga4gh_agentic_harness import Harness, Operation
from ga4gh_agentic_harness.conformance import TEST_PACK
from ga4gh_agentic_harness.models import ResultEnvelope, ResultStatus

from ga4gh_mcp.__main__ import main
from ga4gh_mcp.agentic_server import (
    AGENTIC_TOOL_NAMES,
    PROFILE_VERSION,
    TOOL_OPERATION_MAP,
    build_agentic_server,
)
from ga4gh_mcp.config import load_settings


class RecordingHarness:
    def __init__(self) -> None:
        self.calls: list[tuple[Operation, dict[str, Any], Any]] = []

    async def dispatch(
        self, operation: Operation, payload: dict[str, Any], *, authority: Any
    ) -> ResultEnvelope[dict[str, Any]]:
        self.calls.append((operation, payload, authority))
        return ResultEnvelope[dict[str, Any]](
            profile_version=PROFILE_VERSION,
            operation=operation,
            request_id="request-1234",
            status=ResultStatus.SUCCESS,
            data={"received": payload},
            trace_id="trace-1234",
        )


def _structured(result: Any) -> dict[str, Any]:
    return result[1] if isinstance(result, tuple) else result


async def test_canonical_tools_and_annotations_register():
    harness = RecordingHarness()
    mcp = build_agentic_server(load_settings(), harness=harness)  # type: ignore[arg-type]
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    assert list(tools) == AGENTIC_TOOL_NAMES
    assert set(tools) == set(TOOL_OPERATION_MAP)
    for name, tool in tools.items():
        operation = TOOL_OPERATION_MAP[name]
        assert operation.value in (tool.description or "")
        assert PROFILE_VERSION in (tool.description or "")
        assert isinstance(tool.inputSchema, dict)
        assert isinstance(tool.outputSchema, dict)
        assert tool.annotations is not None

    assert tools["ga4gh_harness_describe"].annotations.readOnlyHint is True
    assert tools["ga4gh_wes_run_submit"].annotations.destructiveHint is True
    assert tools["ga4gh_wes_run_cancel"].annotations.destructiveHint is True


CASES = [
    ("ga4gh_harness_describe", {}, Operation.HARNESS_DESCRIBE, {}),
    (
        "ga4gh_service_search",
        {"product": "DRS", "limit": 2},
        Operation.SERVICE_SEARCH,
        {
            "query": None,
            "product": "DRS",
            "organization": None,
            "environment": None,
            "limit": 2,
            "cursor": 0,
        },
    ),
    (
        "ga4gh_service_describe",
        {"service_id": "service-1"},
        Operation.SERVICE_DESCRIBE,
        {"service_id": "service-1"},
    ),
    (
        "ga4gh_service_probe",
        {"service_id": "service-1"},
        Operation.SERVICE_PROBE,
        {"service_id": "service-1"},
    ),
    (
        "ga4gh_trs_workflow_resolve",
        {"service_id": "trs-1", "tool_id": "workflow", "version": "1"},
        Operation.TRS_WORKFLOW_RESOLVE,
        {
            "service_id": "trs-1",
            "tool_id": "workflow",
            "version": "1",
            "descriptor_type": None,
        },
    ),
    (
        "ga4gh_drs_object_resolve",
        {"service_id": "drs-1", "object_id": "object-1"},
        Operation.DRS_OBJECT_RESOLVE,
        {"service_id": "drs-1", "object_id": "object-1", "expand": False},
    ),
    (
        "ga4gh_drs_access_resolve",
        {"service_id": "drs-1", "object_id": "object-1", "access_id": "access-1"},
        Operation.DRS_ACCESS_RESOLVE,
        {"service_id": "drs-1", "object_id": "object-1", "access_id": "access-1"},
    ),
    (
        "ga4gh_beacon_variant_query",
        {"service_id": "beacon-1", "query": {"referenceName": "1"}},
        Operation.BEACON_VARIANT_QUERY,
        {
            "service_id": "beacon-1",
            "query": {"referenceName": "1"},
            "entry_type": "g_variants",
        },
    ),
    (
        "ga4gh_wes_service_describe",
        {"service_id": "wes-1"},
        Operation.WES_SERVICE_DESCRIBE,
        {"service_id": "wes-1"},
    ),
    (
        "ga4gh_wes_run_submit",
        {
            "service_id": "wes-1",
            "workflow_url": "https://example.org/workflow.cwl",
            "workflow_type": "CWL",
            "workflow_type_version": "v1.2",
            "workflow_params": {},
        },
        Operation.WES_RUN_SUBMIT,
        {
            "service_id": "wes-1",
            "workflow_url": "https://example.org/workflow.cwl",
            "workflow_type": "CWL",
            "workflow_type_version": "v1.2",
            "workflow_params": {},
            "tags": None,
            "workflow_engine_parameters": None,
            "idempotency_key": None,
        },
    ),
    (
        "ga4gh_wes_run_get",
        {"service_id": "wes-1", "run_id": "run-1"},
        Operation.WES_RUN_GET,
        {"service_id": "wes-1", "run_id": "run-1", "local_run_id": None},
    ),
    (
        "ga4gh_wes_run_cancel",
        {"service_id": "wes-1", "run_id": "run-1"},
        Operation.WES_RUN_CANCEL,
        {"service_id": "wes-1", "run_id": "run-1", "local_run_id": None},
    ),
    (
        "ga4gh_conformance_assess",
        {"service_id": "drs-1"},
        Operation.CONFORMANCE_ASSESS,
        {"service_id": "drs-1", "test_pack": TEST_PACK},
    ),
]


@pytest.mark.parametrize(("tool", "arguments", "operation", "payload"), CASES)
async def test_every_tool_dispatches_to_matching_sdk_operation(
    tool: str,
    arguments: dict[str, Any],
    operation: Operation,
    payload: dict[str, Any],
):
    harness = RecordingHarness()
    mcp = build_agentic_server(load_settings(), harness=harness)  # type: ignore[arg-type]

    result = _structured(await mcp.call_tool(tool, arguments))

    assert harness.calls[0][0] == operation
    assert harness.calls[0][1] == payload
    assert harness.calls[0][2].software_actor == "local-mcp"
    assert result["operation"] == operation.value
    assert result["status"] == "success"
    assert result["data"] == {"received": payload}
    assert result["errors"] == []
    assert result["warnings"] == []


async def test_end_to_end_mcp_invocation_uses_real_sdk_harness():
    harness = Harness()
    mcp = build_agentic_server(load_settings(), harness=harness)
    try:
        result = _structured(await mcp.call_tool("ga4gh_harness_describe", {}))
    finally:
        await harness.aclose()

    assert result["operation"] == Operation.HARNESS_DESCRIBE.value
    assert result["status"] == "success"
    operations = {item["operation"] for item in result["data"]["capabilities"]}
    assert Operation.BEACON_VARIANT_QUERY.value in operations


def test_agentic_runtime_defaults_are_local_and_safe():
    settings = load_settings()
    mcp = build_agentic_server(settings)
    harness = mcp._ga4gh_harness  # type: ignore[attr-defined]

    assert settings.transport == "stdio"
    assert settings.host == "127.0.0.1"
    assert harness.settings.allow_http is False
    assert harness.settings.allow_private_hosts is False
    assert harness.settings.verify_tls is True


def test_agentic_local_exceptions_and_write_scopes_are_explicit():
    settings = load_settings(
        agentic_allow_http=True,
        agentic_allow_private_hosts=True,
        agentic_allowed_hosts="127.0.0.1",
        agentic_write_scopes="ga4gh:workflow:submit",
    )
    mcp = build_agentic_server(settings)
    harness = mcp._ga4gh_harness  # type: ignore[attr-defined]

    assert harness.settings.allow_http is True
    assert harness.settings.allow_private_hosts is True
    assert harness.settings.allowed_hosts == ["127.0.0.1"]


def test_cli_lists_harness_tools(capsys):
    assert main(["--list-tools"]) == 0
    output = capsys.readouterr().out
    assert '"profile": "ga4gh-agentic-harness"' in output
    assert '"ga4gh_harness_describe"' in output
    assert '"count": 13' in output
