"""Shared async HTTP client with timeouts, bounded retries, and failure classification.

Every outbound call to a GA4GH service goes through here so that the wide variety of
real-world failures (DNS misses, private IPs, TLS mismatches, 401 challenges, HTML error
pages) become *structured* outcomes instead of exceptions that could crash a tool.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import Settings
from .errors import Liveness

# HTTP statuses worth retrying (transient).
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_REDIRECTS = 5


def origin(url: str | httpx.URL) -> tuple[str, str, int | None]:
    """(scheme, host, port) of a URL, parsed the way httpx will send it."""
    u = url if isinstance(url, httpx.URL) else httpx.URL(url)
    port = u.port or {"https": 443, "http": 80}.get(u.scheme)
    return u.scheme, u.host.lower().rstrip("."), port


class RedirectRefused(Exception):
    """A redirect would have re-sent a request body to a different origin."""


class BlockedAddress(Exception):
    """The destination resolves to a non-global address and private addresses are blocked."""


async def _ensure_public(url: httpx.URL) -> None:
    """Raise :class:`BlockedAddress` if ``url``'s host is, or resolves to, a non-global IP.

    An unresolvable name is left to the request itself, which then fails as a DNS error.
    """
    host = url.host
    try:
        addrs = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                host, url.port or 443, type=socket.SOCK_STREAM)
        except OSError:
            return
        addrs = {ipaddress.ip_address(i[4][0].split("%", 1)[0]) for i in infos}
    for a in addrs:
        if not a.is_global:
            raise BlockedAddress(
                f"refused request to non-public address {a} ({host}); set "
                f"GA4GH_MCP_BLOCK_PRIVATE_ADDRESSES=false to allow private destinations")


@dataclass
class HttpResult:
    url: str
    liveness: Liveness
    status: int | None = None
    latency_ms: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    json: Any = None
    text: str | None = None
    error: str | None = None

    @property
    def reachable(self) -> bool:
        return self.liveness in (
            Liveness.LIVE,
            Liveness.AUTH_REQUIRED,
            Liveness.HTTP_ERROR,
            Liveness.INVALID_RESPONSE,
        )


def _walk_causes(exc: BaseException):
    seen = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        yield cur
        cur = cur.__cause__ or cur.__context__


def classify_exception(exc: Exception) -> tuple[Liveness, str]:
    """Map an httpx/transport exception to a structured liveness + message."""
    # Timeouts first (httpx.TimeoutException covers connect/read/write/pool).
    if isinstance(exc, httpx.TimeoutException):
        return Liveness.TIMEOUT, f"timeout: {exc!s} ({type(exc).__name__})"
    # Inspect the cause chain for DNS / TLS roots.
    for cause in _walk_causes(exc):
        if isinstance(cause, ssl.SSLError):
            return Liveness.TLS_ERROR, f"tls error: {cause!s}"
        if isinstance(cause, socket.gaierror):
            return Liveness.UNREACHABLE_DNS, f"dns resolution failed: {cause!s}"
    msg = str(exc) or type(exc).__name__
    low = msg.lower()
    if "ssl" in low or "certificate" in low or "wrong_version_number" in low:
        return Liveness.TLS_ERROR, f"tls error: {msg}"
    if "nodename nor servname" in low or "name or service not known" in low or "getaddrinfo" in low:
        return Liveness.UNREACHABLE_DNS, f"dns resolution failed: {msg}"
    if isinstance(exc, httpx.ConnectError):
        return Liveness.CONNECTION_ERROR, f"connection error: {msg}"
    return Liveness.CONNECTION_ERROR, f"{type(exc).__name__}: {msg}"


class Ga4ghHttpClient:
    """Thin async wrapper around a single shared ``httpx.AsyncClient``."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None

    def _ensure(self) -> httpx.AsyncClient:
        if self._client is None:
            timeout = httpx.Timeout(
                connect=self._settings.connect_timeout,
                read=self._settings.read_timeout,
                write=self._settings.read_timeout,
                pool=self._settings.connect_timeout,
            )
            self._client = httpx.AsyncClient(
                timeout=timeout,
                verify=self._settings.verify_tls,
                # Redirects are followed by ``_send`` so credentials stay bound to the origin
                # they were resolved for (httpx itself strips only ``Authorization``).
                follow_redirects=False,
                headers={
                    "User-Agent": self._settings.user_agent,
                    "Accept": "application/json",
                },
                limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        data: dict[str, Any] | None = None,
    ) -> HttpResult:
        client = self._ensure()
        attempts = self._settings.max_retries + 1
        last: HttpResult | None = None
        for attempt in range(attempts):
            start = time.monotonic()
            try:
                resp = await self._send(client, client.build_request(
                    method.upper(), url, headers=headers, params=params,
                    json=json_body, data=data,
                ), caller_headers=headers)
            except (RedirectRefused, BlockedAddress) as exc:
                liveness = (Liveness.CONNECTION_ERROR if isinstance(exc, BlockedAddress)
                            else Liveness.HTTP_ERROR)
                return HttpResult(url=url, liveness=liveness, error=str(exc),
                                  latency_ms=int((time.monotonic() - start) * 1000))
            except Exception as exc:  # noqa: BLE001 - deliberately broad; classify below
                liveness, msg = classify_exception(exc)
                last = HttpResult(url=url, liveness=liveness, error=msg,
                                  latency_ms=int((time.monotonic() - start) * 1000))
                # DNS/TLS are deterministic — no point retrying.
                if liveness in (Liveness.UNREACHABLE_DNS, Liveness.TLS_ERROR):
                    return last
                if attempt < attempts - 1:
                    await asyncio.sleep(self._settings.retry_backoff * (2 ** attempt))
                    continue
                return last

            latency = int((time.monotonic() - start) * 1000)
            result = self._build_result(url, resp, latency)
            if resp.status_code in _RETRY_STATUS and attempt < attempts - 1:
                delay = self._retry_after(resp) or self._settings.retry_backoff * (2 ** attempt)
                last = result
                await asyncio.sleep(delay)
                continue
            return result
        assert last is not None
        return last

    async def _send(self, client: httpx.AsyncClient, request: httpx.Request, *,
                    caller_headers: dict[str, str] | None) -> httpx.Response:
        """Send ``request``, following redirects without carrying credentials across origins.

        Caller-supplied headers (auth headers from a provider, API keys) are dropped as soon
        as a hop leaves the original (scheme, host, port), and a redirect that would re-send a
        request body (307/308) to another origin is refused outright.
        """
        start_origin = origin(request.url)
        drop = {k.lower() for k in (caller_headers or {})}
        for _ in range(_MAX_REDIRECTS + 1):
            if self._settings.blocks_private_addresses():
                await _ensure_public(request.url)
            resp = await client.send(request)
            nxt = resp.next_request
            if nxt is None:
                return resp
            await resp.aclose()
            body = await nxt.aread()  # a 307/308 carries the original body; 301/302/303 do not
            if origin(nxt.url) != start_origin:
                if body:
                    raise RedirectRefused(
                        f"refused {resp.status_code} redirect that would re-send the request "
                        f"body to a different origin ({nxt.url.scheme}://{nxt.url.host})")
                for name in list(nxt.headers.keys()):
                    if name.lower() in drop or name.lower() in ("authorization", "cookie"):
                        del nxt.headers[name]
            request = nxt
        raise httpx.TooManyRedirects(f"exceeded {_MAX_REDIRECTS} redirects", request=request)

    def _build_result(self, url: str, resp: httpx.Response, latency: int) -> HttpResult:
        # Bound how much we buffer/parse from any single upstream.
        text = resp.text[: self._settings.max_response_bytes]
        parsed: Any = None
        try:
            parsed = resp.json()
        except Exception:  # noqa: BLE001 - non-JSON bodies are common and expected
            parsed = None

        status = resp.status_code
        if status in (401, 403):
            liveness = Liveness.AUTH_REQUIRED
        elif status >= 400:
            liveness = Liveness.HTTP_ERROR
        elif parsed is None:
            liveness = Liveness.INVALID_RESPONSE
        else:
            liveness = Liveness.LIVE
        return HttpResult(
            url=str(resp.url),
            liveness=liveness,
            status=status,
            latency_ms=latency,
            headers={k.lower(): v for k, v in resp.headers.items()},
            json=parsed,
            text=None if parsed is not None else text,
        )

    @staticmethod
    def _retry_after(resp: httpx.Response) -> float | None:
        ra = resp.headers.get("retry-after")
        if not ra:
            return None
        try:
            return min(float(ra), 10.0)  # cap to keep tools responsive
        except ValueError:
            return None

    async def get_json(self, url: str, *, headers: dict[str, str] | None = None,
                       params: dict[str, Any] | None = None) -> HttpResult:
        return await self.request("GET", url, headers=headers, params=params)
