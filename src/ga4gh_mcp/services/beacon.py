"""Beacon type-aware helper for every Beacon version: pre-1.0, v1 and v2.

Where a Beacon describes itself depends on its version, which the registry record declares; the
service is never probed to find out. v2 publishes a framework 'info' document at the registered
``serviceInfoUrl`` (or ``{url}/info``); v1, and the 0.3 and 0.4 APIs it grew from, answer with
their Beacon object at the base URL. Pre-1.0 Beacons whose record declares a ``queryShape`` have
no standard info endpoint: the shape's optional ``infoPath`` names one (UCSC's 0.2 beacons
answer at ``/info``), and without it the declared record is the description.
``analyze_service_info`` maps whatever comes back best-effort.
"""

from __future__ import annotations

import re
from typing import Any

from ..auth.providers import OriginBoundAuth
from ..errors import Liveness
from ..http_client import Ga4ghHttpClient, HttpResult
from .base import ServiceTypePlugin, register

register(ServiceTypePlugin(
    product="Beacon",
    artifacts={"beacon"},
    api_base_path="",
    capabilities=["beacon_info"],
    description="GA4GH Beacon (pre-1.0, v1, v2) — genomic variant discovery; info document.",
))

_VERSION = re.compile(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.\d+)*\s*$", re.IGNORECASE)
_SAFE_PATH = re.compile(r"^(/[A-Za-z0-9._~!$&'()*+,;=:@-]+)*/?$")


def _version(service: dict[str, Any]) -> tuple[int, int] | None:
    declared = (service.get("standardVersion") or {}).get("version")
    match = _VERSION.match(str(declared)) if declared else None
    return (int(match.group(1)), int(match.group(2) or 0)) if match else None


def info_url(service: dict[str, Any]) -> str | None:
    """Where this Beacon describes itself, or None when only its registry record does."""
    base = (service.get("url") or "").rstrip("/")
    shape = service.get("queryShape")
    if isinstance(shape, dict):
        path = shape.get("infoPath")
        # The path comes from the registry record and may extend the base URL, never leave it.
        if not isinstance(path, str) or not _SAFE_PATH.match(path) or any(
                part in {".", ".."} for part in path.split("/")):
            return None
        return base + path
    version = _version(service)
    if version and (version[0] == 1 or (version[0] == 0 and version[1] >= 3)):
        return base or None
    if service.get("serviceInfoUrl") and not str(service.get("source", "")).startswith(
            "federated:"):
        return service["serviceInfoUrl"]
    return f"{base}/info" if base else None


async def beacon_info(http: Ga4ghHttpClient, service: dict[str, Any],
                      auth: OriginBoundAuth) -> HttpResult:
    url = info_url(service)
    if url is None:
        # Nothing to fetch: the declared record, queryShape included, is what is known.
        declared = {key: service.get(key) for key in (
            "id", "name", "description", "url", "standardVersion", "queryShape")}
        return HttpResult(url=service.get("url") or "", liveness=Liveness.LIVE, status=200,
                          json={"declared": declared,
                                "note": "This pre-1.0 Beacon has no info endpoint; its "
                                        "registry record declares how to query it."})
    headers = await auth.headers_for(url)
    return await http.request("GET", url, headers=headers or None)
