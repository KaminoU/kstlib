"""Configuration tests for the local development infrastructure.

These tests parse the files under ``infra/`` (Docker Compose stack and
Keycloak realm export) and lock down known-good configuration invariants.
They do not require Docker: runtime behavior is validated separately.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

INFRA_DIR = Path(__file__).resolve().parents[2] / "infra"

pytestmark = pytest.mark.skipif(
    not INFRA_DIR.is_dir(),
    reason="infra/ directory not present (available in source checkouts only)",
)


def _load_compose() -> dict[str, Any]:
    """Load and parse the Docker Compose stack definition.

    Returns:
        Parsed content of infra/docker-compose.yml.
    """
    with (INFRA_DIR / "docker-compose.yml").open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    assert isinstance(data, dict)
    return data


def _load_realm() -> dict[str, Any]:
    """Load and parse the Keycloak realm export.

    Returns:
        Parsed content of infra/keycloak/realm-export.json.
    """
    with (INFRA_DIR / "keycloak" / "realm-export.json").open(encoding="utf-8") as handle:
        data = json.load(handle)
    assert isinstance(data, dict)
    return data


def test_keycloak_healthcheck_closes_connection() -> None:
    """Healthcheck HTTP request sends a Connection: close header.

    Without it Keycloak answers 200 but keeps the socket open (HTTP
    keep-alive), the check waits for an EOF that never comes and exceeds
    its timeout on every run: the container never turns healthy.
    """
    compose = _load_compose()
    test_cmd = compose["services"]["keycloak"]["healthcheck"]["test"]
    command = " ".join(test_cmd) if isinstance(test_cmd, list) else str(test_cmd)
    assert "Connection: close" in command


def test_keycloak_service_pins_hostname() -> None:
    """Keycloak service pins hostname to a stable value.

    The dev-mode embedded H2 database resolves the container hostname at
    boot; with the default random container id this resolution fails on
    some Docker/WSL2 stacks and the container exits before realm import.
    """
    compose = _load_compose()
    assert compose["services"]["keycloak"].get("hostname") == "keycloak"


def test_realm_clients_do_not_list_openid_as_client_scope() -> None:
    """No realm client lists openid in defaultClientScopes.

    The openid scope is the OIDC protocol marker sent in authorization
    requests, not a Keycloak client scope: referencing it in a client
    makes the realm import log a warning at boot.
    """
    realm = _load_realm()
    offenders = [client["clientId"] for client in realm["clients"] if "openid" in client.get("defaultClientScopes", [])]
    assert offenders == []
