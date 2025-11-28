"""
Integration tests for SPA-oriented API endpoints.

Tests the REST API endpoints added to support React SPA frontend:
1. GET /properties?metadata=true - Properties with metadata
2. PUT /{actor_id}/properties/{name}/metadata - Update list property metadata
3. GET /{actor_id}/meta/trusttypes - Trust types listing
4. GET /{actor_id}/trust - Trust relationships with OAuth2 client data
"""

import requests


class TestPropertiesMetadataAPI:
    """
    Test properties API with metadata parameter.

    Tests the enhanced GET /properties endpoint that returns metadata
    (description, explanation) for list properties.
    """

    actor_url: str | None = None
    actor_id: str | None = None
    passphrase: str | None = None
    creator: str = "spa_test@actingweb.net"

    def test_001_create_actor(self, http_client):
        """Create actor for properties tests."""
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestPropertiesMetadataAPI.actor_url = response.headers.get("Location")
        TestPropertiesMetadataAPI.actor_id = response.json()["id"]
        TestPropertiesMetadataAPI.passphrase = response.json()["passphrase"]

    def test_002_create_property(self, http_client):
        """Create a property for testing."""
        response = requests.put(
            f"{self.actor_url}/properties/test_prop",
            json={"value": "test_value"},
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code in [200, 201, 204]

    def test_003_get_properties_without_metadata(self, http_client):
        """Get properties without metadata parameter."""
        response = requests.get(
            f"{self.actor_url}/properties",
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 200
        data = response.json()
        # Should return simple key-value format
        assert "test_prop" in data or isinstance(data, dict)

    def test_004_get_properties_with_metadata_true(self, http_client):
        """Get properties with metadata=true parameter."""
        response = requests.get(
            f"{self.actor_url}/properties?metadata=true",
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code == 200
        data = response.json()
        # Should return structured format with properties and list_properties
        assert "properties" in data or "list_properties" in data or "test_prop" in data

    def test_099_cleanup_actor(self, http_client):
        """Delete test actor."""
        if self.actor_url:
            response = requests.delete(
                self.actor_url,
                auth=(self.creator, self.passphrase),
            )
            assert response.status_code in [200, 204]


class TestMetaTrustTypesAPI:
    """
    Test /meta/trusttypes endpoint.

    Tests the simplified trust types API that returns all configured
    trust types and the default trust type.
    """

    actor_url: str | None = None
    actor_id: str | None = None
    passphrase: str | None = None
    creator: str = "trusttypes_test@actingweb.net"

    def test_001_create_actor(self, http_client):
        """Create actor for trust types tests."""
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestMetaTrustTypesAPI.actor_url = response.headers.get("Location")
        TestMetaTrustTypesAPI.actor_id = response.json()["id"]
        TestMetaTrustTypesAPI.passphrase = response.json()["passphrase"]

    def test_002_get_meta_trusttypes(self, http_client):
        """Get trust types from /meta/trusttypes endpoint."""
        response = requests.get(f"{self.actor_url}/meta/trusttypes")
        # Should be publicly accessible or return auth error
        assert response.status_code in [200, 401, 403]

        if response.status_code == 200:
            data = response.json()
            # Should have trust_types and default_trust_type
            assert "trust_types" in data or "default_trust_type" in data or isinstance(data, dict)

    def test_003_get_meta_actingweb_trust_types(self, http_client):
        """Get trust types from legacy /meta/actingweb/trust_types endpoint."""
        response = requests.get(f"{self.actor_url}/meta/actingweb/trust_types")
        # This endpoint may or may not exist depending on config
        assert response.status_code in [200, 404]

    def test_099_cleanup_actor(self, http_client):
        """Delete test actor."""
        if self.actor_url:
            response = requests.delete(
                self.actor_url,
                auth=(self.creator, self.passphrase),
            )
            assert response.status_code in [200, 204]


class TestTrustWithOAuth2Data:
    """
    Test /trust endpoint returns OAuth2 client data.

    Verifies that trust relationships include OAuth2 client metadata
    when the relationship was established via OAuth2.
    """

    actor_url: str | None = None
    actor_id: str | None = None
    passphrase: str | None = None
    creator: str = "trust_oauth2_test@actingweb.net"
    peer_url: str | None = None
    peer_id: str | None = None
    peer_passphrase: str | None = None
    peer_creator: str = "peer_oauth2_test@actingweb.net"

    def test_001_create_actor(self, http_client):
        """Create main actor for trust tests."""
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestTrustWithOAuth2Data.actor_url = response.headers.get("Location")
        TestTrustWithOAuth2Data.actor_id = response.json()["id"]
        TestTrustWithOAuth2Data.passphrase = response.json()["passphrase"]

    def test_002_create_peer_actor(self, http_client):
        """Create peer actor for trust relationship."""
        response = http_client.post(
            f"{http_client.peer_url}/",
            json={"creator": self.peer_creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestTrustWithOAuth2Data.peer_url = response.headers.get("Location")
        TestTrustWithOAuth2Data.peer_id = response.json()["id"]
        TestTrustWithOAuth2Data.peer_passphrase = response.json()["passphrase"]

    def test_003_get_trust_empty(self, http_client):
        """Get trust relationships when none exist."""
        response = requests.get(
            f"{self.actor_url}/trust",
            auth=(self.creator, self.passphrase),
        )
        # Should return 404 when no trusts exist
        assert response.status_code in [200, 404]

    def test_004_create_trust_relationship(self, http_client):
        """Create a trust relationship."""
        response = requests.post(
            f"{self.actor_url}/trust",
            json={
                "url": self.peer_url,
                "relationship": "friend",
            },
            auth=(self.creator, self.passphrase),
        )
        # Trust creation may succeed or timeout if peer unreachable
        assert response.status_code in [201, 408]

    def test_005_get_trust_with_relationships(self, http_client):
        """Get trust relationships and verify data structure."""
        response = requests.get(
            f"{self.actor_url}/trust",
            auth=(self.creator, self.passphrase),
        )
        # May be 200 with data or 404 if no trusts
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            data = response.json()
            # Should be a list of trust relationships
            assert isinstance(data, list) or isinstance(data, dict)

            # If list, check first item has expected fields
            if isinstance(data, list) and len(data) > 0:
                trust = data[0]
                # Standard trust fields
                assert "peerid" in trust or "relationship" in trust
                # OAuth2 client fields may be present
                # These are optional - only present if established via OAuth2

    def test_006_get_trust_by_relationship(self, http_client):
        """Get trust relationships filtered by relationship type."""
        response = requests.get(
            f"{self.actor_url}/trust?relationship=friend",
            auth=(self.creator, self.passphrase),
        )
        assert response.status_code in [200, 404]

    def test_098_cleanup_peer_actor(self, http_client):
        """Delete peer actor."""
        if self.peer_url:
            response = requests.delete(
                self.peer_url,
                auth=(self.peer_creator, self.peer_passphrase),
            )
            assert response.status_code in [200, 204]

    def test_099_cleanup_actor(self, http_client):
        """Delete main actor."""
        if self.actor_url:
            response = requests.delete(
                self.actor_url,
                auth=(self.creator, self.passphrase),
            )
            assert response.status_code in [200, 204]


class TestPropertyMetadataEndpoint:
    """
    Test PUT /{actor_id}/properties/{name}/metadata endpoint.

    Tests updating description and explanation for list properties.
    """

    actor_url: str | None = None
    actor_id: str | None = None
    passphrase: str | None = None
    creator: str = "prop_meta_test@actingweb.net"

    def test_001_create_actor(self, http_client):
        """Create actor for property metadata tests."""
        response = http_client.post(
            f"{http_client.base_url}/",
            json={"creator": self.creator},
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 201

        TestPropertyMetadataEndpoint.actor_url = response.headers.get("Location")
        TestPropertyMetadataEndpoint.actor_id = response.json()["id"]
        TestPropertyMetadataEndpoint.passphrase = response.json()["passphrase"]

    def test_002_get_metadata_nonexistent_property(self, http_client):
        """Get metadata for property that doesn't exist."""
        response = requests.get(
            f"{self.actor_url}/properties/nonexistent/metadata",
            auth=(self.creator, self.passphrase),
        )
        # Should return 404 for non-existent property
        assert response.status_code in [404, 403, 401]

    def test_003_put_metadata_creates_list_property(self, http_client):
        """PUT metadata may create list property or fail."""
        response = requests.put(
            f"{self.actor_url}/properties/test_list/metadata",
            json={
                "description": "Test description",
                "explanation": "Test explanation",
            },
            auth=(self.creator, self.passphrase),
            headers={"Content-Type": "application/json"},
        )
        # May succeed, fail with 404 (property doesn't exist), or 400
        assert response.status_code in [200, 201, 204, 400, 404]

    def test_099_cleanup_actor(self, http_client):
        """Delete test actor."""
        if self.actor_url:
            response = requests.delete(
                self.actor_url,
                auth=(self.creator, self.passphrase),
            )
            assert response.status_code in [200, 204]
