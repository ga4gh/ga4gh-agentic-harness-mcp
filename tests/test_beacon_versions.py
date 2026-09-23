"""Beacon info location by declared version, and queryShape passthrough from federated records."""

from __future__ import annotations

from ga4gh_mcp.registry import normalize_service_info
from ga4gh_mcp.services.beacon import info_url


def _record(version, url="https://b.test/api", **extra):
    return {"url": url, "standardVersion": {"ga4ghProduct": "Beacon", "version": version},
            **extra}


def test_v2_uses_registered_service_info_url():
    assert info_url(_record("2.0.0", serviceInfoUrl="https://b.test/api/info")) == \
        "https://b.test/api/info"


def test_v2_federated_record_uses_info_not_synthesized_service_info():
    record = _record("v2.0.0", serviceInfoUrl="https://b.test/api/service-info",
                     source="federated:http://127.0.0.1:18091/ga4gh/registry")
    assert info_url(record) == "https://b.test/api/info"


def test_v1_and_v0_4_use_base_url():
    assert info_url(_record("1.0.0")) == "https://b.test/api"
    assert info_url(_record("0.4")) == "https://b.test/api"


def test_query_shape_info_path_or_none():
    assert info_url(_record("0.2", queryShape={"infoPath": "/info"})) == "https://b.test/api/info"
    assert info_url(_record("0.0.0", queryShape={})) is None
    assert info_url(_record("0.2", queryShape={"infoPath": "/../admin"})) is None
    assert info_url(_record("0.2", queryShape={"infoPath": "//evil.test"})) is None


def test_federated_record_keeps_query_shape():
    shape = {"path": "/query", "parameters": {"position": "{start}"}}
    normalized = normalize_service_info(
        {"id": "b", "url": "https://b.test", "type": {"artifact": "beacon", "version": "0.2.0"},
         "queryShape": shape}, source="http://127.0.0.1:18091/ga4gh/registry")
    assert normalized["queryShape"] == shape
    assert "queryShape" not in normalize_service_info(
        {"id": "c", "url": "https://c.test", "type": {"artifact": "beacon"}}, source="x")
