import asyncio
from aiohttp import ClientSession
from aiorexense import (
  get_basic_info,
  RexenseWebsocketClient
)

async def main():
    session = ClientSession()
    # 1. HTTP get device basic info
    device_id, model, sw_build_id, feature_map = await get_basic_info(
        host='192.168.1.50', port=80, session=session
    )
    # 2. WebSocket connect
    client = RexenseWebsocketClient(
        device_id=device_id,
        model=model,
        url=f'ws://192.168.1.50:80/rpc',
        sw_build_id=sw_build_id,
        feature_map=feature_map,
        session=session,
        on_update=lambda: print('Update value', client.last_values)
    )
    await client.connect()

asyncio.run(main())
