"""DRS (Data Repository Service) type-aware helpers."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from ..auth.providers import OriginBoundAuth
from ..errors import ErrorType, ToolError
from ..http_client import Ga4ghHttpClient, HttpResult
from .base import ServiceTypePlugin, call_api, get_plugin, register

register(ServiceTypePlugin(
    product="DRS",
    artifacts={"drs"},
    api_base_path="/ga4gh/drs/v1",
    capabilities=["drs_get_object", "drs_get_access_url"],
    description="Data Repository Service — resolve data object metadata and access URLs.",
))
_PLUGIN = get_plugin("DRS")


def redact_access_url(access_url: Any) -> Any:
    """Strip bearer capabilities from a DRS AccessURL before it reaches the model.

    ``headers`` may carry an Authorization value for the storage host, and a pre-signed query
    string is itself a credential. Both are replaced with non-secret markers, matching the
    Harness SDK's DRS access redaction.
    """
    if not isinstance(access_url, dict):
        return access_url
    out = dict(access_url)
    if out.get("headers"):
        out["headers"] = {"redacted": True}
        out["access_headers_available"] = True
    url = out.get("url")
    if isinstance(url, str) and urlsplit(url).query:
        parts = urlsplit(url)
        out["url"] = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        out["access_url_query_redacted"] = True
    return out


def redact_object(obj: Any) -> Any:
    """Apply :func:`redact_access_url` to every inline access_url of a DRS object."""
    if not isinstance(obj, dict) or not isinstance(obj.get("access_methods"), list):
        return obj
    methods = [
        {**m, "access_url": redact_access_url(m["access_url"])}
        if isinstance(m, dict) and m.get("access_url") else m
        for m in obj["access_methods"]
    ]
    return {**obj, "access_methods": methods}


async def get_object(http: Ga4ghHttpClient, service: dict[str, Any], auth: OriginBoundAuth,
                     object_id: str) -> HttpResult:
    """Fetch a DRS object. Callers that return it to the model must pass it through
    :func:`redact_object`; ``get_access_url`` needs the unredacted access_id values."""
    return await call_api(http, service, auth, "GET", f"/objects/{quote(object_id, safe='')}",
                          plugin=_PLUGIN)


async def get_access_url(http: Ga4ghHttpClient, service: dict[str, Any], auth: OriginBoundAuth,
                         object_id: str, access_id: str | None = None) -> dict[str, Any]:
    """Return a concrete access URL for a DRS object.

    If ``access_id`` is omitted, fetch the object and pick the first access method,
    returning any inline ``access_url`` directly or dereferencing its ``access_id``.
    """
    if access_id is None:
        obj = await get_object(http, service, auth, object_id)
        if not isinstance(obj.json, dict):
            raise ToolError(ErrorType.UPSTREAM,
                            f"could not fetch DRS object ({obj.status or obj.liveness.value})",
                            detail=obj.error)
        methods = obj.json.get("access_methods") or []
        if not methods:
            raise ToolError(ErrorType.UPSTREAM, "DRS object has no access_methods",
                            detail={"object_id": object_id})
        m = methods[0]
        if m.get("access_url"):
            return {"access_url": redact_access_url(m["access_url"]),
                    "access_method": {**m, "access_url": redact_access_url(m["access_url"])},
                    "source": "inline access_url"}
        access_id = m.get("access_id")
        if not access_id:
            raise ToolError(ErrorType.UPSTREAM,
                            "first access_method has neither access_url nor access_id",
                            detail=m)
    res = await call_api(http, service, auth, "GET",
                         f"/objects/{quote(object_id, safe='')}/access/{quote(access_id, safe='')}",
                         plugin=_PLUGIN)
    if not isinstance(res.json, dict):
        raise ToolError(ErrorType.UPSTREAM,
                        f"could not fetch DRS access URL ({res.status or res.liveness.value})",
                        detail=res.error)
    return {"access_url": redact_access_url(res.json), "access_id": access_id,
            "source": "access endpoint"}
