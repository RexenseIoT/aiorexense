"""Asynchronous transport for the Rexense WebSocket API."""

import asyncio
import itertools
import json
import logging
from collections.abc import Callable
from contextlib import suppress
from typing import Any

import aiohttp
from yarl import URL

DEFAULT_GATEWAY_PORT = 8090
MIN_TAXONOMY_VERSION = 3
REQUEST_TIMEOUT = 15
_LOGGER = logging.getLogger(__name__)


class RexenseError(Exception):
    """A Rexense protocol or transport error."""


class RexenseConnectionError(RexenseError):
    """The connection was lost or a request timed out."""


class RexenseAuthenticationError(RexenseError):
    """The gateway rejected authentication."""


class UnsupportedTaxonomyError(RexenseError):
    """The gateway does not implement the v3 logical-device contract."""


class RexenseCommandError(RexenseError):
    """The gateway rejected a command."""

    def __init__(self, code: int) -> None:
        """Keep untrusted response text and credentials out of exceptions."""
        self.code = code
        super().__init__(f"Gateway returned error code {code}")


def check_result(result: dict[str, Any]) -> None:
    """Validate a response, including target-level execution results."""
    code = result.get("code")
    if code in (401, 403):
        raise RexenseAuthenticationError("Gateway authentication failed")
    if not isinstance(code, int) or isinstance(code, bool):
        raise RexenseError("Gateway response has no numeric result code")
    if code != 0:
        raise RexenseCommandError(code)


def gateway_identity(info: dict[str, Any]) -> str:
    """Return a stable gateway identity, independent of its IP address."""
    if serial := str(info.get("system", {}).get("sn") or "").strip():
        return serial.lower()
    for network in info.get("network", {}).values():
        if isinstance(network, dict) and (mac := network.get("mac")):
            return str(mac).replace(":", "").replace("-", "").lower()
    raise RexenseError("Gateway has neither a serial number nor a MAC address")


def validate_gateway(info: dict[str, Any]) -> None:
    """Enforce the connection-scoped taxonomy boundary."""
    version = info.get("taxonomy_version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version < MIN_TAXONOMY_VERSION
    ):
        raise UnsupportedTaxonomyError("Rexense requires taxonomy_version >= 3")
    gateway_identity(info)


class RexenseClient:
    """One connection with correlated requests and unsolicited events."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int = DEFAULT_GATEWAY_PORT,
        api_key: str = "",
        *,
        use_ssl: bool = False,
        verify_ssl: bool = True,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
        request_timeout: float = REQUEST_TIMEOUT,
    ) -> None:
        """Initialize a client using the caller's shared HTTP session."""
        self._session = session
        self._url = URL.build(
            scheme="wss" if use_ssl else "ws", host=host, port=port, path="/ws"
        )
        self._api_key = api_key
        self._verify_ssl = verify_ssl
        if request_timeout <= 0:
            raise ValueError("request_timeout must be positive")
        self.request_timeout = request_timeout
        self.event_callback = event_callback
        self._socket: aiohttp.ClientWebSocketResponse | None = None
        self._reader: asyncio.Task[None] | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._ids = itertools.count(1)
        self._disconnected = asyncio.Event()
        self._disconnected.set()

    @property
    def connected(self) -> bool:
        """Return whether the underlying connection is open."""
        return self._socket is not None and not self._socket.closed

    async def async_connect(self) -> dict[str, Any]:
        """Connect, authenticate, and query the version once per connection."""
        await self.async_close()
        try:
            async with asyncio.timeout(self.request_timeout):
                self._socket = await self._session.ws_connect(
                    self._url,
                    ssl=self._verify_ssl,
                    heartbeat=30,
                    max_msg_size=4 * 1024 * 1024,
                )
            self._disconnected.clear()
            self._reader = asyncio.create_task(
                self._async_read(), name="rexense reader"
            )
            if self._api_key:
                await self.async_request("auth.api_key.use", {"api_key": self._api_key})
            info = await self.async_request("gateway.info.get")
            validate_gateway(info)
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            await self.async_close()
            raise RexenseConnectionError("Unable to connect to gateway") from err
        except BaseException:
            await self.async_close()
            raise
        return info

    async def async_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Send once; never replay a command after a disconnect or timeout."""
        if self._socket is None or self._socket.closed:
            raise RexenseConnectionError("Gateway is disconnected")
        request_id = str(next(self._ids))
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending[request_id] = future
        try:
            async with asyncio.timeout(self.request_timeout):
                await self._socket.send_json(
                    {"id": request_id, "method": method, "params": params or {}}
                )
                result = await future
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            raise RexenseConnectionError("Gateway request failed") from err
        finally:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()
        check_result(result)
        return result

    async def _async_read(self) -> None:
        """Dispatch events before responses: events may also contain an id."""
        assert self._socket is not None
        try:
            async for message in self._socket:
                if message.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    payload = json.loads(message.data)
                except (TypeError, ValueError):
                    continue
                if not isinstance(payload, dict):
                    continue
                if event := payload.get("event"):
                    data = payload.get("data")
                    if (
                        self.event_callback
                        and isinstance(event, str)
                        and isinstance(data, dict)
                    ):
                        try:
                            self.event_callback(event, data)
                        except Exception:
                            _LOGGER.warning("Gateway event callback failed")
                    continue
                future = self._pending.get(str(payload.get("id")))
                if future is None or future.done():
                    continue
                result = payload.get("result")
                if isinstance(result, dict):
                    future.set_result(result)
                else:
                    future.set_exception(RexenseError("Invalid gateway response"))
        except (aiohttp.ClientError, OSError):
            pass
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(RexenseConnectionError("Gateway disconnected"))
            self._disconnected.set()

    async def async_wait_disconnected(self) -> None:
        """Wait until the reader detects a connection loss."""
        await self._disconnected.wait()

    async def async_close(self) -> None:
        """Close the socket and await the reader without closing the session."""
        if self._socket is not None:
            await self._socket.close()
        if self._reader is not None:
            self._reader.cancel()
            with suppress(asyncio.CancelledError):
                await self._reader
        self._reader = None
        self._socket = None
        self._disconnected.set()
