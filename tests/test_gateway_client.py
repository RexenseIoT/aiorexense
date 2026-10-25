"""Exercise complete gateway behavior over a real loopback WebSocket."""

import asyncio
from collections.abc import AsyncIterator, Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from aiorexense import (
    DEFAULT_GATEWAY_PORT,
    DEFAULT_PORT,
    RexenseAuthenticationError,
    RexenseConnectionError,
    RexenseError,
    RexenseGateway,
    UnsupportedTaxonomyError,
    load_baseline,
)

from .conftest import INFO, MAC


@dataclass
class GatewayPeer:
    """An independent wire peer; command acceptance does not mutate its state."""

    node: dict[str, Any]
    requests: list[dict[str, Any]] = field(default_factory=list)
    sockets: list[web.WebSocketResponse] = field(default_factory=list)
    auth_code: int = 0
    capability_code: int = 0
    execution_code: int = 0
    repeated_cursor: bool = False
    inventory_event: bool = False
    completed_command: bool = False
    info: dict[str, Any] = field(default_factory=lambda: deepcopy(INFO))

    async def emit(self, event: str, data: dict[str, Any]) -> None:
        for socket in tuple(self.sockets):
            if not socket.closed:
                await socket.send_json({"event": event, "data": data})

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        self.sockets.append(socket)
        async for message in socket:
            payload = message.json()
            self.requests.append(payload)
            method = payload["method"]
            result: dict[str, Any] = {"code": 0}
            if method == "auth.api_key.use":
                result = {"code": self.auth_code}
            elif method == "gateway.info.get":
                result = self.info
            elif method == "device.list":
                snapshot = deepcopy(self.node)
                if not payload["params"]["include"].get("cap_def"):
                    for endpoint in snapshot["endpoints"]:
                        endpoint.pop("cap_defs", None)
                result = {
                    "code": 0,
                    "items": [snapshot],
                    "paging": {"has_more": self.repeated_cursor, "next_cursor": "same"},
                }
                if self.inventory_event:
                    await socket.send_json(
                        {
                            "event": "device.message",
                            "data": {
                                "addr": f"{MAC}:1",
                                "data": {"properties": {"on": False}},
                            },
                        }
                    )
            elif method == "device.logic.cap.get":
                endpoint = self.node["endpoints"][
                    int(payload["params"]["addr"].split(":")[1]) - 1
                ]
                result = {
                    "code": self.capability_code,
                    "addr": payload["params"]["addr"],
                    "state": "online",
                    **deepcopy(endpoint),
                }
            elif method == "device.logic.exec":
                result = {"code": self.execution_code, "status": "accepted"}
                if self.completed_command:
                    result["items"] = [
                        {
                            "addr": payload["params"]["addr"],
                            "code": self.execution_code,
                            "properties": {"on": False},
                            "state": "online",
                        }
                    ]
            await socket.send_json({"id": payload["id"], "result": result})
        return socket


@pytest.fixture
async def peer(node: dict[str, Any]) -> AsyncIterator[tuple[GatewayPeer, TestServer]]:
    device = GatewayPeer(deepcopy(node))
    app = web.Application()
    app.router.add_get("/ws", device.handle)
    async with TestServer(app) as server:
        yield device, server


async def until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_inventory_and_observed_light_state(
    peer: tuple[GatewayPeer, TestServer],
) -> None:
    device, server = peer
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(session, server.host, server.port, "key")
        await gateway.async_connect()
        try:
            assert gateway.connected
            assert gateway.unique_id == "gw-test-1"
            assert set(gateway.endpoints) == {f"{MAC}:1", f"{MAC}:2"}
            assert gateway.nodes[MAC]["model_id"] == "REX-TEST"
            await gateway.async_execute(f"{MAC}:1", {"on": False})
            assert gateway.endpoints[f"{MAC}:1"].properties["on"] is True
            commands = [
                p for p in device.requests if p["method"] == "device.logic.exec"
            ]
            assert len(commands) == 1
            assert commands[0]["params"]["addr"] == f"{MAC}:1"
            await device.emit(
                "device.message",
                {
                    "addr": f"{MAC}:1",
                    "data": {
                        "properties": {"on": False},
                        "signal": {"rssi": -43, "lqi": 0},
                    },
                },
            )
            await until(lambda: gateway.endpoints[f"{MAC}:1"].properties["on"] is False)
            assert gateway.nodes[MAC]["lqi"] == 0
            assert gateway.nodes[MAC]["rssi"] == -43
            assert gateway.nodes[MAC]["received_at"]
        finally:
            await gateway.async_stop()
        assert not session.closed


