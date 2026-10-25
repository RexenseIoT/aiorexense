# Changelog

## 0.2.1

- Publish release-tag builds through PyPI Trusted Publishing using GitHub Actions
  OIDC, with signed attestations for the wheel and source distribution.
- Restrict publishing to the `pypi` environment and validate the release tag
  against the tested wheel before uploading. The workflow no longer needs a
  long-lived PyPI token or permission to write repository contents.
- No changes to the gateway API or device behavior.

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
