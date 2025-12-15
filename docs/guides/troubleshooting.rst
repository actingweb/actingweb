===============
Troubleshooting
===============

Common issues and fixes when developing with ActingWeb.

401 at /mcp
-----------

- Cause: No authentication configured or provided. MCP is OAuth2-protected in production.
- Fix: Configure OAuth2 (Google/GitHub) with `.with_oauth(...)`. Unauthenticated requests should return 401 with `WWW-Authenticate` header. For local, temporarily allow open access or sign in via `/www`.

DynamoDB Local connection errors
--------------------------------

- Symptom: Timeouts or table not found.
- Fix: Ensure DynamoDB Local is running and set env vars:

  .. code-block:: bash

     export AWS_ACCESS_KEY_ID=local
     export AWS_SECRET_ACCESS_KEY=local
     export AWS_DEFAULT_REGION=us-east-1
     export AWS_DB_HOST=http://localhost:8000

Slow first request after startup
--------------------------------

- Explanation: The permission system compiles/caches trust types on first use.
- Fix: This is initialized automatically during framework integration. If you still see warmups during requests, check logs for initialization errors.

Tools/prompts don’t appear in tools/list or prompts/list
--------------------------------------------------------

- Check that you decorated hooks correctly:
  - Tools: `@app.action_hook("name")` + `@mcp_tool(...)`
  - Prompts: `@app.method_hook("name")` + `@mcp_prompt(...)`
- Verify unified access control isn’t filtering them out for the current peer.

Property changes not visible in Web UI
--------------------------------------

- Hook returns `None` for GET hides the property completely.
- Hook returns `None` for PUT/POST marks the property read-only.
