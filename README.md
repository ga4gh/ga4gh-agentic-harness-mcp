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

# GA4GH Agentic Harness tools backed by the local Python SDK (default surface)
ga4gh-mcp

# registry, DRS, Data Connect, TRS, TES and Beacon tools (21 tools)
ga4gh-mcp --surface legacy

# local streamable HTTP
ga4gh-mcp --transport streamable-http \
  --host 127.0.0.1 --port 8000 --path /mcp
```

All options are also env vars (prefix `GA4GH_MCP_`):
`GA4GH_MCP_SURFACE`, `GA4GH_MCP_TRANSPORT`, `GA4GH_MCP_HOST`,
`GA4GH_MCP_PORT`, `GA4GH_MCP_HTTP_PATH`, `GA4GH_MCP_REGISTRY_BASE_URL`, timeouts, cache TTLs,
`GA4GH_MCP_AUTH_CONFIG`, `GA4GH_MCP_BEARER_TOKEN`, `GA4GH_MCP_BEARER_HOSTS`. See `.env.example`.

## Harness tools

The server exposes the 13 canonical tools defined by the Agentic Harness MCP
crosswalk. These tools delegate to the protocol-neutral SDK and return
structured Harness envelopes. See [`docs/agentic-harness.md`](docs/agentic-harness.md).

Every tool returns the Harness result envelope.

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