async def test_snapshot_replays_concurrent_push(
    peer: tuple[GatewayPeer, TestServer],
) -> None:
    device, server = peer
    device.inventory_event = True
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(session, server.host, server.port, baseline={})
        await gateway.async_connect()
        try:
            assert gateway.endpoints[f"{MAC}:1"].properties["on"] is False
        finally:
            await gateway.async_stop()


async def test_reconnect_without_replaying_commands(
    peer: tuple[GatewayPeer, TestServer],
) -> None:
    device, server = peer
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(
            session, server.host, server.port, "key", reconnect_delay=0.01
        )
        changes: list[bool] = []
        unsubscribe = gateway.subscribe(lambda: changes.append(gateway.connected))
        await gateway.async_start()
        try:
            await gateway.async_execute(f"{MAC}:1", {"on": False})
            await device.sockets[0].close()
            await until(lambda: len(device.sockets) == 2 and gateway.connected)
            assert False in changes
            assert changes[-1] is True
            assert (
                len([p for p in device.requests if p["method"] == "device.logic.exec"])
                == 1
            )
            assert gateway.unique_id == "gw-test-1"
            assert gateway.last_error is None
        finally:
            unsubscribe()
            await gateway.async_stop()


async def test_reconnect_stops_on_authentication_failure(
    peer: tuple[GatewayPeer, TestServer],
) -> None:
    device, server = peer
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(
            session, server.host, server.port, "key", reconnect_delay=0.01
        )
        await gateway.async_start()
        try:
            device.auth_code = 401
            await device.sockets[0].close()
            await until(
                lambda: isinstance(gateway.last_error, RexenseAuthenticationError)
            )
            assert not gateway.connected
            await asyncio.sleep(0.05)
            assert len(device.sockets) == 2
        finally:
            await gateway.async_stop()


async def test_wrong_gateway_is_not_ready(peer: tuple[GatewayPeer, TestServer]) -> None:
    _, server = peer
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(
            session, server.host, server.port, expected_gateway_id="other-gateway"
        )
        with pytest.raises(RexenseError, match="different gateway"):
            await gateway.async_connect()
        assert not gateway.connected
        assert gateway.unique_id == "other-gateway"
        await gateway.async_stop()


async def test_repeated_inventory_cursor_fails_atomically(
    peer: tuple[GatewayPeer, TestServer],
) -> None:
    device, server = peer
    device.repeated_cursor = True
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(session, server.host, server.port)
        with pytest.raises(RexenseError, match="cursor"):
            await gateway.async_connect()
        assert gateway.nodes == {}
        assert not gateway.connected
        await gateway.async_stop()


async def test_events_and_departure(peer: tuple[GatewayPeer, TestServer]) -> None:
    device, server = peer
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(session, server.host, server.port)
        events: list[tuple[str, dict[str, Any]]] = []
        remove_listener = gateway.subscribe_events(
            lambda addr, event: events.append((addr, event))
        )
        await gateway.async_connect()
        try:
            occurrence = {"name": "contact_changed", "args": {"contact_open": True}}
            await device.emit(
                "device.message", {"addr": f"{MAC}:2", "data": {"events": [occurrence]}}
            )
            await until(lambda: len(events) == 1)
            assert gateway.endpoints[f"{MAC}:2"].properties["contact_open"] is True
            await device.emit("device.changed", {"mac": MAC, "notify_status": "leaved"})
            await until(lambda: not gateway.nodes)
            assert not gateway.endpoints
            with pytest.raises(RexenseConnectionError):
                await gateway.async_execute(f"{MAC}:1", {"on": True})
        finally:
            remove_listener()
            await gateway.async_stop()


