# Examples

This directory is repo-only — it ships in this repository's tests and
documentation but not in the published `actingweb` wheel (verified by a test
in `tests/`).

- **`mcp_quickstart.py`** — a minimal single-actor MCP server: one tool, one
  prompt. Narrated in `docs/guides/mcp-quickstart.rst`.
- **`p2p_quickstart.py`** — a two-actor peer-to-peer trust and subscription
  flow. Narrated in `docs/guides/p2p-quickstart.rst`.
- **`demo/`** — a complete Flask application (OAuth2 login, MCP, the full
  hook system, a customized web UI). See `demo/README.md`. This is the
  application code behind the live `demo.actingweb.io` instance; deployment
  of that instance lives in the separate `actingwebdemo` repository.

Each quickstart script is also imported directly by a test under `tests/`,
so the documentation, the example, and the test all exercise the same code
rather than three copies that can drift apart.
