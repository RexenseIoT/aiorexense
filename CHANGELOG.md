# Changelog

## 0.2.0

- Add the independent taxonomy v3 gateway transport, endpoint models and packaged
  capability baseline, with a high-level inventory and push client.
- Add optional API-key authentication, correlated requests, identity checks and
  reconnection supervision. Do not replay writes after a disconnect or timeout.
- Validate commands against fresh runtime capabilities; keep command acceptance
  separate from observed state.
- Preserve the existing individual-device HTTP/WebSocket API and constants; fix
  cleanup of sessions created by the legacy WebSocket client.
- Require Python 3.11+ and aiohttp 3.12+. Consolidate build metadata and include
  the typed marker and taxonomy resource in both distributions.
- Add loopback protocol tests and public test/build/publication workflows.

## 0.1.4 and earlier

Previously published legacy individual-device API releases remain available on
[PyPI](https://pypi.org/project/aiorexense/#history).
