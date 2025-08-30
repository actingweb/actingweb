"""
Test that the trustpermissions feature tag is properly included in /meta/actingweb/supported
when the unified access control system is available.
"""

import unittest
from unittest.mock import Mock, patch
from actingweb.config import Config


class TestTrustPermissionsFeatureTag(unittest.TestCase):

    def test_trustpermissions_tag_included_when_available(self):
        """Test that trustpermissions tag is included when permission system is available."""
        # The permission system should be available in this test environment
        config = Config()
        
        # Check that the trustpermissions tag is in the supported list
        self.assertIn("trustpermissions", config.aw_supported)
        
        # Verify it's a properly formatted comma-separated list
        supported_tags = config.aw_supported.split(",")
        self.assertIn("trustpermissions", supported_tags)
        
    def test_trustpermissions_tag_not_included_when_unavailable(self):
        """Test that trustpermissions tag is not included when permission system is unavailable."""
        
        # Mock the import to fail, simulating unavailable permission system
        with patch.object(Config, '_check_trust_permissions_available', return_value=False):
            config = Config()
            
            # Check that the trustpermissions tag is NOT in the supported list
            self.assertNotIn("trustpermissions", config.aw_supported)
            
            # But other standard tags should still be there
            self.assertIn("trust", config.aw_supported)
            self.assertIn("www", config.aw_supported)
            
    def test_mcp_tag_included_when_enabled(self):
        """Test that mcp tag is included when MCP is enabled."""
        config = Config(mcp=True)
        
        # Check that the mcp tag is in the supported list
        self.assertIn("mcp", config.aw_supported)
        
    def test_mcp_tag_not_included_when_disabled(self):
        """Test that mcp tag is not included when MCP is disabled."""
        config = Config(mcp=False)
        
        # Check that the mcp tag is NOT in the supported list
        self.assertNotIn("mcp", config.aw_supported)
        
    def test_check_trust_permissions_available_method(self):
        """Test the _check_trust_permissions_available method directly."""
        config = Config()
        
        # Since the permission system modules exist in this test environment,
        # the method should return True
        self.assertTrue(config._check_trust_permissions_available())
        
    def test_meta_endpoint_includes_trustpermissions_tag(self):
        """Test that the meta endpoint includes the trustpermissions tag in its response."""
        from actingweb.handlers.meta import MetaHandler
        from unittest.mock import Mock
        
        # Mock the dependencies
        config = Config()
        handler = MetaHandler()
        handler.config = config
        handler.response = Mock()
        handler.response.headers = {}
        
        # Mock the auth system to return a valid actor and check
        mock_actor = Mock()
        mock_actor.store = Mock()
        mock_actor.store.trustee_root = None
        
        mock_check = Mock()
        mock_check.check_authorisation = Mock(return_value=True)
        
        with patch('actingweb.handlers.meta.auth.init_actingweb', return_value=(mock_actor, mock_check)):
            # Call the meta handler for the supported endpoint
            handler.get("test-actor", "actingweb/supported")
            
            # Verify the response was written
            handler.response.write.assert_called_once()
            
            # Get the written content and verify it contains trustpermissions
            written_content = handler.response.write.call_args[0][0]
            self.assertIn("trustpermissions", written_content)


if __name__ == '__main__':
    unittest.main()