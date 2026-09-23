#!/usr/bin/env python3
"""Submit a TRS workflow to a WES through the canonical MCP surface and wait for it.

Start a WES 1.1 service on this machine that also serves a GA4GH Service Registry at
/ga4gh/registry (the defaults below assume 127.0.0.1:18090 and service id local.ga4gh-wes),
then this server with that registry listed and the submit scope granted:

    ga4gh-mcp --surface agentic --transport streamable-http --port 8766 \\
      --agentic-allow-private-hosts
    # with GA4GH_MCP_REGISTRIES='[{"url": "https://implementation-registry.ga4gh.org/api",
    #   "api": "implementation-registry"},
    #   {"url": "http://127.0.0.1:18090/ga4gh/registry", "api": "service-registry"}]'
    #  and GA4GH_MCP_AGENTIC_WRITE_SCOPES=ga4gh:workflow:submit,ga4gh:workflow:cancel
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

HELLO = (
    "trs://dockstore.org/%23workflow%2Fgithub.com%2Fga4gh-tech-team%2Fwdl-hello-world"
    "%2FwdlHelloWorld/main"
)
TERMINAL = {"COMPLETE", "EXECUTOR_ERROR", "SYSTEM_ERROR", "CANCELED", "PREEMPTED"}


def _payload(result: Any) -> dict[str, Any]:
    structured = result.structuredContent
    if not isinstance(structured, dict):
        raise RuntimeError("tool returned no structured content")
    return structured


async def run(url: str, service_id: str, workflow_url: str, timeout: float) -> dict[str, Any]:
    async with streamable_http_client(url) as (read, write, _session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            call = session.call_tool
            searched = _payload(await call("ga4gh_service_search", {"product": "wes"}))
            described = _payload(await call("ga4gh_wes_service_describe", {"service_id": service_id}))
            submitted = _payload(
                await call(
                    "ga4gh_wes_run_submit",
                    {
                        "service_id": service_id,
                        "workflow_url": workflow_url,
                        "workflow_type": "WDL",
                        "workflow_type_version": "1.0",
                        "workflow_params": {},
                    },
                )
            )
            if submitted["status"] != "success":
                return {"submit": submitted}
            run_id = submitted["data"]["run"]["run_id"]
            local_run_id = submitted["data"]["ledger"]["local_run_id"]
            started = time.monotonic()
            states: list[str] = []
            while True:
                got = _payload(
                    await call(
                        "ga4gh_wes_run_get",
                        {"service_id": service_id, "run_id": run_id, "local_run_id": local_run_id},
                    )
                )
                state = (got.get("data") or {}).get("state", "UNKNOWN")
                if not states or states[-1] != state:
                    states.append(state)
                if state in TERMINAL or time.monotonic() - started > timeout:
                    break
                await asyncio.sleep(1)
            return {
                "wes_services": [item["id"] for item in searched.get("data") or []],
                "workflow_types": sorted((described.get("data") or {}).get("workflow_type_versions") or {}),
                "run_id": run_id,
                "states": states,
                "seconds": round(time.monotonic() - started, 1),
                "outputs": (got.get("data") or {}).get("outputs"),
            }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8766/mcp")
    parser.add_argument("--service-id", default="local.ga4gh-wes")
    parser.add_argument("--workflow-url", default=HELLO)
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()
    result = asyncio.run(run(args.url, args.service_id, args.workflow_url, args.timeout))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
