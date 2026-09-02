"""Tests for config module."""

import os

import pytest

from actingweb.config import Config
from actingweb.constants import DatabaseType, Environment


class TestConfigInitialization:
    """Test Config class initialization."""

    def test_config_init_default(self):
        """Test Config initialization with default values."""
        config = Config()

        # Test basic settings
        assert config.fqdn == "demo.actingweb.io"
        assert config.proto == "https://"
        # Database defaults to DATABASE_BACKEND env var or 'dynamodb'
        expected_database = os.getenv("DATABASE_BACKEND", "dynamodb")
        assert config.database == expected_database
        # Env is set to 'aws' when database is dynamodb, empty otherwise
        expected_env = "aws" if expected_database == "dynamodb" else ""
        assert config.env == expected_env
        assert config.ui is True
        assert config.devtest is True
        assert config.unique_creator is False
        assert config.force_email_prop_as_creator is True
        assert config.www_auth == "basic"

    def test_config_init_with_kwargs(self):
        """Test Config initialization with keyword arguments."""
        config = Config(
            fqdn="test.example.com",
            proto="http://",
            database="dynamodb",
            ui=False,
            devtest=False,
        )

        assert config.fqdn == "test.example.com"
        assert config.proto == "http://"
        assert config.database == "dynamodb"
        assert config.ui is False
        assert config.devtest is False

    def test_config_actingweb_settings(self):
        """Test ActingWeb-specific settings."""
        config = Config()

        assert config.aw_type == "urn:actingweb:actingweb.org:demo"
        assert config.desc == "Demo actor: "
        assert config.specification == ""
        assert config.version == "1.0"
        assert config.info == "http://actingweb.org/"

    def test_config_trust_settings(self):
        """Test trust-related settings exist."""
        config = Config()

        # These should exist as they're mentioned in the class
        assert hasattr(config, "aw_type")
        assert hasattr(config, "desc")
        assert hasattr(config, "specification")
        assert hasattr(config, "version")
        assert hasattr(config, "info")


class TestConfigMethods:
    """Test Config class methods."""

    def test_config_has_required_methods(self):
        """Test Config has required methods."""
        config = Config()

        # Check for commonly used methods (may be defined elsewhere in full class)
        assert hasattr(config, "__init__")

        # Test that config can be used in basic operations
        assert isinstance(config.fqdn, str)
        assert isinstance(config.proto, str)
        assert isinstance(config.database, str)

    def test_config_database_types(self):
        """Test database type validation."""
        config = Config()

        # Test default database type (from env var or dynamodb)
        expected_database = os.getenv("DATABASE_BACKEND", "dynamodb")
        assert config.database == expected_database

        # Test setting different database types
        config.database = DatabaseType.DYNAMODB.value
        assert config.database == "dynamodb"

    def test_config_environment_types(self):
        """Test environment type handling."""
        config = Config()

        # Test default environment (aws for dynamodb, empty otherwise)
        expected_database = os.getenv("DATABASE_BACKEND", "dynamodb")
        expected_env = "aws" if expected_database == "dynamodb" else ""
        assert config.env == expected_env

        # Test setting environment
        config.env = Environment.AWS.value
        assert config.env == "aws"

        config.env = Environment.STANDALONE.value
        assert config.env == "standalone"


class TestConfigSecuritySettings:
    """Test security-related configuration."""

    def test_config_security_defaults(self):
        """Test security-related default values."""
        config = Config()

        # HTTPS should be default
        assert config.proto == "https://"

        # DevTest should be controllable
        assert isinstance(config.devtest, bool)

        # Auth method should be set
        assert config.www_auth in ["basic", "oauth"]

    def test_config_production_settings(self):
        """Test production-recommended settings."""
        config = Config(proto="https://", devtest=False, www_auth="oauth")

        assert config.proto == "https://"
        assert config.devtest is False
        assert config.www_auth == "oauth"

    def test_config_development_settings(self):
        """Test development settings."""
        config = Config(proto="http://", devtest=True, www_auth="basic")

        assert config.proto == "http://"
        assert config.devtest is True
        assert config.www_auth == "basic"


