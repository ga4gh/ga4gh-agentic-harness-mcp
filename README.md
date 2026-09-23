# ga4gh-agentic-harness-mcp

A **reference [MCP](https://modelcontextprotocol.io) implementation of the GA4GH Agentic Harness.**
It makes
the [GA4GH Implementation Registry](https://implementation-registry.ga4gh.org/) and the services it
lists usable by any MCP client (Claude Desktop/Code, Vertex AI, Bedrock). It is built to tolerate
the real world: registered implementations vary widely in **liveness, spec compliance, and version**,
and the server degrades gracefully instead of failing.

- **Transports:** `stdio` (Claude Desktop/Code) and `streamable-http` (remote / Vertex / Bedrock).
- **Tools:** registry list/detail/search/health + generic (service-info driven) + type-aware
  (DRS, TRS, TES, Beacon) access, plus a pluggable auth layer.
- **Robustness:** every upstream call is timed out, retried, and classified; one bad service never
  crashes the server. See [`docs/compatibility.md`](docs/compatibility.md) for the empirical basis.

## Install

```bash
git clone https://github.com/ga4gh/ga4gh-agentic-harness-mcp && cd ga4gh-agentic-harness-mcp
uv venv && . .venv/bin/activate      # or: python -m venv .venv && . .venv/bin/activate
uv pip install -e ".[dev]"           # or: pip install -e ".[dev]"
```

The Harness SDK is installed from
[`ga4gh/ga4gh-agentic-harness-python`](https://github.com/ga4gh/ga4gh-agentic-harness-python)
(see `[tool.uv.sources]` in `pyproject.toml`). To develop against a local SDK checkout, sync
and then install it editable over the locked copy:

```bash
uv sync --extra dev
uv pip install -e ../ga4gh-agentic-harness-python
```

Run directly with no clone via uvx:

```bash
uvx --from git+https://github.com/ga4gh/ga4gh-agentic-harness-mcp ga4gh-mcp --list-tools
```

## Run

```bash
# stdio (default) — for Claude Desktop / Claude Code
ga4gh-mcp                      # or: python -m ga4gh_mcp

# local streamable HTTP
ga4gh-mcp --transport streamable-http \
  --host 127.0.0.1 --port 8000 --path /mcp
```

All options are also env vars (prefix `GA4GH_MCP_`):
`GA4GH_MCP_TRANSPORT`, `GA4GH_MCP_HOST`,
`GA4GH_MCP_PORT`, `GA4GH_MCP_HTTP_PATH`, `GA4GH_MCP_REGISTRIES`, timeouts, cache TTLs,
`GA4GH_MCP_AUTH_CONFIG`, `GA4GH_MCP_BEARER_TOKEN`, `GA4GH_MCP_BEARER_HOSTS`. See `.env.example`.

### Registries

Services are discovered from one list of registries. Each entry is a URL and the API it speaks,
declared rather than probed: `implementation-registry` (the GA4GH Implementation Registry, which
also supplies standards, organisations and deployments) or `service-registry` (any GA4GH Service
Registry `/services` endpoint, such as a local WES or `ga4gh-aws-opendata`). The default is the
GA4GH Implementation Registry alone. Setting the list replaces it:

```bash
GA4GH_MCP_REGISTRIES='[
  {"url": "https://implementation-registry.ga4gh.org/api", "api": "implementation-registry"},
  {"url": "http://127.0.0.1:18090/ga4gh/registry", "api": "service-registry"}
]' ga4gh-mcp --agentic-allow-private-hosts

# or on the command line (repeatable)
ga4gh-mcp --registry implementation-registry=https://implementation-registry.ga4gh.org/api \
  --registry service-registry=http://127.0.0.1:18090/ga4gh/registry
```

An unreachable registry is skipped while another answers. The same list reaches the Harness SDK.
Plain HTTP to this machine (`localhost`, `127.0.0.1`, `::1`) needs only
`--agentic-allow-private-hosts`; every other host still requires HTTPS.

## Tools

One server exposes 34 tools (`ga4gh-mcp --list-tools`):

- **13 Agentic Harness tools** (`ga4gh_*`), the canonical operations of the Agentic Harness MCP
  crosswalk: service search, describe and probe; TRS workflow resolution; DRS object and
  access resolution; Beacon variant query (v1 and v2); WES describe, submit, get and cancel;
  conformance assessment. They delegate to the protocol-neutral SDK and return the Harness
  result envelope. See [`docs/agentic-harness.md`](docs/agentic-harness.md).
- **21 registry and service tools**: Implementation Registry browsing (services, standards,
  organisations, service types, health, service-info), DRS, TRS tool listing, TES tasks,
  Beacon info, Data Connect tables and SQL search, a generic `call_service_endpoint`, and auth
  status / device login. They return `{"ok", "data" | "error", "warnings"}`.

Where both sets cover the same standard (DRS, TRS, service discovery), prefer the Harness tool.
Data Connect, TES and TRS listing exist only in the second set today.

## Verify from the CLI (no UI needed)

```bash
. .venv/bin/activate

# 1) Tools register + schemas load and transport round trips
python scripts/smoke.py                    # exercises registry tools end-to-end; prints PASS/FAIL

# 2) Unit tests (fully mocked; no network)
pytest -q                                  # expect: all passed

# 3) Live integration smoke (hits real registered services; skips offline)
GA4GH_MCP_LIVE=1 pytest -q tests/test_live_integration.py   # prints a pass/fail table

# 4) Re-probe the registry & regenerate the compatibility matrix
python scripts/probe_registry.py

# 5) HTTP transport is reachable
ga4gh-mcp --transport streamable-http --port 8000 &         # background
curl -s -i http://127.0.0.1:8000/mcp -H 'Accept: text/event-stream' | head -n 5   # expect HTTP 4xx/200 from the MCP endpoint (not connection refused)
```

Expected `scripts/smoke.py` tail:

```
[smoke] list_service_types: ok
[smoke] list_services(product=DRS): ok, N services
[smoke] get_service(<id>): ok
[smoke] check_service_health(<id>): <liveness>
[smoke] ALL CHECKS PASSED (tools=18)
```

## Clients

Copy-paste connection configs, each with a verification step, in
[`docs/clients/`](docs/clients/): [Claude Desktop](docs/clients/claude-desktop.md),
[Claude Code](docs/clients/claude-code.md), [Vertex AI](docs/clients/vertex-ai.md),
[Amazon Bedrock](docs/clients/bedrock.md).

## Auth

Pluggable (`none`, static `bearer`, `api_key`, `oauth2_client_credentials`, `oauth2_device_code`)
with per-service resolution and `WWW-Authenticate` discovery. Secrets are referenced by env-var
name, never stored. Full guide: [`docs/auth.md`](docs/auth.md).

## Docs

- [`PLAN.md`](PLAN.md) — architecture, decisions, progress log (source of truth).
- [`docs/compatibility.md`](docs/compatibility.md) — empirical liveness/compliance/version matrix.
- [`docs/auth.md`](docs/auth.md) — auth flows + exact env vars.

## License

Apache-2.0.
