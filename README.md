# ga4gh-agentic-harness-mcp

A **universal [MCP](https://modelcontextprotocol.io) server for GA4GH services.** It provides a
canonical Agentic Harness binding alongside the original registry-oriented tool surface. v1 makes
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
git clone https://github.com/mfiume/ga4gh-agentic-harness-mcp && cd ga4gh-agentic-harness-mcp
uv venv && . .venv/bin/activate      # or: python -m venv .venv && . .venv/bin/activate
uv pip install -e ".[dev]"           # or: pip install -e ".[dev]"
```

For local Agentic Harness development, keep
`ga4gh-agentic-harness-python` beside this checkout and use `uv sync --extra dev`.
The editable SDK path is declared in `pyproject.toml`.

Run directly with no clone via uvx:

```bash
uvx --from git+https://github.com/mfiume/ga4gh-agentic-harness-mcp ga4gh-mcp --list-tools
```

## Run

```bash
# stdio (default) — for Claude Desktop / Claude Code
ga4gh-mcp                      # or: python -m ga4gh_mcp

# canonical Agentic Harness tools backed by the local Python SDK
ga4gh-mcp --surface agentic

# local streamable HTTP
ga4gh-mcp --surface agentic --transport streamable-http \
  --host 127.0.0.1 --port 8000 --path /mcp
```

All options are also env vars (prefix `GA4GH_MCP_`): `GA4GH_MCP_SURFACE`,
`GA4GH_MCP_TRANSPORT`, `GA4GH_MCP_HOST`,
`GA4GH_MCP_PORT`, `GA4GH_MCP_HTTP_PATH`, `GA4GH_MCP_REGISTRY_BASE_URL`, timeouts, cache TTLs,
`GA4GH_MCP_AUTH_CONFIG`, `GA4GH_MCP_BEARER_TOKEN`, `GA4GH_MCP_BEARER_HOSTS`. See `.env.example`.

## Tool surface

Use `--surface agentic` for the 13 canonical tools defined by the Agentic Harness
MCP crosswalk. These tools delegate to the protocol-neutral SDK and return
structured Harness envelopes. See [`docs/agentic-harness.md`](docs/agentic-harness.md).

The default `--surface legacy` preserves the existing tools:

| Tool | What it does |
|---|---|
| `list_services` | List registry services with filters (product, org, version, environment, type, free-text). |
| `get_service` | Full registry entry by UUID or implementationId. |
| `search_services` | Free-text search across services + deployments. |
| `list_service_types` | Type counts + GA4GH standards catalog + which types have type-aware helpers. |
| `list_standards` | GA4GH standards + versions. |
| `list_organisations` | Registered organisations. |
| `check_service_health` | Structured liveness + compliance/version report for a service. |
| `get_service_info` | Fetch + normalize a `/service-info` (by id or raw url); tolerant of 5 shapes. |
| `call_service_endpoint` | Generic authenticated call to any registered service via its base URL. |
| `drs_get_object`, `drs_get_access_url` | DRS object metadata + access-URL resolution. |
| `trs_list_tools`, `trs_get_tool` | TRS workflow/tool listing + detail. |
| `tes_list_tasks`, `tes_get_task` | TES task listing + detail. |
| `beacon_info` | Beacon v2 framework info document. |
| `auth_status`, `auth_device_login` | Inspect auth config; start OAuth2 device-code flow. |

Every tool returns `{"ok": bool, "data"|"error": ..., "warnings": [...]}`.

## Verify from the CLI (no UI needed)

```bash
. .venv/bin/activate

# 1) Tools register + schemas load (uses the MCP SDK's own client in-process)
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
