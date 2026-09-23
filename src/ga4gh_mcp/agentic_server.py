"""MCP projection of the protocol-neutral GA4GH Agentic Harness SDK."""

from __future__ import annotations

import ipaddress
from contextlib import asynccontextmanager
from typing import Any

from ga4gh_agentic_harness import Harness, Operation
from ga4gh_agentic_harness.auth import AuthorityContext
from ga4gh_agentic_harness.conformance import TEST_PACK
from ga4gh_agentic_harness.models import ResultEnvelope
from ga4gh_agentic_harness.settings import Settings as HarnessSettings
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .config import Settings, load_settings

PROFILE_VERSION = "0.1.0"

INSTRUCTIONS = """\
GA4GH Agentic Harness MCP binding. Each tool maps exactly one canonical Harness operation
to the protocol-neutral Python SDK and returns its structured result envelope. Discover services
before invoking service operations. Registry declarations are not proof of liveness or
conformance. Credentials are managed below the tool boundary and must never be tool arguments.
"""

TOOL_OPERATION_MAP: dict[str, Operation] = {
    "ga4gh_harness_describe": Operation.HARNESS_DESCRIBE,
    "ga4gh_service_search": Operation.SERVICE_SEARCH,
    "ga4gh_service_describe": Operation.SERVICE_DESCRIBE,
    "ga4gh_service_probe": Operation.SERVICE_PROBE,
    "ga4gh_trs_workflow_resolve": Operation.TRS_WORKFLOW_RESOLVE,
    "ga4gh_drs_object_resolve": Operation.DRS_OBJECT_RESOLVE,
    "ga4gh_drs_access_resolve": Operation.DRS_ACCESS_RESOLVE,
    "ga4gh_beacon_variant_query": Operation.BEACON_VARIANT_QUERY,
    "ga4gh_wes_service_describe": Operation.WES_SERVICE_DESCRIBE,
    "ga4gh_wes_run_submit": Operation.WES_RUN_SUBMIT,
    "ga4gh_wes_run_get": Operation.WES_RUN_GET,
    "ga4gh_wes_run_cancel": Operation.WES_RUN_CANCEL,
    "ga4gh_conformance_assess": Operation.CONFORMANCE_ASSESS,
}

AGENTIC_TOOL_NAMES = list(TOOL_OPERATION_MAP)


def _annotations(
    *, read_only: bool, idempotent: bool = False, open_world: bool = False
) -> ToolAnnotations:
    return ToolAnnotations(
        readOnlyHint=read_only,
        destructiveHint=not read_only,
        idempotentHint=idempotent,
        openWorldHint=open_world,
    )


def _description(operation: Operation, purpose: str) -> str:
    return f"{purpose} Canonical operation: {operation.value}. Profile: {PROFILE_VERSION}."


def _structured(result: ResultEnvelope[Any]) -> dict[str, Any]:
    """Keep required nullable data while omitting other absent optional envelope fields."""
    payload = result.model_dump(mode="json", exclude_none=True)
    payload.setdefault("data", None)
    return payload


def _harness_settings(settings: Settings) -> HarnessSettings:
    """Map shared runtime settings while retaining SDK security defaults."""
    return HarnessSettings(
        registry_base_url=settings.registry_base_url,
        connect_timeout_seconds=settings.connect_timeout,
        read_timeout_seconds=settings.read_timeout,
        retry_backoff_seconds=settings.retry_backoff,
        max_retries=settings.max_retries,
        max_response_bytes=settings.max_response_bytes,
        verify_tls=settings.verify_tls,
        allow_http=settings.agentic_allow_http,
        allow_private_hosts=settings.agentic_allow_private_hosts,
        allowed_hosts=settings.agentic_allowed_host_list(),
    )


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _check_write_scope_exposure(settings: Settings) -> None:
    """Refuse write scopes when unauthenticated network clients would inherit them.

    The streamable-HTTP transport has no inbound authorization, so the server-wide scopes in
    ``agentic_write_scopes`` apply to every client that can reach the port. On loopback that is
    the local user; on any other bind address it is the network.
    """
    if (
        settings.transport == "streamable-http"
        and settings.agentic_write_scope_list()
        and not _is_loopback_host(settings.host)
    ):
        raise ValueError(
            "agentic write scopes cannot be enabled on a non-loopback streamable-http bind "
            f"({settings.host!r}): the transport has no inbound authorization, so every network "
            "client would be able to submit or cancel WES runs. Bind to 127.0.0.1 or clear "
            "GA4GH_MCP_AGENTIC_WRITE_SCOPES."
        )


