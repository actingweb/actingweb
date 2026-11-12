# pytest-xdist Group Reference

## Overview

This document describes all xdist groups used in the ActingWeb integration test suite. Groups ensure tests with dependencies or resource conflicts run on the same worker during parallel execution.

## Why Groups Are Needed

**Without grouping**, pytest-xdist distributes tests randomly across workers. This breaks:
- Sequential test flows (where test_002 depends on test_001's state)
- Module patching (when multiple files patch the same module)
- Asyncio tests (event loop conflicts across workers)

**With `@pytest.mark.xdist_group(name="group_name")`**, all tests in a group run on the same worker.

## Group Categories

### Flow Groups (Sequential Test Flows)
Tests that share class-level state and must run in order.

| Group | Description | Files |
|-------|-------------|-------|
| `basic_flow` | Basic actor lifecycle | test_basic_flow.py |
| `trust_flow` | Trust relationship operations | test_trust_flow.py |
| `subscription_flow` | Subscription creation and callbacks | test_subscription_flow.py |
| `attributes_flow` | Advanced attribute operations | test_attributes.py |
| `peer_profile_flow` | Peer profile operations | test_peer_profile.py |
| `post_properties_flow` | POST property creation | test_post_properties.py |

### Feature Groups (Grouped for Performance/Clarity)
Feature-specific tests that logically belong together.

| Group | Description | Files |
|-------|-------------|-------|
| `subscription_callback_flows` | Subscription callback flow variations | test_subscription_callback_flows.py |
| `wire_peer_paths` | The wire recordings (`wire/rows.toml`), and the files that use the wire apps | test_oauth2_trust_binding.py, test_peer_state_flow.py, test_wire_access.py, test_wire_delivery.py, test_wire_grants.py, test_wire_harness.py, test_wire_list_properties.py, test_wire_peer_paths.py, test_wire_permissions.py, test_wire_queue_and_lifecycle.py, test_wire_scalar_properties.py, test_wire_trust.py |
| `property_grants_flow` | A peer's grant at every level of a property | test_property_grants_flow.py |
| `subscription_grants_flow` | Pushed and pulled diffs follow the grant at every level | test_subscription_grants_flow.py |
| `resources_grant` | `/resources` follows the peer's grant | test_resources_grant.py |
| `subscription_sync_dataclasses` | Subscription sync data structures | test_subscription_sync_flow.py |
| `cached_capabilities` | Capability caching behavior | test_peer_capabilities_integration.py |
| `cleanup_verification` | Cleanup verification tests | test_subscription_processing_flow.py |
| `peer_capabilities` | Peer capability discovery | test_peer_capabilities_integration.py |
| `peer_capabilities_subscription` | Subscription with peer capabilities | test_subscription_processing_flow.py |
| `peer_profile_trust_flow` | Peer profile trust operations | test_peer_profile.py |
| `property_list_collision` | Property list collision handling | test_property_list_collision.py |
| `baseline_storage` | Baseline sync storage of simple and list properties | test_subscription_baseline_storage.py |
| `callback_processor_cas` | Two threads deliver one in-order callback against the real store; the handler runs once | test_callback_processor_concurrency.py |
| `peer_profile_extraction` | Peer profile extraction during subscription sync | test_peer_profile_extraction.py |
| `sync_coverage` | Subscription sync coverage tests (trust revocation, baseline fetch, error handling) | test_subscription_sync_coverage.py |
| `subscription_lifecycle_hooks` | Subscription deleted hook execution (peer-initiated and owner-initiated) | test_subscription_lifecycle_hooks.py |
| `revoke_peer_subscription` | Revoking inbound subscriptions via revoke_peer_subscription() | test_subscription_lifecycle_hooks.py |
| `unsubscribe_vs_revoke` | Difference between unsubscribe() and revoke_peer_subscription() | test_subscription_lifecycle_hooks.py |
| `devtest_attributes_flow` | DevTest attributes operations | test_devtest_attributes.py |
| `mcp_refresh_rotation_backend` | MCP refresh-token rotation, reuse detection and the 3.15 backend protocol keywords on the real backends | test_mcp_refresh_rotation_backend.py |
| `spa_chain_revocation_backend` | SPA refresh-chain revocation (`delete_by_chain`, `revoke_session`) on the real backends | test_spa_chain_revocation_backend.py |

### Isolation Groups (Technical Requirements)
Tests with technical isolation needs to prevent conflicts.

| Group | Reason | Files |
|-------|--------|-------|
| `attribute_patching` | Both patch `actingweb.attribute.Attributes` | ../test_callback_processor.py, ../test_remote_storage.py |
| `fanout_tests` | Asyncio event loop conflicts | ../test_fanout.py |

### Test Class Groups (Auto-Generated)
Groups automatically created from test class names to ensure class-level isolation.

| Group | Description | Files |
|-------|-------------|-------|
| `actor_root_redirect_TestActorRootContentNegotiation` | Actor root content negotiation tests | test_actor_root_redirect.py |
| `devtest_TestDevTestEndpoints` | DevTest endpoint test class | test_devtest.py |
| `oauth2_security_TestCrossActorAuthorizationPrevention` | Cross-actor authorization prevention | test_oauth2_security.py |
| `oauth2_security_TestEmailValidationSecurity` | Email validation security tests | test_oauth2_security.py |
| `spa_api_TestMetaTrustTypesAPI` | SPA meta trust types API | test_spa_api.py |
| `spa_api_TestPropertiesMetadataAPI` | SPA properties metadata API | test_spa_api.py |
| `spa_api_TestPropertyMetadataEndpoint` | SPA property metadata endpoint | test_spa_api.py |
| `spa_api_TestTrustWithOAuth2Data` | SPA trust with OAuth2 data | test_spa_api.py |
| `unique_creator` | Creator uniqueness on an isolated store: the fixtures swap the process-wide table names (DynamoDB) or schema (PostgreSQL), so no other test may run beside them | test_deletion_resume_http.py, test_property_lookup_readiness.py, test_unique_creator_adoption.py, test_unique_creator_backend.py, test_unique_creator_default.py, test_unique_creator_http.py, test_unique_creator_states.py, test_unique_creators_command.py |
| `www_templates_TestWWWCustomTemplateRendering` | WWW custom template rendering | test_www_templates.py |
| `www_templates_TestWWWTemplateURLConsistency` | WWW template URL consistency | test_www_templates.py |
| `www_templates_TestWWWTemplates` | WWW templates test class | test_www_templates.py |
| `www_templates_TestWWWWithOAuthCookie` | WWW with OAuth cookie | test_www_templates.py |

## Running Groups Independently

Test a single group:
```bash
poetry run pytest tests/integration/ -k "basic_flow" -v
```

Run multiple groups in parallel:
```bash
poetry run pytest tests/integration/ -k "basic_flow or trust_flow" -n 2 -v --dist loadgroup
```

## Adding New Groups

When to add a group:
1. **Sequential flows**: Tests share class variables (actor_url, passphrase, etc.)
2. **Module patching**: Multiple test files patch the same module
3. **Asyncio conflicts**: Tests use `asyncio.get_event_loop()`
4. **Resource conflicts**: Tests share expensive setup

How to add:
1. Add `@pytest.mark.xdist_group(name="descriptive_name")` decorator
2. Document the group in this file
3. Add rationale comment in test file docstring
4. Verify independence: `pytest -k "group_name" -v`

## Implementation Notes

- Groups are session-scoped for the entire test class
- Worker isolation uses database prefixes (DynamoDB) or schemas (PostgreSQL)
- OAuth2 clients are namespaced by worker ID to prevent token exchange conflicts
- Each worker gets its own port range for test apps (base + worker_num * 10)