async def test_callback_failure_does_not_break_reader(
    peer: tuple[GatewayPeer, TestServer],
) -> None:
    device, server = peer
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(session, server.host, server.port)

        def broken() -> None:
            raise ValueError("consumer failed")

        unsubscribe = gateway.subscribe(broken)
        await gateway.async_connect()
        try:
            await device.emit(
                "device.message",
                {"addr": f"{MAC}:1", "data": {"properties": {"on": False}}},
            )
            await until(lambda: gateway.endpoints[f"{MAC}:1"].properties["on"] is False)
            assert gateway.connected
            assert (await gateway.client.async_request("gateway.info.get"))["code"] == 0
        finally:
            unsubscribe()
            await gateway.async_stop()


def test_legacy_port_and_packaged_model() -> None:
    assert DEFAULT_PORT == 80
    assert DEFAULT_GATEWAY_PORT == 8090
    assert "domains" in load_baseline()


async def test_command_rejection_is_not_retried(
    peer: tuple[GatewayPeer, TestServer],
) -> None:
    device, server = peer
    device.execution_code = 500
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(session, server.host, server.port)
        await gateway.async_connect()
        try:
            with pytest.raises(RexenseError):
                await gateway.async_execute(f"{MAC}:1", {"on": False})
            assert gateway.endpoints[f"{MAC}:1"].properties["on"] is True
            assert (
                len([p for p in device.requests if p["method"] == "device.logic.exec"])
                == 1
            )
        finally:
            await gateway.async_stop()


async def test_tl0001_unknown_switch_state_waits_for_report(
    peer: tuple[GatewayPeer, TestServer],
) -> None:
    """The real gateway may advertise on/off without an observed on value."""
    device, server = peer
    endpoint = device.node["endpoints"][0]
    endpoint.update(dev_type="switch", properties={}, domains=["onoff", "identify"])
    endpoint["cap_defs"]["domains"] = {
        name: definition
        for name, definition in endpoint["cap_defs"]["domains"].items()
        if name in endpoint["domains"]
    }
    device.node["endpoints"] = [endpoint]
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(session, server.host, server.port)
        await gateway.async_start()
        try:
            switch = gateway.endpoints[f"{MAC}:1"]
            assert switch.dev_type == "switch"
            assert switch.properties.get("on") is None
            await gateway.async_execute(switch.addr, {"on": True})
            assert switch.properties.get("on") is None
            await device.emit(
                "device.message",
                {"addr": switch.addr, "data": {"properties": {"on": True}}},
            )
            await until(lambda: switch.properties.get("on") is True)
        finally:
            await gateway.async_stop()


async def test_completed_command_supplies_observed_state(
    peer: tuple[GatewayPeer, TestServer],
) -> None:
    device, server = peer
    device.completed_command = True
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(session, server.host, server.port)
        await gateway.async_connect()
        try:
            await gateway.async_execute(f"{MAC}:1", {"on": False})
            assert gateway.endpoints[f"{MAC}:1"].properties["on"] is False
        finally:
            await gateway.async_stop()


async def test_missing_runtime_capabilities_prevent_control(
    peer: tuple[GatewayPeer, TestServer],
) -> None:
    device, server = peer
    device.capability_code = 503
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(session, server.host, server.port)
        await gateway.async_connect()
        try:
            assert gateway.connected
            assert not gateway.endpoints[f"{MAC}:1"].confirmed
            with pytest.raises(RexenseError):
                await gateway.async_execute(f"{MAC}:1", {"on": False})
            assert not any(p["method"] == "device.logic.exec" for p in device.requests)
            device.capability_code = 0
            await gateway.async_refresh_inventory()
            assert gateway.endpoints[f"{MAC}:1"].confirmed
        finally:
            await gateway.async_stop()


