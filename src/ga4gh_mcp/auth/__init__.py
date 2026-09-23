"""Pluggable authentication for outbound GA4GH service calls."""

from .base import AuthProvider, AuthSpec
from .providers import (
    ApiKeyAuth,
    NoAuth,
    OAuth2ClientCredentialsAuth,
    OAuth2DeviceCodeAuth,
    OriginBoundAuth,
    StaticBearerAuth,
)
from .resolver import AuthResolver, parse_www_authenticate

__all__ = [
    "AuthProvider",
    "AuthSpec",
    "NoAuth",
    "StaticBearerAuth",
    "ApiKeyAuth",
    "OAuth2ClientCredentialsAuth",
    "OAuth2DeviceCodeAuth",
    "OriginBoundAuth",
    "AuthResolver",
    "parse_www_authenticate",
]
