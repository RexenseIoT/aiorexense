# aiorexense

A Python asyncio client for Rexense gateways and legacy individual devices. The
gateway client maintains device inventory, runtime capabilities and push state
without depending on Home Assistant or a cloud service.

## Install

```bash
pip install aiorexense
```

Python 3.11 or later is required. The gateway API uses `aiohttp >= 3.12` and a
caller-owned `aiohttp.ClientSession`.

## Supported gateway contract

- Local WebSocket API at `ws://<gateway>:8090/ws`; TLS and a different port are
  configurable.
- `taxonomy_version >= 3`, with precise capabilities from
  `device.logic.cap.get`. Runtime capabilities determine which operations are
  allowed; the bundled taxonomy is a discovery baseline.
- Manufacturer-confirmed minimum: **RG5100**, `system.sw_version` **4.0.0**.
  Firmware can be upgraded locally. Firmware version and taxonomy version are
  separate fields; the client checks the taxonomy contract on every connection.
- An API key is optional when gateway authentication is disabled.

The [RG5100 product page](https://www.rexense.cn/product_cont_51_1819.html)
describes this B2B gateway. A read-only check on 2026-10-25 confirmed an RG5100
running 4.0.0 and a TL0001 switch running `20260630 17:12`, exposing one `switch`
endpoint with `onoff` and `identify`. Physical switching, push latency and device
restart recovery still require hardware validation. A missing `on` property means
the current state is unknown; it must not be treated as off.

## Read inventory and subscribe to changes

```python
import asyncio

import aiohttp

from aiorexense import RexenseGateway


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        gateway = RexenseGateway(session, "192.168.1.10")

        def changed() -> None:
            for address, endpoint in gateway.endpoints.items():
                print(address, endpoint.dev_type, endpoint.properties)

        unsubscribe = gateway.subscribe(changed)
        try:
            await gateway.async_start()
            await asyncio.sleep(60)
        finally:
            unsubscribe()
            await gateway.async_stop()


asyncio.run(main())
```

`async_start()` reads the initial inventory and starts reconnection supervision.
`async_connect()` reads the same snapshot without starting automatic reconnection.
`async_refresh_inventory()` explicitly refreshes inventory and capabilities.
`async_stop()` cancels background tasks and closes the WebSocket; it leaves the
provided session open. Subscribe callbacks are synchronous and should return
quickly. `subscribe_events()` delivers endpoint occurrences without replaying old
events.

`gateway.connected` means the connection and initial inventory are ready.
`gateway.unique_id` is retained across reconnects and prevents accepting a
different gateway at the same address. Transient failures retry with a bounded
backoff; authentication and unsupported-taxonomy errors stop reconnection and
are available as `gateway.last_error`.

## Control an endpoint

After inspecting the inventory and selecting an actual device address:

```python
# This changes a real device. Use an address from gateway.endpoints.
await gateway.async_execute("00124B0000000001:1", {"on": True})
```

Each operation refreshes runtime capabilities and validates the endpoint's
availability, property access, argument types and limits before sending exactly
one `device.logic.exec` request. An `accepted` response does not change observed
state. State updates come from a completed command response or gateway push.
Writes are never retried automatically after a timeout or disconnect.

For an advertised action, pass `action="<action_name>"` and its argument mapping.
Unsupported properties and actions raise `RexenseError`. Failed authentication
raises `RexenseAuthenticationError`; transport errors raise
`RexenseConnectionError`; gateway rejection raises `RexenseCommandError`, whose
`code` contains the numeric result. Exceptions do not include response bodies or
API keys.

## Low-level transport

`RexenseClient(session, host, port=8090, api_key="")` offers `async_connect()`,
`async_request(method, params)`, `async_wait_disconnected()` and `async_close()`.
Use it when the application owns its inventory and reconnect policy. Requests
are correlated by ID, and unsolicited events go to `event_callback`.

Both clients accept `use_ssl`, `verify_ssl` and a positive `request_timeout`.
`RexenseGateway` also accepts `reconnect_delay`, `expected_gateway_id` and an
optional preloaded `baseline`. `load_baseline()` performs file I/O; asynchronous
callers should use `await asyncio.to_thread(load_baseline)`.

## Legacy compatibility

The existing `get_basic_info`, `RexenseWebsocketClient`, sensor constants and
`DEFAULT_PORT = 80` remain available. New gateway applications use
`RexenseGateway` or `RexenseClient` and `DEFAULT_GATEWAY_PORT = 8090`.
The legacy WebSocket client closes sessions it creates and keeps caller-provided
sessions open. See [usage.py](usage.py) for the legacy device API.

## Development and releases

```bash
python -m pip install -e '.[dev]' build twine
pytest
ruff check .
ruff format --check .
mypy
python -m build
python -m twine check dist/*
```

Public [GitHub Actions](https://github.com/RexenseIoT/aiorexense/actions) runs tests
on Python 3.11–3.14, checks types and formatting, and builds the source archive
and wheel. Releases publish those CI-built artifacts to PyPI after all checks
pass. Configure the repository's `PYPI_API_TOKEN` Actions secret, update
`src/__init__.py` and `CHANGELOG.md`, then push a main-branch commit containing a
`Release: X.Y.Z` trailer, or run the workflow on `main` with that release version.
The workflow verifies the package version and creates the matching immutable
`vX.Y.Z` tag. It rejects tags pointing at a different commit and does not overwrite
PyPI releases. Never put a publishing token in the source tree or a workflow file.

Maintainer: [@GorgeOu](https://github.com/GorgeOu). Licensed under [MIT](LICENSE).
