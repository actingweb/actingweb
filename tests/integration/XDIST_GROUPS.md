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
| `subscription_processing` | Subscription callback processing | test_subscription_processing_flow.py |
| `subscription_suspension` | Subscription suspension mechanics | test_subscription_suspension_flow.py |
| `subscription_callback_flows` | Subscription callback flow variations | test_subscription_callback_flows.py |
| `subscription_sync_dataclasses` | Subscription sync data structures | test_subscription_sync_dataclasses.py |
| `subscription_with_peer_capabilities` | Subscriptions with peer capability discovery | test_subscription_with_peer_capabilities.py |
| `circuit_breaker` | Circuit breaker failure handling | test_circuit_breaker_flow.py |
| `circuit_breaker_recovery` | Circuit breaker recovery mechanisms | test_circuit_breaker_recovery.py |
| `back_pressure` | Back pressure handling for subscriptions | test_back_pressure.py |
| `cached_capabilities` | Capability caching behavior | test_cached_capabilities.py |
| `callback_sequencing` | Callback sequence ordering | test_callback_sequencing.py |
| `cleanup_verification` | Cleanup verification tests | test_cleanup_verification.py |
| `granularity_downgrade` | Subscription granularity downgrade handling | test_granularity_downgrade.py |
| `multiple_subscribers_suspension` | Suspension with multiple subscribers | test_multiple_subscribers_suspension.py |
| `peer_capabilities` | Peer capability discovery | test_peer_capabilities_integration.py |
| `peer_capabilities_subscription` | Subscription with peer capabilities | test_peer_capabilities_subscription.py |
| `peer_profile_trust_flow` | Peer profile trust operations | test_peer_profile_trust_flow.py |
| `property_list_collision` | Property list collision handling | test_property_list_collision.py |
| `resync_callbacks` | Resync callback handling | test_resync_callbacks.py |
| `resync_on_resume` | Resync on subscription resume | test_resync_on_resume.py |
| `resync_state_handling` | Resync state management | test_resync_state_handling.py |
| `suspension_subtarget` | Subscription subtarget suspension | test_suspension_subtarget.py |
| `baseline_storage` | Baseline sync storage of simple and list properties | test_subscription_baseline_storage.py |
| `peer_profile_extraction` | Peer profile extraction during subscription sync | test_peer_profile_extraction.py |
| `devtest_attributes_flow` | DevTest attributes operations | test_devtest_attributes_flow.py |
| `mcp_integration` | MCP (Model Context Protocol) integration tests | test_mcp_integration.py |
| `oauth2_integration` | OAuth2 authentication and token flow | test_oauth2_integration.py |
| `www_templates` | Web UI template rendering | test_www_templates.py |
| `flask_integration` | Flask framework integration | test_flask_integration.py |
| `fastapi_integration` | FastAPI framework integration | test_fastapi_integration.py |
| `devtest_endpoints` | Development and testing endpoints | test_devtest_endpoints.py |

### Isolation Groups (Technical Requirements)
Tests with technical isolation needs to prevent conflicts.

| Group | Reason | Files |
|-------|--------|-------|
| `attribute_patching` | Both patch `actingweb.attribute.Attributes` | test_callback_processor.py, test_remote_storage.py |
| `fanout_tests` | Asyncio event loop conflicts | test_fanout.py |

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
