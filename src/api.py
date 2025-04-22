"""
HTTP API for Rexense device basic info
"""
import asyncio
import logging
from typing import Any, Tuple

from aiohttp import ClientSession, ClientError

from .const import (
    API_VERSION,
    VENDOR_CODE,
    FUNCTION_GET_BASIC_INFO,
)

_LOGGER = logging.getLogger(__name__)


async def get_basic_info(
    host: str,
    port: int,
    session: ClientSession,
    timeout: int = 5,
) -> Tuple[str, str, str, list[dict[str, Any]]]:
    """
    Send an HTTP request to the device, query device_id, model, sw_build_id, feature_map。
    """
    url = f"http://{host}:{port}/rex/device/v1/operate"
    payload = {
        "Version": API_VERSION,
        "VendorCode": VENDOR_CODE,
        "Timestamp": "0",
        "Seq": "0",
        "DeviceId": "",
        "FunctionCode": FUNCTION_GET_BASIC_INFO,
        "Payload": {},
    }
    try:
        async with asyncio.timeout(timeout):
            resp = await session.get(url, json=payload)
    except (asyncio.TimeoutError, ClientError) as err:
        _LOGGER.error("HTTP get_basic_info failed: %s", err)
        raise

    if resp.status != 200:
        _LOGGER.error("Device %s:%s HTTP status %s", host, port, resp.status)
        raise ClientError(f"Status {resp.status}")

    data = await resp.json()

    if data.get("FunctionCode") != FUNCTION_GET_BASIC_INFO.replace("GetBasic", "ReportBasic") or not data.get("Payload"):
        _LOGGER.error("Invalid response format: %s", data)
        raise ClientError("Invalid response format")

    device_id = data.get("DeviceId", "")
    payload = data["Payload"]
    model = payload.get("ModelId", "")
    sw_build_id = payload.get("SwBuildId", "")
    feature_map = payload.get("FeatureMap", [])

    return device_id, model, sw_build_id, feature_map
