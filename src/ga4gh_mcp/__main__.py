"""CLI entrypoint: ``ga4gh-mcp`` / ``python -m ga4gh_mcp``."""

from __future__ import annotations

import argparse
import json
import sys

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
    if args.list_tools:
        print(json.dumps({"profile": "ga4gh-agentic-harness",
                          "tools": TOOL_NAMES, "count": len(TOOL_NAMES)}, indent=2))
        return 0

    server = build_server(settings)
    # stderr is safe to log to under stdio (stdout is the JSON-RPC channel).
    print(f"[ga4gh-mcp] starting tools={len(TOOL_NAMES)} transport={settings.transport} "
          f"registry={settings.registry_base_url}", file=sys.stderr)
    if settings.transport == "streamable-http":
        print(f"[ga4gh-mcp] listening on http://{settings.host}:{settings.port}"
              f"{settings.http_path}", file=sys.stderr)
    server.run(transport=settings.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
