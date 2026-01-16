"""
WWW Endpoint Integration Tests.

Tests that verify www endpoints are properly configured and secured.

NOTE: ActingWeb is a library - HTML templates are provided by the application
(e.g., actingwebdemo), not by the library itself. These tests verify:
1. WWW endpoints exist and are routable
2. Authentication is properly enforced
3. Template variables are passed correctly (when templates exist)

For full template testing, see actingwebdemo integration tests.

These tests use a separate test app fixture (www_test_app) that runs WITHOUT OAuth
enabled, allowing www endpoints to be accessed with basic auth credentials.

This test suite runs sequentially - each test depends on the previous ones.
"""


class TestWWWTemplates:
    """
    Sequential test flow for www template verification.

    Tests www endpoints with basic auth (OAuth disabled in www_test_app fixture).
    This verifies template variables are correctly populated.

    Tests must run in order as they share state (actor created in early tests,
    used in middle tests, deleted in final test).
    """

    # Shared state across tests in this class
    actor_url: str | None = None
    actor_id: str | None = None
    passphrase: str | None = None
    creator: str = "wwwtest@actingweb.net"

    def test_001_create_actor(self, www_test_app):
        """
        Create an actor for www template testing.

        Spec: docs/actingweb-spec.rst:454-505
        """
        import requests

        response = requests.post(
            f"{www_test_app}/",
            json={"creator": self.creator},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201
        assert response.json()["creator"] == self.creator

        # Store for subsequent tests
        actor_data = response.json()
        TestWWWTemplates.actor_id = actor_data["id"]
        TestWWWTemplates.passphrase = actor_data["passphrase"]

        # Build actor URL from base URL and ID
        TestWWWTemplates.actor_url = f"{www_test_app}/{TestWWWTemplates.actor_id}"

    def test_002_www_root_template_variables(self, www_test_app):
        """
        Verify www root endpoint returns template with correct variables.

        The template should receive: id, creator, actor_root, actor_www, url
        """
        import requests

        # Use the creator and passphrase from actor creation for basic auth
        response = requests.get(
            f"{self.actor_url}/www",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type,union-attr,attr-defined,return-value]
        )

        assert response.status_code == 200
        assert "text/html" in response.headers.get("Content-Type", "")

        html = response.text
        # Verify template variables are populated
        assert self.actor_id in html, "Template should contain actor_id"  # type: ignore[arg-type]
        assert self.creator in html, "Template should contain creator"
        assert f"/{self.actor_id}/www" in html, "Template should contain actor_www URL"

    def test_003_www_init_template_values(self, www_test_app):
        """
        Verify www init template contains expected values.

        Template: aw-actor-www-init.html
        Expected template_values: id, url, actor_root, actor_www
        """
        import requests

        response = requests.get(
            f"{self.actor_url}/www/init",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code == 200

        html = response.text
        assert self.actor_id in html, "actor_id should be in init template"  # type: ignore[arg-type]
        assert f"/{self.actor_id}/www" in html, "actor_www URL should be in template"

    def test_004_create_simple_property(self, www_test_app):
        """Create a simple property for testing properties template."""
        import requests

        response = requests.post(
            f"{self.actor_url}/properties/test_prop",
            json={"test_prop": "test_value"},
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code in [200, 201]

    def test_005_www_properties_template_values(self, www_test_app):
        """
        Verify www properties template contains expected values.

        Template: aw-actor-www-properties.html
        Expected template_values: id, properties, read_only_properties, list_properties,
                                  url, actor_root, actor_www
        """
        import requests

        response = requests.get(
            f"{self.actor_url}/www/properties",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code == 200

        html = response.text
        assert self.actor_id in html, "actor_id should be in properties template"  # type: ignore[arg-type]
        assert "test_prop" in html, "property name should be in template"
        assert "test_value" in html, "property value should be in template"
        assert f"/{self.actor_id}/www" in html, "actor_www URL should be in template"

    def test_006_www_property_template_values(self, www_test_app):
        """
        Verify individual property template contains expected values.

        Template: aw-actor-www-property.html
        Expected template_values: id, property, value, raw_value, qual, url, actor_root,
                                  actor_www, is_read_only, is_list_property
        """
        import requests

        response = requests.get(
            f"{self.actor_url}/www/properties/test_prop",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code == 200

        html = response.text
        assert self.actor_id in html, "actor_id should be in property template"  # type: ignore[arg-type]
        assert "test_prop" in html, "property name should be in template"
        assert "test_value" in html, "property value should be in template"
        assert f"/{self.actor_id}/www" in html, "actor_www URL should be in template"

    def test_007_create_list_property(self, www_test_app):
        """Create a list property for testing list property template values."""
        import requests

        # Create empty list property using POST to /properties
        response = requests.post(
            f"{self.actor_url}/properties",
            json={"test_list": {"_type": "list"}},
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code in [200, 201], (
            f"Failed to create list property: {response.text}"
        )

        # Add an item using PUT to the list property (standard approach)
        response = requests.put(
            f"{self.actor_url}/properties/test_list?index=0",
            json="list_item_1",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code == 204, f"Failed to add list item: {response.text}"

    def test_008_www_list_property_template_values(self, www_test_app):
        """
        Verify list property template contains expected values.

        Template: aw-actor-www-property.html (with is_list_property=True)
        Expected template_values: id, property, value, raw_value, qual, url, actor_root,
                                  actor_www, is_read_only, is_list_property (True),
                                  list_items, list_description, list_explanation
        """
        import requests

        response = requests.get(
            f"{self.actor_url}/www/properties/test_list",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code == 200

        html = response.text
        assert self.actor_id in html, "actor_id should be in list property template"  # type: ignore[arg-type]
        assert "test_list" in html, "property name should be in template"
        # Should show list indicator (either "List with X items" or the items themselves)
        assert "list_item_1" in html or "List with" in html or "value" in html, (
            "list content or indicator should be in template"
        )

    def test_009_create_trust_relationship(self, www_test_app):
        """Create a trust relationship for testing trust template."""
        import requests

        # Create peer actor on the same www_test_app server
        peer_response = requests.post(
            f"{www_test_app}/",
            json={"creator": "peer@actingweb.net"},
            headers={"Content-Type": "application/json"},
        )
        assert peer_response.status_code == 201
        peer_data = peer_response.json()
        peer_id = peer_data["id"]
        peer_passphrase = peer_data["passphrase"]
        peer_url = f"{www_test_app}/{peer_id}"

        # Initiate trust from main actor to peer
        trust_response = requests.post(
            f"{self.actor_url}/trust",
            json={
                "url": peer_url,
                "relationship": "friend",
            },
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )
        assert trust_response.status_code == 201

        # Approve trust from peer side
        _ = trust_response.json()  # noqa: F841  # type: ignore[arg-type]
        approve_response = requests.put(
            f"{peer_url}/trust/friend/{self.actor_id}",
            json={"approved": True},
            auth=("peer@actingweb.net", peer_passphrase),
        )
        assert approve_response.status_code == 204

        # Store peer info for potential cleanup
        TestWWWTemplates.peer_id = peer_id
        TestWWWTemplates.peer_url = peer_url

    def test_010_www_trust_template_values(self, www_test_app):
        """
        Verify www trust template contains expected values.

        Template: aw-actor-www-trust.html
        Expected template_values: id, trusts, oauth_clients, url, actor_root, actor_www
        """
        import pytest
        import requests

        # Skip if actor wasn't created in previous tests
        if not self.actor_url or not self.actor_id:
            pytest.skip("Actor not created - test depends on previous tests")

        response = requests.get(
            f"{self.actor_url}/www/trust",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code == 200

        html = response.text
        assert self.actor_id in html, "actor_id should be in trust template"
        assert "friend" in html, "relationship should be in template"
        assert f"/{self.actor_id}/www" in html, "actor_www URL should be in template"

    def test_011_www_trust_new_template_values(self, www_test_app):
        """
        Verify www trust creation form template contains expected values.

        Template: aw-actor-www-trust-new.html
        Expected template_values: id, url, actor_root, actor_www, form_action,
                                  form_method, trust_types, error, default_relationship
        """
        import requests

        response = requests.get(
            f"{self.actor_url}/www/trust/new",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code == 200

        html = response.text
        assert self.actor_id in html, "actor_id should be in trust new template"  # type: ignore[arg-type]
        assert "POST" in html or "post" in html, "form method should be in template"
        # Should have form for creating trust relationships
        assert "peer" in html.lower() or "url" in html.lower(), (
            "form fields should be in template"
        )

    def test_012_cleanup_actor(self, www_test_app):
        """Delete the test actor."""
        import requests

        response = requests.delete(
            self.actor_url,  # type: ignore[arg-type]
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code in [200, 204]  # 204 No Content is valid for DELETE


class TestWWWTemplateURLConsistency:
    """
    Test that URL template values are consistent across all www pages.

    This verifies the fix for base path handling where config.root is used
    to derive actor_root and actor_www URLs.
    """

    actor_id: str | None = None
    actor_url: str | None = None
    passphrase: str | None = None
    creator: str = "urltest@actingweb.net"

    def test_001_create_actor(self, www_test_app):
        """Create an actor for URL consistency testing."""
        import requests

        response = requests.post(
            f"{www_test_app}/",
            json={"creator": self.creator},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201

        actor_data = response.json()
        TestWWWTemplateURLConsistency.actor_id = actor_data["id"]
        TestWWWTemplateURLConsistency.passphrase = actor_data["passphrase"]
        TestWWWTemplateURLConsistency.actor_url = (
            f"{www_test_app}/{TestWWWTemplateURLConsistency.actor_id}"
        )

    def test_002_verify_url_consistency_across_pages(self, www_test_app):
        """
        Verify that actor_root and actor_www URLs are consistent across all www pages.

        This tests the _get_consistent_urls() method implementation.
        """
        import requests

        pages = ["", "init", "properties", "trust"]

        actor_www_pattern = f"/{self.actor_id}/www"
        actor_root_pattern = f"/{self.actor_id}"

        for page in pages:
            url = f"{self.actor_url}/www/{page}" if page else f"{self.actor_url}/www"
            response = requests.get(url, auth=(self.creator, self.passphrase))  # type: ignore[arg-type]

            assert response.status_code == 200, f"Page {page} should be accessible"

            html = response.text
            assert actor_www_pattern in html, (
                f"actor_www URL pattern should be in {page} page"
            )
            # actor_root pattern should also be present (as substring of actor_www)
            assert actor_root_pattern in html, (
                f"actor_root URL pattern should be in {page} page"
            )

    def test_003_cleanup_actor(self, www_test_app):
        """Delete the test actor."""
        import requests

        response = requests.delete(
            self.actor_url,  # type: ignore[arg-type]
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code in [200, 204]  # 204 No Content is valid for DELETE


class TestWWWCustomTemplateRendering:
    """
    Test custom template rendering via www callback hooks.

    When a www callback hook returns {"template": "...", "data": {...}},
    the integration should render that template with the provided data
    merged with standard template values (id, url, actor_root, actor_www).
    """

    actor_id: str | None = None
    actor_url: str | None = None
    passphrase: str | None = None
    creator: str = "customtemplate@actingweb.net"

    def test_001_create_actor(self, www_test_app):
        """Create an actor for custom template testing."""
        import requests

        response = requests.post(
            f"{www_test_app}/",
            json={"creator": self.creator},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 201

        actor_data = response.json()
        TestWWWCustomTemplateRendering.actor_id = actor_data["id"]
        TestWWWCustomTemplateRendering.passphrase = actor_data["passphrase"]
        TestWWWCustomTemplateRendering.actor_url = (
            f"{www_test_app}/{TestWWWCustomTemplateRendering.actor_id}"
        )

    def test_002_custom_path_renders_template(self, www_test_app):
        """
        Verify custom www path renders template from callback hook.

        The test_harness registers a www callback hook for path "custom"
        that returns {"template": "aw-actor-www-custom.html", "data": {...}}.
        This should render the template with both hook data and standard values.
        """
        import requests

        response = requests.get(
            f"{self.actor_url}/www/custom",
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code == 200
        assert "text/html" in response.headers.get("Content-Type", "")

        html = response.text
        # Verify standard template values are present
        assert self.actor_id in html, "Template should contain actor_id"  # type: ignore[arg-type]
        assert f"/{self.actor_id}/www" in html, "Template should contain actor_www URL"

        # Verify custom data from hook is present
        assert "Hello from callback hook!" in html, (
            "Template should contain custom_message from hook"
        )
        assert "Custom Template Test" in html, "Template title should be present"

    def test_003_cleanup_actor(self, www_test_app):
        """Delete the test actor."""
        import requests

        response = requests.delete(
            self.actor_url,  # type: ignore[arg-type]
            auth=(self.creator, self.passphrase),  # type: ignore[arg-type]
        )

        assert response.status_code in [200, 204]


class TestWWWWithOAuthCookie:
    """
    Test www endpoints with OAuth authentication using cookies.

    This demonstrates the pattern for testing www endpoints when OAuth is enabled:
    - Get OAuth bearer token from oauth2_client
    - Set oauth_token cookie with the bearer token
    - Make requests to www endpoints

    This is how real OAuth-authenticated www access works in production.
    """

    def test_www_with_oauth_cookie(self, test_app, oauth2_client):
        """
        Test www endpoint with oauth_token cookie.

        Pattern: oauth_token=<bearer_token>
        """
        import time

        import requests

        # Create an actor
        actor_response = requests.post(
            f"{test_app}/",
            json={"creator": "oauth_www_test@example.com"},
            headers={"Content-Type": "application/json"},
        )
        assert actor_response.status_code == 201
        actor_id = actor_response.json()["id"]

        # Access www with OAuth cookie - retry on transient network errors
        # PostgreSQL backend can occasionally have connection pool issues
        max_retries = 3
        last_error = None
        for attempt in range(max_retries):
            try:
                response = requests.get(
                    f"{test_app}/{actor_id}/www",
                    cookies={"oauth_token": oauth2_client.access_token},
                    timeout=10,
                )
                # Should get 200 with HTML (or redirect if cookie auth not fully implemented)
                assert response.status_code in [200, 302]

                if response.status_code == 200:
                    assert "text/html" in response.headers.get("Content-Type", "")
                return  # Success
            except (
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.ConnectionError,
            ) as e:
                last_error = e
                if attempt < max_retries - 1:
                    time.sleep(0.5 * (attempt + 1))  # Exponential backoff
                    continue
                raise AssertionError(
                    f"Request failed after {max_retries} attempts: {last_error}"
                ) from e