def build_agentic_server(
    settings: Settings | None = None,
    *,
    harness: Harness | None = None,
) -> FastMCP:
    """Build a server with only the canonical Harness tools (see server.build_server for all)."""
    settings = settings or load_settings()
    sdk: Harness | None = None
    owns_harness = harness is None

    @asynccontextmanager
    async def lifespan(_server: FastMCP):
        try:
            yield {}
        finally:
            if owns_harness and sdk is not None:
                await sdk.aclose()

    mcp = FastMCP(
        name="ga4gh-agentic-harness",
        instructions=INSTRUCTIONS,
        host=settings.host,
        port=settings.port,
        streamable_http_path=settings.http_path,
        stateless_http=settings.stateless_http,
        lifespan=lifespan,
    )
    sdk = register_harness_tools(mcp, settings, harness=harness)
    return mcp


def register_harness_tools(
    mcp: FastMCP,
    settings: Settings,
    *,
    harness: Harness | None = None,
) -> Harness:
    """Register the canonical Harness tools on ``mcp`` and return the SDK Harness they use.

    The caller owns closing the returned Harness when it created it (``harness`` is None).
    """
    _check_write_scope_exposure(settings)
    sdk = harness or Harness(settings=_harness_settings(settings))
    authority = AuthorityContext(
        software_actor="local-mcp",
        inbound_scopes=settings.agentic_write_scope_list(),
    )

    async def invoke(operation: Operation, payload: dict[str, Any]) -> dict[str, Any]:
        result = await sdk.dispatch(operation, payload, authority=authority)
        return _structured(result)

    @mcp.tool(
        annotations=_annotations(read_only=True, idempotent=True),
        description=_description(
            Operation.HARNESS_DESCRIBE, "Describe this Harness and its canonical capabilities."
        ),
        structured_output=True,
    )
    async def ga4gh_harness_describe() -> dict[str, Any]:
        return await invoke(Operation.HARNESS_DESCRIBE, {})

    @mcp.tool(
        annotations=_annotations(read_only=True, idempotent=True, open_world=True),
        description=_description(
            Operation.SERVICE_SEARCH, "Search declarations of GA4GH services."
        ),
        structured_output=True,
    )
    async def ga4gh_service_search(
        query: str | None = None,
        product: str | None = None,
        organization: str | None = None,
        environment: str | None = None,
        limit: int = 50,
        cursor: int = 0,
    ) -> dict[str, Any]:
        return await invoke(
            Operation.SERVICE_SEARCH,
            {
                "query": query,
                "product": product,
                "organization": organization,
                "environment": environment,
                "limit": limit,
                "cursor": cursor,
            },
        )

    @mcp.tool(
        annotations=_annotations(read_only=True, idempotent=True, open_world=True),
        description=_description(
            Operation.SERVICE_DESCRIBE,
            "Describe a registered service and its Harness capabilities.",
        ),
        structured_output=True,
    )
    async def ga4gh_service_describe(service_id: str) -> dict[str, Any]:
        return await invoke(Operation.SERVICE_DESCRIBE, {"service_id": service_id})

    @mcp.tool(
        annotations=_annotations(read_only=True, open_world=True),
        description=_description(
            Operation.SERVICE_PROBE, "Perform a bounded service compatibility observation."
        ),
        structured_output=True,
    )
    async def ga4gh_service_probe(service_id: str) -> dict[str, Any]:
        return await invoke(Operation.SERVICE_PROBE, {"service_id": service_id})

    @mcp.tool(
        annotations=_annotations(read_only=True, open_world=True),
        description=_description(
            Operation.TRS_WORKFLOW_RESOLVE, "Resolve a versioned workflow through TRS."
        ),
        structured_output=True,
    )
    async def ga4gh_trs_workflow_resolve(
        service_id: str,
        tool_id: str,
        version: str | None = None,
        descriptor_type: str | None = None,
    ) -> dict[str, Any]:
        return await invoke(
            Operation.TRS_WORKFLOW_RESOLVE,
            {
                "service_id": service_id,
                "tool_id": tool_id,
                "version": version,
                "descriptor_type": descriptor_type,
            },
        )

    @mcp.tool(
        annotations=_annotations(read_only=True, open_world=True),
        description=_description(Operation.DRS_OBJECT_RESOLVE, "Resolve a DRS data object."),
        structured_output=True,
    )
    async def ga4gh_drs_object_resolve(
        service_id: str, object_id: str, expand: bool = False
    ) -> dict[str, Any]:
        return await invoke(
            Operation.DRS_OBJECT_RESOLVE,
            {"service_id": service_id, "object_id": object_id, "expand": expand},
        )

    @mcp.tool(
        annotations=_annotations(read_only=True, open_world=True),
        description=_description(
            Operation.DRS_ACCESS_RESOLVE,
            "Resolve a DRS access method with capability-sensitive fields redacted.",
        ),
        structured_output=True,
    )
    async def ga4gh_drs_access_resolve(
        service_id: str, object_id: str, access_id: str
    ) -> dict[str, Any]:
        return await invoke(
            Operation.DRS_ACCESS_RESOLVE,
            {"service_id": service_id, "object_id": object_id, "access_id": access_id},
        )

    @mcp.tool(
        annotations=_annotations(read_only=True, open_world=True),
        description=_description(
            Operation.BEACON_VARIANT_QUERY,
            "Query a Beacon for variant evidence; results are not a clinical conclusion.",
        ),
        structured_output=True,
    )
    async def ga4gh_beacon_variant_query(
        service_id: str,
        query: dict[str, Any],
        entry_type: str = "g_variants",
    ) -> dict[str, Any]:
        return await invoke(
            Operation.BEACON_VARIANT_QUERY,
            {"service_id": service_id, "query": query, "entry_type": entry_type},
        )

    @mcp.tool(
        annotations=_annotations(read_only=True, idempotent=True, open_world=True),
        description=_description(
            Operation.WES_SERVICE_DESCRIBE, "Describe WES execution capabilities."
        ),
        structured_output=True,
    )
    async def ga4gh_wes_service_describe(service_id: str) -> dict[str, Any]:
        return await invoke(Operation.WES_SERVICE_DESCRIBE, {"service_id": service_id})

    @mcp.tool(
        annotations=_annotations(read_only=False, open_world=True),
        description=_description(Operation.WES_RUN_SUBMIT, "Submit a workflow run to WES."),
        structured_output=True,
    )
    async def ga4gh_wes_run_submit(
        service_id: str,
        workflow_url: str,
        workflow_type: str,
        workflow_type_version: str,
        workflow_params: dict[str, Any],
        tags: dict[str, Any] | None = None,
        workflow_engine_parameters: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        return await invoke(
            Operation.WES_RUN_SUBMIT,
            {
                "service_id": service_id,
                "workflow_url": workflow_url,
                "workflow_type": workflow_type,
                "workflow_type_version": workflow_type_version,
                "workflow_params": workflow_params,
                "tags": tags,
                "workflow_engine_parameters": workflow_engine_parameters,
                "idempotency_key": idempotency_key,
            },
        )

    @mcp.tool(
        annotations=_annotations(read_only=True, open_world=True),
        description=_description(Operation.WES_RUN_GET, "Retrieve a WES workflow run."),
        structured_output=True,
    )
    async def ga4gh_wes_run_get(
        service_id: str, run_id: str, local_run_id: str | None = None
    ) -> dict[str, Any]:
        return await invoke(
            Operation.WES_RUN_GET,
            {"service_id": service_id, "run_id": run_id, "local_run_id": local_run_id},
        )

    @mcp.tool(
        annotations=_annotations(read_only=False, idempotent=True, open_world=True),
        description=_description(Operation.WES_RUN_CANCEL, "Request cancellation of a WES run."),
        structured_output=True,
    )
    async def ga4gh_wes_run_cancel(
        service_id: str, run_id: str, local_run_id: str | None = None
    ) -> dict[str, Any]:
        return await invoke(
            Operation.WES_RUN_CANCEL,
            {"service_id": service_id, "run_id": run_id, "local_run_id": local_run_id},
        )

    @mcp.tool(
        annotations=_annotations(read_only=True, open_world=True),
        description=_description(
            Operation.CONFORMANCE_ASSESS,
            "Run a deterministic read-only conformance test pack; this is not certification.",
        ),
        structured_output=True,
    )
    async def ga4gh_conformance_assess(
        service_id: str, test_pack: str = TEST_PACK
    ) -> dict[str, Any]:
        return await invoke(
            Operation.CONFORMANCE_ASSESS,
            {"service_id": service_id, "test_pack": test_pack},
        )

    mcp._ga4gh_harness = sdk  # type: ignore[attr-defined]
    return sdk
