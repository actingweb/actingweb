# `auth.py` builds a fresh `Config()` per request when a caller omits one

Found by the 3.14.4 scalability review
(`thoughts/plans/2026-09-02-identifier-matching-and-metadata-fidelity.md`).
Verified at the 3.14.4 tree.

`Auth.__init__` (`actingweb/auth.py:83`) and the public
`check_and_verify_auth()` helpers (`:839`, `:919`) construct `Config()` when
the caller passes none. Every config-bound singleton compares by **identity**
(`tests/test_config_bound_singletons.py` pins that), so each such request
rebuilds the permission evaluator, the trust type registry, the trust
permission store and their caches, and re-runs `logging.basicConfig()` via
`configure_actingweb_logging()`. It is the largest per-request cost adjacent to
the permission path. The library's own integrations always pass a config; the
exposure is direct callers of the helpers.

Fix shape: require a config (a breaking signature change, next minor) or fall
back to a process-wide default the app registered, never a fresh instance.

## Related: `Config.oauth["redirect_uri"]` is built from the default `fqdn`

`actingweb/config.py:170` composes `redirect_uri` from `self.proto` and
`self.fqdn` **before** the kwargs loop has applied the caller's values, so it
carries `demo.actingweb.io` unless `oauth=` is passed explicitly (which every
`ActingWebApp` does, masking it). A direct `Config(fqdn=...)` caller who reads
`config.oauth["redirect_uri"]` gets the wrong host. Same fix locus as the
3.14.4 `fqdn` validation: derive it after the loop.
