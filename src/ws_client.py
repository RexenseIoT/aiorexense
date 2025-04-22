"""
WebSocket client for Rexense devices, independent of Home Assistant.
"""
import asyncio
import logging
from typing import Any, Callable, Optional

from aiohttp import ClientSession, ClientWebSocketResponse, ClientWSTimeout, WSMsgType
from .const import REXENSE_SWITCH_ONOFF

_LOGGER = logging.getLogger(__name__)


class RexenseWebsocketClient:
    """
    Manages WebSocket connection to a Rexense device.
    """

    def __init__(
        self,
        device_id: str,
        model: str,
        url: str,
        sw_build_id: str,
        feature_map: list[dict[str, Any]],
        session: Optional[ClientSession] = None,
        on_update: Optional[Callable[[], None]] = None,
    ) -> None:
        """Initialize the WebSocket client."""
        self.device_id = device_id
        self.model = model
        self.sw_build_id = sw_build_id
        self.feature_map = feature_map
        self.url = url
        self.ws: Optional[ClientWebSocketResponse] = None
        self.connected: bool = False
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self.last_values: dict[str, Any] = {}
        self.switch_state: Optional[bool] = None
        self.ping_interval: int = 30

        self.on_update = on_update
        self._session = session
        self.signal_update = f"{device_id}_update"

    async def connect(self) -> None:
        """Connect to the device and start listening."""
        if self._running:
            return
        # Prepare session
        if self._session is None:
            self._session = ClientSession()

        _LOGGER.debug("Attempting WebSocket connection to %s", self.url)
        try:
            ws = await self._session.ws_connect(
                self.url,
                timeout=ClientWSTimeout(ws_close=10),
                heartbeat=self.ping_interval,
                autoping=True,
            )
        except Exception as err:
            _LOGGER.error(
                "Initial WebSocket connect failed for %s: %s", self.device_id, err
            )
            self._running = False
            raise
        else:
            self._running = True
            self.ws = ws
            self.connected = True
            _LOGGER.info("WebSocket connected to device %s", self.device_id)
            self._task = asyncio.create_task(self._run_loop())

    async def _run_loop(self) -> None:
        """Run the WebSocket listen and auto-reconnect loop."""
        first_try = True
        while self._running:
            try:
                if not first_try:
                    _LOGGER.info("Reconnecting to device %s", self.device_id)
                    ws = await self._session.ws_connect(
                        self.url,
                        timeout=ClientWSTimeout(ws_close=10),
                        heartbeat=self.ping_interval,
                        autoping=True,
                    )
                    self.ws = ws
                    self.connected = True
                    _LOGGER.info("WebSocket reconnected to device %s", self.device_id)
                else:
                    first_try = False

                assert self.ws is not None
                async for msg in self.ws:
                    if msg.type == WSMsgType.TEXT:
                        try:
                            data = msg.json()
                        except ValueError as e:
                            _LOGGER.error("Received invalid JSON: %s, data: %s", e, msg.data)
                            continue
                        _LOGGER.debug("Received message: %s", data)
                        self._handle_message(data)
                    elif msg.type == WSMsgType.ERROR:
                        assert self.ws is not None
                        _LOGGER.error(
                            "WebSocket error for %s: %s",
                            self.device_id,
                            self.ws.exception(),
                        )
                        break
                    elif msg.type in (WSMsgType.CLOSED, WSMsgType.CLOSING):
                        _LOGGER.warning(
                            "WebSocket connection closed for %s", self.device_id
                        )
                        break
            except Exception as err:
                _LOGGER.error(
                    "WebSocket connection failed for %s: %s", self.device_id, err
                )
            # Clean up and maybe reconnect
            self.connected = False
            if self.ws is not None:
                try:
                    await self.ws.close()
                except Exception:
                    pass
                finally:
                    self.ws = None

            if self._running:
                await asyncio.sleep(5)
                continue

    def _handle_message(self, data: dict[str, Any]) -> None:
        """Process incoming message from WebSocket."""
        func = (data.get("FunctionCode") or data.get("function") or data.get("func"))
        if isinstance(func, str):
            func = func.lower()

        if func == "notifystatus":
            payload = data.get("Payload") or {}
            _LOGGER.debug("Received payload: %s", payload)
            for k, v in payload.items():
                key = k.replace("_1", "")
                if key == REXENSE_SWITCH_ONOFF['name']:
                    self.switch_state = v not in ("0", False)
                    _LOGGER.debug("Update switch state: %s", self.switch_state)
                else:
                    _LOGGER.debug("Update sensor %s: %s", key, v)
                    self.last_values[key] = v
            # Trigger update callback
            if self.on_update:
                try:
                    self.on_update()
                except Exception as e:
                    _LOGGER.error("Error in on_update callback: %s", e)
        else:
            _LOGGER.debug("Unhandled function %s: %s", func, data)

    async def async_set_switch(self, on: bool) -> None:
        """Send ON/OFF command to device via WebSocket."""
        if not self.connected or self.ws is None:
            raise RuntimeError("WebSocket is not connected.")
        control = "On" if on else "Off"
        payload = {
            "FunctionCode": "InvokeCmd",
            "Payload": {control: {}},
        }
        try:
            await self.ws.send_json(payload)
        except Exception as err:
            _LOGGER.error("Failed to send switch command: %s", err)
            raise

    async def disconnect(self) -> None:
        """Disconnect and stop the WebSocket client."""
        _LOGGER.info("Disconnecting WebSocket for device %s", self.device_id)
        self._running = False
        if self.ws is not None:
            await self.ws.close()
        if self._task:
            await self._task
        self.ws = None
        self.connected = False

    async def disconnect(self) -> None:
        """Disconnect and stop the WebSocket client."""
        _LOGGER.info("Disconnecting WebSocket for device %s", self.device_id)
        self._running = False
        if self.ws is not None:
            await self.ws.close()
        if self._task:
            await self._task
        self.ws = None
        self.connected = False
