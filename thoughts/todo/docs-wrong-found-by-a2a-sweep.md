# Docs already wrong against the code (found by the A2A sweep)

**Filed:** 2026-11-25, from the documentation sweep in
`thoughts/research/2026-11-24-a2a-actor-interface.md` ("Documentation
Impact"). These pages are wrong today, whether or not A2A lands. Line numbers
are as of 4.0.0rc3. Re-read each before editing it.

- **`docs/guides/oauth2-setup.rst:32-33`** says `MCPClientRegistry` stores
  clients "using ActingWeb's property system". The registry uses attribute
  buckets.
- **`docs/guides/oauth2-setup.rst:238-239`** says a re-authorisation "removes
  its permission override". That overstates it: the override is removed only
  when the trust type changes or the row is created new
  (`trust_manager.py:492-530, 815-830`).
- **`docs/guides/mcp-applications.rst`**:
  - **1338** calls the private `_load_client`. The public call is
    `OAuth2ClientManager.get_client` (`interface/oauth_client_manager.py:107`).
  - **1351-1397** tells readers to add a method that already exists.
  - **1476-1478** mixes two flows.
- **`docs/guides/authentication.rst:1603-1635`** lists three well-known
  documents and says "All three" (1632). It leaves out
  `openid-configuration`, which is served.

A docs-only patch, needing only the docs build. Each is small.
