
import pytest
from aiohttp import ClientError
import aiorexense.api as api

class DummyResponse:
    def __init__(self, status, data):
        self.status = status
        self._data = data

    async def json(self):
        return self._data

class DummySession:
    def __init__(self, response):
        self._response = response

    async def get(self, url, json):
        return self._response

@pytest.mark.asyncio
async def test_get_basic_info_success():
    data = {
        "FunctionCode": "ReportBasicInfo",
        "DeviceId": "dev123",
        "Payload": {
            "ModelId": "modelX",
            "SwBuildId": "build1",
            "FeatureMap": [{"feat":1}],
        }
    }
    resp = DummyResponse(200, data)
    session = DummySession(resp)
    device_id, model, sw_build_id, feature_map = await api.get_basic_info("host", 80, session)
    assert device_id == "dev123"
    assert model == "modelX"
    assert sw_build_id == "build1"
    assert feature_map == [{"feat":1}]

@pytest.mark.asyncio
async def test_get_basic_info_http_error():
    resp = DummyResponse(404, {})
    session = DummySession(resp)
    with pytest.raises(ClientError):
        await api.get_basic_info("host", 80, session)

@pytest.mark.asyncio
async def test_get_basic_info_invalid_format():
    data = {"FunctionCode": "WrongCode", "Payload": {}}
    resp = DummyResponse(200, data)
    session = DummySession(resp)
    with pytest.raises(ClientError):
        await api.get_basic_info("host", 80, session)
