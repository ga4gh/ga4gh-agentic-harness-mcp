#!/usr/bin/env python3
"""Exercise the canonical MCP surface over local Streamable HTTP."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def _payload(result: Any) -> dict[str, Any]:
    structured = result.structuredContent
    if not isinstance(structured, dict):
        raise RuntimeError("tool returned no structured content")
    return structured


async def run(url: str, service_id: str | None, object_id: str | None) -> dict[str, Any]:
    async with streamable_http_client(url) as (read, write, _session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            described = _payload(await session.call_tool("ga4gh_harness_describe", {}))
            searched = _payload(
                await session.call_tool("ga4gh_service_search", {"product": "drs", "limit": 5})
            )
            output: dict[str, Any] = {
                "tool_count": len(listed.tools),
                "profile_version": described["profile_version"],
                "describe_status": described["status"],
                "search_status": searched["status"],
                "service_ids": [item["id"] for item in searched.get("data") or []],
            }
            if service_id and object_id:
                resolved = _payload(
                    await session.call_tool(
                        "ga4gh_drs_object_resolve",
                        {"service_id": service_id, "object_id": object_id},
                    )
                )
                output["drs_status"] = resolved["status"]
                output["drs_object_id"] = (resolved.get("data") or {}).get("id")
            return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8766/mcp")
    parser.add_argument("--service-id")
    parser.add_argument("--object-id")
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(run(args.url, args.service_id, args.object_id)),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