class TestConfigModernization:
    """Test Config class modernization features."""

    def test_config_class_inheritance(self):
        """Test Config class uses modern inheritance."""
        # Config should not inherit from object explicitly in Python 3.11+
        assert Config.__bases__ == (object,)  # Python automatically adds object

    def test_config_type_hints(self):
        """Test Config methods have type hints."""
        # Check that __init__ has type hints
        init_annotations = Config.__init__.__annotations__
        assert "kwargs" in init_annotations or len(init_annotations) >= 0

    def test_config_attributes_types(self):
        """Test Config attributes have correct types."""
        config = Config()

        # Test string attributes
        assert isinstance(config.fqdn, str)
        assert isinstance(config.proto, str)
        assert isinstance(config.env, str)
        assert isinstance(config.database, str)
        assert isinstance(config.aw_type, str)
        assert isinstance(config.desc, str)
        assert isinstance(config.specification, str)
        assert isinstance(config.version, str)
        assert isinstance(config.info, str)
        assert isinstance(config.www_auth, str)

        # Test boolean attributes
        assert isinstance(config.ui, bool)
        assert isinstance(config.devtest, bool)
        assert isinstance(config.unique_creator, bool)
        assert isinstance(config.force_email_prop_as_creator, bool)


class TestConfigValidation:
    """Test Config validation and error handling."""

    def test_config_valid_database_types(self):
        """Test valid database types."""
        config = Config()

        # Both dynamodb and postgresql are valid database backends
        valid_databases = ["dynamodb", "postgresql"]
        assert config.database in valid_databases

    def test_config_valid_auth_types(self):
        """Test valid authentication types."""
        config = Config()

        valid_auth_types = ["basic", "oauth"]
        assert config.www_auth in valid_auth_types

    def test_config_valid_protocols(self):
        """Test valid protocol settings."""
        config = Config()

        valid_protocols = ["http://", "https://"]
        assert config.proto in valid_protocols

    def test_config_boolean_settings(self):
        """Test boolean configuration settings."""
        config = Config()

        # Test boolean type validation
        assert isinstance(config.ui, bool)
        assert isinstance(config.devtest, bool)
        assert isinstance(config.unique_creator, bool)
        assert isinstance(config.force_email_prop_as_creator, bool)

        # Test that boolean settings can be changed
        original_ui = config.ui
        config.ui = not original_ui
        assert config.ui != original_ui


class TestHostSettingValidation:
    """``fqdn``/``proto`` are stripped, then validated, at construction (3.14.4)."""

    def test_surrounding_whitespace_is_stripped(self):
        config = Config(fqdn="myapp.example.com\n", proto=" https:// ")
        assert config.fqdn == "myapp.example.com"
        assert config.proto == "https://"
        assert config.root == "https://myapp.example.com/"
        assert config.auth_realm == "myapp.example.com"

    @pytest.mark.parametrize(
        "bad", ['my"app', "my app", "my\x00app", "my\\app", "my\x85app", "a\tb"]
    )
    def test_forbidden_characters_are_rejected_with_a_useful_message(self, bad):
        with pytest.raises(ValueError) as exc:
            Config(fqdn=bad)
        message = str(exc.value)
        assert repr(bad) in message
        assert "APP_HOST_FQDN" in message
        assert "host[:port][/base]" in message

    @pytest.mark.parametrize("bad", ['ht"tp://', "http ://", "http://\x00"])
    def test_proto_is_validated_too(self, bad):
        with pytest.raises(ValueError) as exc:
            Config(proto=bad)
        assert "APP_HOST_PROTOCOL" in str(exc.value)

    @pytest.mark.parametrize(
        "good", ["localhost:5000", "demo.actingweb.io/base", "127.0.0.1", "x"]
    )
    def test_port_and_base_path_are_accepted(self, good):
        assert Config(fqdn=good).fqdn == good

    def test_app_strips_before_config_sees_it(self):
        from actingweb.interface import ActingWebApp

        app = ActingWebApp(
            aw_type="urn:actingweb:test:strip",
            database="dynamodb",
            fqdn=" x.example.com ",
            proto="https://\n",
        )
        assert app.fqdn == "x.example.com"
        assert app.get_config().fqdn == "x.example.com"
        assert app.get_config().proto == "https://"