async def test_inventory_authentication_failure_closes_connection(
    peer: tuple[GatewayPeer, TestServer],
) -> None:
    device, server = peer
    device.capability_code = 401
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(session, server.host, server.port)
        with pytest.raises(RexenseAuthenticationError):
            await gateway.async_connect()
        assert not gateway.connected
        assert not gateway.client.connected
        assert not session.closed
        await gateway.async_stop()


async def test_changed_metadata_and_inventory_refresh(
    peer: tuple[GatewayPeer, TestServer],
) -> None:
    device, server = peer
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(session, server.host, server.port)
        await gateway.async_start()
        try:
            await device.emit(
                "device.changed", {"mac": MAC, "persist_status": "offline"}
            )
            await until(lambda: gateway.nodes[MAC]["state"] == "offline")
            assert all(e.state == "offline" for e in gateway.endpoints.values())
            device.node["model_id"] = "RENAMED"
            await device.emit(
                "device.changed", {"mac": MAC, "notify_status": "data_changed"}
            )
            await until(lambda: gateway.nodes[MAC]["model_id"] == "RENAMED")
            assert all(e.state == "online" for e in gateway.endpoints.values())
        finally:
            await gateway.async_stop()


async def test_unknown_endpoint_refreshes_inventory(
    peer: tuple[GatewayPeer, TestServer],
) -> None:
    device, server = peer
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(session, server.host, server.port)
        await gateway.async_start()
        try:
            new_endpoint = deepcopy(device.node["endpoints"][0])
            new_endpoint["endpoint"] = 3
            device.node["endpoints"].append(new_endpoint)
            await device.emit(
                "device.message", {"addr": f"{MAC}:3", "data": {"properties": {}}}
            )
            await until(lambda: f"{MAC}:3" in gateway.endpoints)
            assert gateway.endpoints[f"{MAC}:3"].confirmed
        finally:
            await gateway.async_stop()


async def test_refresh_preserves_local_receipt_timestamp(
    peer: tuple[GatewayPeer, TestServer],
) -> None:
    device, server = peer
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(session, server.host, server.port)
        await gateway.async_connect()
        try:
            await device.emit(
                "device.message",
                {"addr": f"{MAC}:1", "data": {"properties": {"on": False}}},
            )
            await until(lambda: "received_at" in gateway.nodes[MAC])
            received_at = gateway.nodes[MAC]["received_at"]
            device.node["received_at"] = "untrusted-gateway-field"
            await gateway.async_refresh_inventory()
            assert gateway.nodes[MAC]["received_at"] == received_at
        finally:
            await gateway.async_stop()


async def test_reconnect_stops_on_incompatible_taxonomy(
    peer: tuple[GatewayPeer, TestServer],
) -> None:
    device, server = peer
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(
            session, server.host, server.port, reconnect_delay=0.01
        )
        await gateway.async_start()
        try:
            device.info["taxonomy_version"] = 2
            await device.sockets[0].close()
            await until(
                lambda: isinstance(gateway.last_error, UnsupportedTaxonomyError)
            )
            await asyncio.sleep(0.05)
            assert len(device.sockets) == 2
            assert not gateway.connected
        finally:
            await gateway.async_stop()


async def test_reconnect_recovers_after_temporary_gateway_failure(
    peer: tuple[GatewayPeer, TestServer],
) -> None:
    device, server = peer
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(
            session, server.host, server.port, reconnect_delay=0.01
        )
        await gateway.async_start()
        await gateway.async_start()
        assert len(device.sockets) == 1
        try:
            device.info["code"] = 503
            await device.sockets[0].close()
            await until(lambda: len(device.sockets) >= 2)
            device.info["code"] = 0
            await until(lambda: len(device.sockets) >= 3 and gateway.connected)
        finally:
            await gateway.async_stop()
