"""Gateway fixtures independent of Home Assistant."""

from typing import Any

import pytest

MAC = "1122334455667788"
INFO = {
    "code": 0,
    "taxonomy_version": 3,
    "system": {"sn": "gw-test-1", "model": "RG5100", "sw_version": "4.0.0"},
}


def domain(
    properties: dict[str, Any] | None = None,
    actions: dict[str, Any] | None = None,
    events: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one complete DomainDef."""
    return {
        "properties": properties or {},
        "actions": actions or {},
        "events": events or {},
    }


@pytest.fixture
def node() -> dict[str, Any]:
    """A multi-endpoint physical device with explicit runtime definitions."""
    definitions = {
        "onoff": domain({"on": {"type": "bool", "access": "rw"}}),
        "brightness": domain(
            {
                "brightness": {
                    "type": "number",
                    "access": "rw",
                    "min": 0,
                    "max": 100,
                    "unit": "%",
                }
            }
        ),
        "color_temp": domain(
            {
                "color_temperature": {
                    "type": "number",
                    "access": "rw",
                    "min": 2000,
                    "max": 6500,
                    "unit": "K",
                }
            }
        ),
        "color_hs": domain(
            {
                "hue": {"type": "int", "access": "rw", "min": 0, "max": 254},
                "saturation": {"type": "number", "access": "rw", "min": 0, "max": 100},
            }
        ),
        "identify": domain(
            actions={
                "identify": {
                    "args": {
                        "identify_time": {
                            "type": "int",
                            "min": 0,
                            "max": 65535,
                            "default": 5,
                        }
                    }
                }
            }
        ),
    }
    contact = {
        "contact": domain(
            {"contact_open": {"type": "bool", "access": "r"}},
            events={"contact_changed": {"args": {"contact_open": {"type": "bool"}}}},
        ),
        "temperature": domain(
            {"temperature": {"type": "number", "access": "r", "unit": "C"}}
        ),
        "battery": domain(
            {"battery_level": {"type": "number", "access": "r", "unit": "%"}}
        ),
        "button_event": domain(
            events={
                "button_event": {
                    "args": {
                        "button": {"type": "int"},
                        "gesture": {"type": "enum", "enum": ["single", "double"]},
                    }
                }
            }
        ),
    }
    return {
        "mac": MAC,
        "state": "online",
        "model_id": "REX-TEST",
        "protocol": "zigbee",
        "endpoints": [
            {
                "endpoint": 1,
                "lalias": "Desk",
                "larea": "Office",
                "dev_type": "light",
                "domains": list(definitions),
                "properties": {
                    "on": True,
                    "brightness": 50,
                    "color_temperature": 3000,
                    "hue": 127,
                    "saturation": 70,
                },
                "cap_defs": {"domains": definitions},
            },
            {
                "endpoint": 2,
                "lalias": "Window",
                "dev_type": "contact_sensor",
                "domains": list(contact),
                "properties": {
                    "contact_open": False,
                    "temperature": 21.5,
                    "battery_level": 80,
                },
                "cap_defs": {"domains": contact},
            },
        ],
    }
