"""Exercise request correlation and failures using a real local WebSocket."""

import asyncio
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import Mock

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from aiorexense.gateway import (
    RexenseAuthenticationError,
    RexenseClient,
    RexenseConnectionError,
    UnsupportedTaxonomyError,
)

from .conftest import INFO


@dataclass
class Gateway:
    """A small protocol peer, independent of the client implementation."""

    requests: list[dict[str, Any]] = field(default_factory=list)
    sockets: list[web.WebSocketResponse] = field(default_factory=list)
    held: list[dict[str, Any]] = field(default_factory=list)
    received: asyncio.Event = field(default_factory=asyncio.Event)
    auth_code: int = 0
    auth_required: bool = False
    version: int = 3

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        """Implement enough of the actual protocol for transport tests."""
        socket = web.WebSocketResponse()
        await socket.prepare(request)
        self.sockets.append(socket)
        authenticated = False
        async for message in socket:
            payload = message.json()
            self.requests.append(payload)
            method = payload["method"]
            if method == "held":
                self.held.append(payload)
                self.received.set()
                continue
            result = {"code": 0}
            if method == "auth.api_key.use":
                result = {"code": self.auth_code, "message": "do not log credentials"}
                authenticated = self.auth_code == 0
            elif self.auth_required and not authenticated:
                result = {"code": 401}
            elif method == "gateway.info.get":
                result = {**INFO, "taxonomy_version": self.version}
            elif method == "device.list":
                await socket.send_json(
                    {
                        "id": payload["id"],
                        "event": "device.message",
                        "data": {
                            "addr": "1122334455667788:1",
                            "data": {"properties": {"on": False}},
                        },
                    }
                )
                result = {"code": 0, "items": []}
            await socket.send_json({"id": payload["id"], "result": result})
        return socket


@pytest.fixture
async def gateway() -> tuple[Gateway, TestServer]:
    """Start a loopback endpoint without requiring Home Assistant fixtures."""
    peer = Gateway()
    app = web.Application()
    app.router.add_get("/ws", peer.handle)
    async with TestServer(app) as server:
        yield peer, server


async def test_authentication_and_id_bearing_event(
    gateway: tuple[Gateway, TestServer],
) -> None:
    """Events containing request ids cannot consume their pending responses."""
    peer, server = gateway
    events = Mock()
    async with aiohttp.ClientSession() as session:
        client = RexenseClient(
            session, server.host, server.port, "key", event_callback=events
        )
        assert await client.async_connect() == INFO
        assert await client.async_request("device.list") == {"code": 0, "items": []}
        events.assert_called_once()
        assert events.call_args.args[0] == "device.message"
        assert peer.requests[0] == {
            "id": "1",
            "method": "auth.api_key.use",
            "params": {"api_key": "key"},
        }
        assert [request["method"] for request in peer.requests] == [
            "auth.api_key.use",
            "gateway.info.get",
            "device.list",
        ]
        await client.async_close()
        assert not session.closed


async def test_out_of_order_responses(gateway: tuple[Gateway, TestServer]) -> None:
    """Associate concurrent responses by id, even when delivered in reverse order."""
    peer, server = gateway
    async with aiohttp.ClientSession() as session:
        client = RexenseClient(session, server.host, server.port, "key")
        await client.async_connect()
        first = asyncio.create_task(client.async_request("held", {"n": 1}))
        await peer.received.wait()
        peer.received.clear()
        second = asyncio.create_task(client.async_request("held", {"n": 2}))
        await peer.received.wait()
        for request in reversed(peer.held):
            await peer.sockets[0].send_json(
                {
                    "id": request["id"],
                    "result": {"code": 0, "n": request["params"]["n"]},
                }
            )
        assert await first == {"code": 0, "n": 1}
        assert await second == {"code": 0, "n": 2}
        await client.async_close()


async def test_connect_without_api_key(gateway: tuple[Gateway, TestServer]) -> None:
    """An open gateway is queried without sending an API-key login request."""
    peer, server = gateway
    async with aiohttp.ClientSession() as session:
        client = RexenseClient(session, server.host, server.port, "")
        assert await client.async_connect() == INFO
        assert [request["method"] for request in peer.requests] == ["gateway.info.get"]
        await client.async_close()


async def test_missing_key_on_protected_gateway(
    gateway: tuple[Gateway, TestServer],
) -> None:
    """Leaving the key blank cannot bypass authentication on a protected gateway."""
    peer, server = gateway
    peer.auth_required = True
    async with aiohttp.ClientSession() as session:
        client = RexenseClient(session, server.host, server.port, "")
        with pytest.raises(RexenseAuthenticationError):
            await client.async_connect()
        assert not client.connected


@pytest.mark.parametrize(
    ("auth_code", "version", "exception"),
    [
        (401, 3, RexenseAuthenticationError),
        (0, 2, UnsupportedTaxonomyError),
    ],
)
async def test_handshake_rejected(
    gateway: tuple[Gateway, TestServer],
    auth_code: int,
    version: int,
    exception: type[Exception],
) -> None:
    """An invalid key or old taxonomy closes the failed connection."""
    peer, server = gateway
    peer.auth_code, peer.version = auth_code, version
    async with aiohttp.ClientSession() as session:
        client = RexenseClient(session, server.host, server.port, "key")
        with pytest.raises(exception):
            await client.async_connect()
        assert not client.connected


async def test_disconnect_fails_pending_request(
    gateway: tuple[Gateway, TestServer],
) -> None:
    """A lost connection releases waiters instead of leaving them to time out."""
    peer, server = gateway
    async with aiohttp.ClientSession() as session:
        client = RexenseClient(session, server.host, server.port, "key")
        await client.async_connect()
        request = asyncio.create_task(client.async_request("held"))
        await peer.received.wait()
        await peer.sockets[0].close()
        with pytest.raises(RexenseConnectionError):
            await request
        await client.async_wait_disconnected()
        await client.async_close()


async def test_timeout_does_not_retry(gateway: tuple[Gateway, TestServer]) -> None:
    """A timed-out action is never replayed automatically."""
    peer, server = gateway
    async with aiohttp.ClientSession() as session:
        client = RexenseClient(session, server.host, server.port, "key")
        await client.async_connect()
        client.request_timeout = 0.02
        with pytest.raises(RexenseConnectionError):
            await client.async_request("held")
        assert len(peer.held) == 1
        assert client._pending == {}
        await client.async_close()
