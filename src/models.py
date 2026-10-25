"""Taxonomy v3 endpoint identities, capability definitions and validation."""

import math
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .gateway import RexenseError


def canonical_addr(addr: str) -> str:
    """Normalize MAC case while preserving the endpoint identifier."""
    mac, separator, endpoint = addr.rpartition(":")
    if not separator or not mac or not endpoint.isdecimal():
        raise RexenseError("Invalid logical device address")
    return f"{mac.upper()}:{int(endpoint)}"


def unit_of(definition: dict[str, Any]) -> str | None:
    """Translate only unit spellings, never scale normalized wire values."""
    unit = definition.get("unit")
    if not isinstance(unit, str):
        return None
    return {"C": "°C", "F": "°F", "%open": "%", "lx": "lx"}.get(unit, unit)


def validate_value(value: Any, definition: dict[str, Any]) -> None:
    """Validate a typed property or action argument before sending it."""
    kind = definition.get("type", "")
    valid = {
        "bool": isinstance(value, bool),
        "int": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "enum": value in definition.get("enum", []),
        "string": isinstance(value, str),
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
    }.get(kind, False)
    if not valid:
        raise RexenseError(f"Invalid value for {kind} capability")
    if kind in ("int", "number"):
        if not math.isfinite(value):
            raise RexenseError("Capability value must be finite")
        if value < definition.get("min", -math.inf) or value > definition.get(
            "max", math.inf
        ):
            raise RexenseError("Capability value is outside its permitted range")
        if step := definition.get("step"):
            steps = (value - definition.get("min", 0)) / step
            if not math.isclose(steps, round(steps), abs_tol=1e-6):
                raise RexenseError("Capability value does not match its step")
    if kind == "array":
        if (
            not definition.get("min_items", 0)
            <= len(value)
            <= definition.get("max_items", math.inf)
        ):
            raise RexenseError("Capability array has an invalid length")
        for item in value:
            validate_value(item, definition.get("items", {}))


def quantize_value(value: float, definition: dict[str, Any]) -> float | int:
    """Quantize converted UI values to a property's declared numeric grid."""
    minimum = definition.get("min", 0)
    maximum = definition.get("max", math.inf)
    step = definition.get("step", 1 if definition.get("type") == "int" else 0)
    if step:
        value = minimum + round((value - minimum) / step) * step
    value = min(maximum, max(minimum, value))
    return int(value) if definition.get("type") == "int" else round(value, 6)


