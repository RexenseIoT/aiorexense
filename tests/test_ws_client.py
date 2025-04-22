
import pytest
import asyncio
from aiorexense.ws_client import RexenseWebsocketClient

from aiorexense.const import REXENSE_SWITCH_ONOFF

def test_handle_message_notify_status():
    updates = []
    def on_update():
        updates.append(True)

    client = RexenseWebsocketClient(
        device_id="dev123",
        model="modelX",
        url="ws://example",
        sw_build_id="build1",
        feature_map=[],
        on_update=on_update,
    )
    # simulate payload
    payload = {
        REXENSE_SWITCH_ONOFF['name']: "1",
        "TestSensor": 123,
    }
    data = {"FunctionCode": "NotifyStatus", "Payload": payload}
    client._handle_message(data)

    assert client.switch_state is True
    assert client.last_values.get("TestSensor") == 123
    assert updates == [True]

def test_handle_message_unhandled(caplog):
    client = RexenseWebsocketClient("dev", "model", "url", "sw", [])
    caplog.set_level("DEBUG")
    client._handle_message({"FunctionCode": "UnknownFunc", "Payload": {}})
    assert "Unhandled function" in caplog.text

@pytest.mark.asyncio
async def test_async_set_switch_not_connected():
    client = RexenseWebsocketClient("dev", "model", "url", "sw", [])
    client.connected = False
    client.ws = None
    with pytest.raises(RuntimeError):
        await client.async_set_switch(True)

@pytest.mark.asyncio
async def test_async_set_switch_success():
    sent = []
    class DummyWS:
        async def send_json(self, payload):
            sent.append(payload)

    client = RexenseWebsocketClient("dev", "model", "url", "sw", [])
    client.connected = True
    client.ws = DummyWS()

    await client.async_set_switch(False)
    assert sent[-1] == {"FunctionCode": "InvokeCmd", "Payload": {"Off": {}}}

    await client.async_set_switch(True)
    assert sent[-1] == {"FunctionCode": "InvokeCmd", "Payload": {"On": {}}}

@pytest.mark.asyncio
async def test_disconnect(monkeypatch):
    client = RexenseWebsocketClient("dev", "model", "url", "sw", [])
    # Attach dummy ws and task
    class DummyWS:
        async def close(self):
            pass

    client.ws = DummyWS()
    client.connected = True
    client._running = True

    # Create and cancel a dummy task
    async def dummy_task():
        await asyncio.sleep(0)
    task = asyncio.create_task(dummy_task())
    client._task = task

    await client.disconnect()

    assert client.ws is None
    assert client.connected is False
