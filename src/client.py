"""Gateway inventory, capability models, push updates and reconnection."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from contextlib import suppress
from copy import deepcopy
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any, cast

import aiohttp

from .gateway import (
    DEFAULT_GATEWAY_PORT,
    RexenseAuthenticationError,
    RexenseClient,
    RexenseCommandError,
    RexenseConnectionError,
    RexenseError,
    UnsupportedTaxonomyError,
    check_result,
    gateway_identity,
)
from .models import Endpoint, canonical_addr, endpoints_from_node

_LOGGER = logging.getLogger(__name__)


def load_baseline() -> dict[str, Any]:
    """Read the packaged model; async callers should offload this file access."""
    return cast(
        dict[str, Any],
        json.loads(files("aiorexense").joinpath("thing_model_v3.json").read_text()),
    )


class RexenseGateway:
    """Maintain one physical gateway without depending on an application framework."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int = DEFAULT_GATEWAY_PORT,
        api_key: str = "",
        *,
        use_ssl: bool = False,
        verify_ssl: bool = True,
        request_timeout: float = 15,
        reconnect_delay: float = 5,
        expected_gateway_id: str | None = None,
        baseline: dict[str, Any] | None = None,
    ) -> None:
        """Use a caller-owned session and start background work only on request."""
        if reconnect_delay <= 0:
            raise ValueError("reconnect_delay must be positive")
        self.client = RexenseClient(
            session,
            host,
            port,
            api_key,
            use_ssl=use_ssl,
            verify_ssl=verify_ssl,
            request_timeout=request_timeout,
            event_callback=self._handle_event,
        )
        self.gateway: dict[str, Any] = {}
        self.nodes: dict[str, dict[str, Any]] = {}
        self.endpoints: dict[str, Endpoint] = {}
        self.last_error: RexenseError | None = None
        self.inventory_lock = asyncio.Lock()
        self._baseline = baseline
        self._identity = expected_gateway_id
        self._reconnect_delay = reconnect_delay
        self._ready = False
        self._stopping = False
        self._buffer: list[tuple[str, dict[str, Any]]] | None = None
        self._inventory_requested = False
        self._inventory_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._listeners: list[Callable[[], None]] = []
        self._event_listeners: list[Callable[[str, dict[str, Any]], None]] = []

    @property
    def connected(self) -> bool:
        """Return whether a connection and its initial inventory are ready."""
        return self._ready and self.client.connected

    @property
    def unique_id(self) -> str | None:
        """Return the verified identity, retained across reconnections."""
        return self._identity

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to inventory, state and connection changes."""
        self._listeners.append(callback)

        def unsubscribe() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return unsubscribe

    def subscribe_events(
        self, callback: Callable[[str, dict[str, Any]], None]
    ) -> Callable[[], None]:
        """Subscribe to endpoint occurrences without replaying old events."""
        self._event_listeners.append(callback)

        def unsubscribe() -> None:
            if callback in self._event_listeners:
                self._event_listeners.remove(callback)

        return unsubscribe

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            try:
                listener()
            except Exception:
                _LOGGER.warning("Gateway update callback failed")

    async def async_connect(self) -> None:
        """Connect and read a full snapshot, without starting reconnection."""
        self._stopping = False
        self._ready = False
        try:
            info = await self.client.async_connect()
            identity = gateway_identity(info)
            if self._identity is not None and identity != self._identity:
                raise RexenseError("The address belongs to a different gateway")
            self._identity = identity
            self.gateway = info
            if self._baseline is None:
                self._baseline = await asyncio.to_thread(load_baseline)
            await self.async_refresh_inventory()
        except BaseException:
            await self.client.async_close()
            raise
        self._ready = True
        self.last_error = None
        self._notify()

    async def async_start(self) -> None:
        """Connect, then supervise reconnection until async_stop is called."""
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        await self.async_connect()
        self._reconnect_task = asyncio.create_task(
            self._async_reconnect(), name="aiorexense reconnect"
        )

    async def _async_reconnect(self) -> None:
        delay = self._reconnect_delay
        while not self._stopping:
            await self.client.async_wait_disconnected()
            self._ready = False
            self.last_error = RexenseConnectionError("Gateway disconnected")
            self._notify()
            await asyncio.sleep(delay)
            try:
                await self.async_connect()
            except (RexenseAuthenticationError, UnsupportedTaxonomyError) as error:
                self.last_error = error
                self._notify()
                return
            except RexenseError as error:
                self.last_error = error
                self._notify()
                delay = min(delay * 2, 60)
            else:
                delay = self._reconnect_delay

    async def async_refresh_inventory(self) -> None:
        """Replace a complete paginated snapshot and apply concurrent push messages."""
        async with self.inventory_lock:
            self._buffer = []
            try:
                endpoints: dict[str, Endpoint] = {}
                nodes: dict[str, dict[str, Any]] = {}
                cursor: str | None = None
                seen: set[str] = set()
                while True:
                    result = await self.client.async_request(
                        "device.list",
                        {
                            "limit": 100,
                            "cursor": cursor,
                            "view": "device",
                            "include": {
                                "prop": True,
                                "verbose": True,
                                "cap_def": False,
                            },
                        },
                    )
                    for raw_node in result.get("items", []):
                        node = deepcopy(raw_node)
                        node.pop("received_at", None)
                        if isinstance(node.get("mac"), str):
                            mac = node["mac"].upper()
                            if received := self.nodes.get(mac, {}).get("received_at"):
                                node["received_at"] = received
                            nodes[mac] = node
                        for endpoint in endpoints_from_node(node, self._baseline or {}):
                            endpoints[endpoint.addr] = endpoint
                    paging = result.get("paging", {})
                    if not paging.get("has_more"):
                        break
                    cursor = paging.get("next_cursor")
                    if not cursor or cursor in seen:
                        raise RexenseError(
                            "Gateway returned a repeated or empty cursor"
                        )
                    seen.add(cursor)

                semaphore = asyncio.Semaphore(4)

                async def load_capabilities(endpoint: Endpoint) -> None:
                    async with semaphore:
                        try:
                            response = await self.client.async_request(
                                "device.logic.cap.get",
                                {"addr": endpoint.addr, "include_state": True},
                            )
                        except RexenseCommandError as error:
                            _LOGGER.debug(
                                "Capability lookup failed with code %s", error.code
                            )
                            return
                        endpoint.update_capabilities(response)

                try:
                    async with asyncio.TaskGroup() as group:
                        for endpoint in endpoints.values():
                            group.create_task(load_capabilities(endpoint))
                except ExceptionGroup as error:
                    cause = error.exceptions[0]
                    if isinstance(cause, RexenseError):
                        raise cause from error
                    raise RexenseError("Unable to load gateway capabilities") from error
                self.endpoints = endpoints
                self.nodes = nodes
            finally:
                buffered = self._buffer
                self._buffer = None
                for event, data in buffered:
                    self._handle_event(event, data)
            self._notify()

    def _schedule_inventory(self) -> None:
        if self._stopping:
            return
        self._inventory_requested = True
        if self._inventory_task is None or self._inventory_task.done():
            self._inventory_task = asyncio.create_task(
                self._async_refresh_after_event(), name="aiorexense inventory"
            )

    async def _async_refresh_after_event(self) -> None:
        while self._inventory_requested and not self._stopping:
            self._inventory_requested = False
            await asyncio.sleep(0.5)
            try:
                await self.async_refresh_inventory()
            except RexenseError as error:
                self.last_error = error
                await self.client.async_close()
                self._ready = False
                self._notify()
                return

    def _handle_event(self, event: str, data: dict[str, Any]) -> None:
        if self._stopping or event not in ("device.message", "device.changed"):
            return
        if self._buffer is not None:
            self._buffer.append((event, data))
            return
        if event == "device.message":
            try:
                addr = canonical_addr(str(data.get("addr", "")))
            except RexenseError:
                return
            endpoint = self.endpoints.get(addr)
            if endpoint is None:
                self._schedule_inventory()
                return
            payload = data.get("data")
            if not isinstance(payload, dict):
                return
            for sibling in self.endpoints.values():
                if sibling.mac == endpoint.mac:
                    sibling.state = "online"
            if node := self.nodes.get(endpoint.mac):
                node["state"] = "online"
                node["received_at"] = datetime.now(UTC).isoformat()
                if isinstance(signal := payload.get("signal"), dict):
                    node.update(
                        {key: signal[key] for key in ("rssi", "lqi") if key in signal}
                    )
            for occurrence in endpoint.apply_message(payload):
                for listener in tuple(self._event_listeners):
                    try:
                        listener(addr, occurrence)
                    except Exception:
                        _LOGGER.warning("Endpoint event callback failed")
        else:
            mac = str(data.get("mac", "")).upper()
            state = data.get("persist_status", data.get("state"))
            if data.get("notify_status") == "leaved":
                self.endpoints = {
                    addr: endpoint
                    for addr, endpoint in self.endpoints.items()
                    if endpoint.mac != mac
                }
                self.nodes.pop(mac, None)
            else:
                if node := self.nodes.get(mac):
                    node.update(
                        {
                            key: value
                            for key, value in data.items()
                            if key != "endpoints"
                        }
                    )
                    if state is not None:
                        node["state"] = state
                for endpoint in self.endpoints.values():
                    if endpoint.mac == mac:
                        endpoint.node.update(
                            {
                                key: value
                                for key, value in data.items()
                                if key != "endpoints"
                            }
                        )
                        if state is not None:
                            endpoint.state = state
                if (
                    data.get("notify_status")
                    in ("secure_joined", "unsecure_joined", "data_changed")
                    or "endpoints" in data
                ):
                    self._schedule_inventory()
        self._notify()

    async def async_execute(
        self, addr: str, properties: dict[str, Any], *, action: str | None = None
    ) -> None:
        """Confirm current capabilities, then send a command exactly once."""
        addr = canonical_addr(addr)
        endpoint = self.endpoints.get(addr)
        if endpoint is None or not self.connected:
            raise RexenseConnectionError("Device is unavailable")
        capabilities = await self.client.async_request(
            "device.logic.cap.get", {"addr": addr, "include_state": False}
        )
        endpoint.update_capabilities(capabilities)
        command = endpoint.command(properties, action)
        result = await self.client.async_request(
            "device.logic.exec", {"addr": addr, "data": command}
        )
        for item in result.get("items", []):
            check_result(item)
            if canonical_addr(item["addr"]) == addr:
                endpoint.update_properties(item.get("properties", {}))
                endpoint.state = item.get("state", endpoint.state)
        self._notify()

    async def async_stop(self) -> None:
        """Stop background tasks and close the socket, retaining the caller's session."""
        self._stopping = True
        self._ready = False
        for task in (self._inventory_task, self._reconnect_task):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        self._inventory_task = None
        self._reconnect_task = None
        await self.client.async_close()
        self._notify()
