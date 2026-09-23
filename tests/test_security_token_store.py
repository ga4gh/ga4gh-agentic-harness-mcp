"""The device-code token cache is created private, not made private after the fact."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from ga4gh_mcp.auth.providers import OAuth2DeviceCodeAuth
from ga4gh_mcp.config import load_settings
from ga4gh_mcp.http_client import Ga4ghHttpClient


async def test_token_file_is_created_0600_without_relying_on_chmod(tmp_path, monkeypatch):
    # With chmod neutralised, whatever mode the file is *created* with is what an attacker
    # sharing the machine gets to read between write and chmod.
    monkeypatch.setattr(Path, "chmod", lambda self, mode: None)
    monkeypatch.setattr(os, "chmod", lambda *a, **k: None)
    old = os.umask(0o022)
    try:
        store = tmp_path / "tokens" / "svc.json"
        http = Ga4ghHttpClient(load_settings())
        p = OAuth2DeviceCodeAuth(http, device_authorization_url="https://idp.test/d",
                                 token_url="https://idp.test/t", client_id="c",
                                 token_store=str(store))
        p._store_tokens({"access_token": "AT", "refresh_token": "RT", "expires_in": 60})
        await http.aclose()
    finally:
        os.umask(old)
    assert stat.S_IMODE(store.stat().st_mode) & 0o077 == 0
    assert stat.S_IMODE(store.parent.stat().st_mode) & 0o077 == 0
