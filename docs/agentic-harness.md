# Agentic Harness MCP binding

This server is a thin MCP projection over the local
`ga4gh-agentic-harness-python` SDK. It exposes the 13 canonical tool names in the
Agentic Harness MCP crosswalk and returns the SDK's Harness result envelope as
MCP structured content. The same server also registers the 21 registry and service tools in
`server.py`; see the README.

## Local development

The uv source in `pyproject.toml` installs the SDK from
`https://github.com/ga4gh/ga4gh-agentic-harness-python` (branch `main`, pinned in `uv.lock`).
To work against a local SDK checkout instead, run `uv pip install -e
../ga4gh-agentic-harness-python` after `uv sync`.

Install and inspect the Harness implementation locally:

```bash
uv sync --extra dev
uv run ga4gh-mcp --list-tools
uv run ga4gh-mcp
```

The default transport is stdio. For a local HTTP client, bind only to loopback:

```bash
uv run ga4gh-mcp --transport streamable-http \
  --host 127.0.0.1 --port 8000 --path /mcp
```

No cloud deployment is required. The Harness may call remote GA4GH services
from the Implementation Registry while the MCP process remains local.

To use a GA4GH Service Registry on localhost, opt in explicitly:

```bash
uv run ga4gh-mcp --transport streamable-http \
  --host 127.0.0.1 --port 8765 --path /mcp \
  --registry service-registry=http://127.0.0.1:18080/ga4gh/registry \
  --agentic-allow-private-hosts
```

`GA4GH_MCP_AGENTIC_ALLOWED_HOSTS` can further constrain upstream destinations.

With the local server running, exercise the MCP transport and a DRS lookup:

```bash
uv run python scripts/smoke_agentic_http.py \
  --service-id org.ga4gh.aws-opendata.drs \
  --object-id gnomad-exomes-v4.1-chr17-sites-vcf
```

## Safety boundary

The binding supplies no credential arguments or login tools. Downstream
credentials remain inside SDK credential providers. SDK HTTP defaults require
HTTPS and TLS verification and reject private, loopback, link-local, reserved,
credential-bearing, and cross-origin credential redirect targets.

The local MCP HTTP transport has no inbound OAuth boundary. Keep it on
`127.0.0.1`; do not expose it on a network interface. Remote hosting requires a
separate MCP authorization implementation and is outside this local pilot.

WES submission and cancellation are denied by default. For a trusted local client,
`GA4GH_MCP_AGENTIC_WRITE_SCOPES` may explicitly list `ga4gh:workflow:submit` and/or
`ga4gh:workflow:cancel`. On the unauthenticated loopback HTTP transport those scopes apply to
every connected local client, so do not enable them on a shared machine or network interface.
The server refuses to start with write scopes on a non-loopback streamable-http bind.

The profile schemas and SDK inputs are not yet identical: profile operations
use complete service references, while SDK v0.1 currently selects registered
services by `service_id`. This binding follows the SDK API and does not add a
second GA4GH HTTP implementation. Contract tests lock each tool to exactly one
SDK operation so the input surface can move with the SDK as that gap closes.
