"""Validate v3 members, identities and wire constraints."""

import math
from typing import Any

import pytest
from aiorexense.gateway import (
    RexenseError,
    UnsupportedTaxonomyError,
    validate_gateway,
)
from aiorexense.models import (
    canonical_addr,
    endpoints_from_node,
    unit_of,
    validate_value,
)

from .conftest import INFO, MAC


@pytest.mark.parametrize("version", [None, 0, 2, True, "3", 3.5])
def test_reject_old_or_invalid_taxonomy(version: Any) -> None:
    """Do not silently route old or malformed versions through v3."""
    with pytest.raises(UnsupportedTaxonomyError):
        validate_gateway({**INFO, "taxonomy_version": version})


@pytest.mark.parametrize("version", [3, 4, 10])
def test_accept_additive_taxonomy(version: int) -> None:
    """Future additive models still use runtime cap_defs."""
    validate_gateway({**INFO, "taxonomy_version": version})


def test_identity_and_delta(node: dict[str, Any]) -> None:
    """Preserve sibling endpoint state and unrelated properties."""
    endpoints = endpoints_from_node(node, {})
    assert endpoints[0].addr == f"{MAC}:1"
    assert canonical_addr("aabbccddeeff0011:01") == "AABBCCDDEEFF0011:1"
    endpoints[0].apply_message({"properties": {"on": False}})
    assert endpoints[0].properties["brightness"] == 50
    assert endpoints[1].properties["contact_open"] is False
    endpoints[1].apply_message(
        {"events": [{"name": "contact_changed", "args": {"contact_open": True}}]}
    )
    assert endpoints[1].properties["contact_open"] is True


def test_runtime_definitions_are_authoritative(node: dict[str, Any]) -> None:
    """Do not synthesize actions omitted by the actual gateway."""
    endpoint = endpoints_from_node(
        node, {"domains": {"onoff": {"actions": {"toggle": {"args": {}}}}}}
    )[0]
    with pytest.raises(RexenseError, match="not supported"):
        endpoint.command({}, "toggle")


@pytest.mark.parametrize("value", [True, "12", 12.3, 101, math.nan])
def test_invalid_integer(value: Any) -> None:
    """Reject coercions, overflow and non-finite values."""
    with pytest.raises(RexenseError):
        validate_value(value, {"type": "int", "min": 0, "max": 100})


def test_step_and_readonly(node: dict[str, Any]) -> None:
    """Reject off-grid setpoints and writes to read-only properties."""
    with pytest.raises(RexenseError, match="step"):
        validate_value(21.2, {"type": "number", "min": 16, "max": 30, "step": 0.5})
    with pytest.raises(RexenseError, match="not writable"):
        endpoints_from_node(node, {})[1].command({"temperature": 22}, None)


@pytest.mark.parametrize("value", [None, 42, {}, []])
def test_invalid_unit_is_unknown(value: Any) -> None:
    assert unit_of({"unit": value}) is None


@pytest.mark.parametrize("value", [None, 42, {}, []])
def test_invalid_device_type_is_unknown(node: dict[str, Any], value: Any) -> None:
    node["endpoints"][0]["dev_type"] = value
    assert endpoints_from_node(node, {})[0].dev_type == "unknown_device"