@dataclass
class Endpoint:
    """One logical endpoint attached to a physical node."""

    addr: str
    node: dict[str, Any]
    metadata: dict[str, Any]
    definitions: dict[str, Any]
    properties: dict[str, Any] = field(default_factory=dict)
    state: str = "unknown"
    confirmed: bool = False
    color_mode: str | None = None

    @property
    def mac(self) -> str:
        """Return the physical identity."""
        return self.addr.rsplit(":", 1)[0]

    @property
    def dev_type(self) -> str:
        """Return the gateway's declared device type."""
        value = self.metadata.get("dev_type")
        return value if isinstance(value, str) else "unknown_device"

    def members(self, kind: str) -> dict[str, dict[str, Any]]:
        """Flatten members, rejecting ambiguous ownership across domains."""
        result: dict[str, dict[str, Any]] = {}
        for domain in self.definitions.values():
            for name, definition in domain.get(kind, {}).items():
                if name in result:
                    raise RexenseError(f"Duplicate capability member: {name}")
                result[name] = definition
        return result

    def writable(self, name: str) -> bool:
        """Return whether a property is declared read/write."""
        return self.members("properties").get(name, {}).get("access") == "rw"

    def command(self, args: dict[str, Any], action: str | None) -> dict[str, Any]:
        """Build a validated command from confirmed gateway capabilities."""
        if self.state != "online" or not self.confirmed:
            raise RexenseError("Device capabilities are unavailable")
        if action is None:
            definitions = self.members("properties")
            for name, value in args.items():
                if not self.writable(name):
                    raise RexenseError(f"Property is not writable: {name}")
                validate_value(value, definitions[name])
            return {"cmd": "set_state", "args": args}
        definition = self.members("actions").get(action)
        if definition is None:
            raise RexenseError(f"Action is not supported: {action}")
        arguments = definition.get("args", {})
        if args.keys() - arguments.keys():
            raise RexenseError("Action contains undeclared arguments")
        for name, spec in arguments.items():
            if name in args:
                validate_value(args[name], spec)
            elif spec.get("required", True):
                raise RexenseError(f"Missing action argument: {name}")
        if action in ("gqb_tunneled_request", "gqb_tunneled_report_response") and len(
            args.get("data", [])
        ) > (507 if "transaction_id" in args else 508):
            raise RexenseError("GQB data exceeds the gateway encoder limit")
        return {"cmd": "invoke", "action": action, "args": args}

    def update_capabilities(self, result: dict[str, Any]) -> None:
        """Use precise runtime definitions as the authority for control."""
        definitions = result.get("cap_defs", {}).get("domains")
        if not isinstance(definitions, dict):
            raise RexenseError("Gateway omitted logical-device capability definitions")
        self.definitions = deepcopy(definitions)
        self.confirmed = True
        self.metadata.update(
            {k: result[k] for k in ("lalias", "larea", "dev_type") if k in result}
        )
        self.state = result.get("state", self.state)
        self.properties.update(result.get("properties", {}))
        for kind in ("properties", "actions", "events"):
            self.members(kind)

    def update_properties(self, properties: dict[str, Any]) -> None:
        """Track the last reported color branch because v3 has no color_mode."""
        if "color_temperature" in properties:
            self.color_mode = "color_temp"
        elif "hue" in properties or "saturation" in properties:
            self.color_mode = "hs"
        self.properties.update(properties)

    def apply_message(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Merge deltas and project event arguments within their owning domain."""
        events = payload.get("events", [])
        valid_events = []
        for event in events if isinstance(events, list) else []:
            if not isinstance(event, dict) or not isinstance(
                event.get("args", {}), dict
            ):
                continue
            for domain in self.definitions.values():
                if event.get("name") not in domain.get("events", {}):
                    continue
                valid_events.append(event)
                # Other instances do not update the endpoint's main state.
                if event.get("instance", "main") != "main":
                    break
                arguments = domain["events"][event["name"]].get("args", {})
                self.properties.update(
                    {
                        key: value
                        for key, value in event.get("args", {}).items()
                        if key in arguments and key in domain.get("properties", {})
                    }
                )
                break
        if isinstance(payload.get("properties"), dict):
            self.update_properties(payload["properties"])
        if isinstance(payload.get("signal"), dict):
            self.node.update(payload["signal"])
        self.state = "online"
        return valid_events


def endpoints_from_node(
    node: dict[str, Any], baseline: dict[str, Any]
) -> list[Endpoint]:
    """Build canonical endpoints with the same local v3 baseline as webUI."""
    mac = str(node["mac"]).upper()
    mappings: list[dict[str, Any]] = next(
        (
            item.get("endpoints", [])
            for item in baseline.get("model_mappings", [])
            if item.get("model_id") == node.get("model_id")
        ),
        [],
    )
    result = []
    for item in node.get("endpoints", []):
        metadata = deepcopy(item)
        addr = canonical_addr(item.get("addr") or f"{mac}:{item['endpoint']}")
        mapping: dict[str, Any] = next(
            (m for m in mappings if str(m["endpoint"]) == addr.rsplit(":", 1)[1]),
            {},
        )
        metadata.setdefault("dev_type", mapping.get("dev_type", "unknown_device"))
        domains = item.get("domains", mapping.get("domains", []))
        definitions = {
            name: deepcopy(baseline["domains"][name])
            for name in domains
            if name in baseline.get("domains", {})
        }
        endpoint = Endpoint(
            addr=addr,
            node={k: v for k, v in node.items() if k != "endpoints"},
            metadata=metadata,
            definitions=definitions,
            properties=dict(item.get("properties", {})),
            state=node.get("state", "unknown"),
        )
        if "cap_defs" in item:
            endpoint.update_capabilities(item)
        result.append(endpoint)
    return result
