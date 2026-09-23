"""CLI entrypoint: ``ga4gh-mcp`` / ``python -m ga4gh_mcp``."""

from __future__ import annotations

import argparse
import json
import sys

from .agentic_server import AGENTIC_TOOL_NAMES, build_agentic_server
from .config import load_settings
from .server import TOOL_NAMES, build_server


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ga4gh-mcp",
        description=(
            "Universal MCP server for GA4GH services "
            "(starts with the Implementation Registry)."
        ),
    )
    p.add_argument("--transport", choices=["stdio", "streamable-http"], default=None,
                   help="Transport (default: env GA4GH_MCP_TRANSPORT or 'stdio').")
    p.add_argument("--surface", choices=["agentic", "legacy"], default=None,
                   help="Tool surface (default: env GA4GH_MCP_SURFACE or 'agentic').")
    p.add_argument("--host", default=None, help="HTTP bind host (streamable-http).")
    p.add_argument("--port", type=int, default=None, help="HTTP bind port (streamable-http).")
    p.add_argument("--path", default=None, help="HTTP path for the MCP endpoint (default /mcp).")
    p.add_argument("--registry-url", default=None, help="Override the registry base URL.")
    p.add_argument("--agentic-allow-http", action="store_true",
                   help="Allow HTTP upstreams for local development.")
    p.add_argument("--agentic-allow-private-hosts", action="store_true",
                   help="Allow private/loopback upstreams for local development.")
    p.add_argument("--list-tools", action="store_true",
                   help="Print the registered tool names as JSON and exit (no server).")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    overrides = {}
    if args.surface:
        overrides["surface"] = args.surface
    if args.transport:
        overrides["transport"] = args.transport
    if args.host:
        overrides["host"] = args.host
    if args.port:
        overrides["port"] = args.port
    if args.path:
        overrides["http_path"] = args.path
    if args.registry_url:
        overrides["registry_base_url"] = args.registry_url
    if args.agentic_allow_http:
        overrides["agentic_allow_http"] = True
    if args.agentic_allow_private_hosts:
        overrides["agentic_allow_private_hosts"] = True

    settings = load_settings(**overrides)
    agentic = settings.surface == "agentic"
    if args.list_tools:
        tool_names = AGENTIC_TOOL_NAMES if agentic else TOOL_NAMES
        print(json.dumps({"surface": settings.surface,
                          **({"profile": "ga4gh-agentic-harness"} if agentic else {}),
                          "tools": tool_names, "count": len(tool_names)}, indent=2))
        return 0

    server = build_agentic_server(settings) if agentic else build_server(settings)
    # stderr is safe to log to under stdio (stdout is the JSON-RPC channel).
    print(f"[ga4gh-mcp] starting surface={settings.surface} transport={settings.transport} "
          f"registry={settings.registry_base_url}", file=sys.stderr)
    if settings.transport == "streamable-http":
        print(f"[ga4gh-mcp] listening on http://{settings.host}:{settings.port}"
              f"{settings.http_path}", file=sys.stderr)
    server.run(transport=settings.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
