#!/usr/bin/env python3
"""
Type checking script for ActingWeb modern interface.
"""

from typing import TYPE_CHECKING
import sys

def check_imports():
    """Check that all modules can be imported without errors."""
    try:
        from actingweb.interface import (
            ActingWebApp, 
            ActorInterface, 
            PropertyStore, 
            TrustManager, 
            SubscriptionManager,
            HookRegistry
        )
        print("✓ All interface modules imported successfully")
        return True
    except ImportError as e:
        print(f"✗ Import error: {e}")
        return False

def check_type_annotations():
    """Check that type annotations are working correctly."""
    try:
        from actingweb.interface import ActingWebApp, ActorInterface
        
        # Test basic type annotations
        app: ActingWebApp = ActingWebApp(
            aw_type="urn:test:example.com:test",
            database="dynamodb"
        )
        
        # Test method chaining
        configured_app = app.with_web_ui().with_devtest()
        
        # Test type hints work with IDE/mypy
        def test_actor_factory(creator: str) -> ActorInterface:
            return ActorInterface.create(creator=creator, config=app.get_config())
        
        print("✓ Type annotations are working correctly")
        return True
    except Exception as e:
        print(f"✗ Type annotation error: {e}")
        return False

def check_hook_types():
    """Check that hook type annotations are working."""
    try:
        from actingweb.interface import ActingWebApp, ActorInterface
        from typing import Any, Dict, Optional, List
        
        app = ActingWebApp(
            aw_type="urn:test:example.com:test",
            database="dynamodb"
        )
        
        # Test property hook types
        @app.property_hook("test")
        def test_property_hook(actor: ActorInterface, operation: str, value: Any, path: List[str]) -> Optional[Any]:
            return value
        
        # Test callback hook types
        @app.callback_hook("test")
        def test_callback_hook(actor: ActorInterface, name: str, data: Dict[str, Any]) -> bool:
            return True
        
        # Test subscription hook types
        @app.subscription_hook
        def test_subscription_hook(actor: ActorInterface, subscription: Dict[str, Any], peer_id: str, data: Dict[str, Any]) -> bool:
            return True
        
        # Test lifecycle hook types
        @app.lifecycle_hook("test")
        def test_lifecycle_hook(actor: ActorInterface, **kwargs: Any) -> None:
            pass
        
        print("✓ Hook type annotations are working correctly")
        return True
    except Exception as e:
        print(f"✗ Hook type annotation error: {e}")
        return False

if __name__ == "__main__":
    print("Running type checks for ActingWeb modern interface...")
    print("=" * 60)
    
    success = True
    
    success &= check_imports()
    success &= check_type_annotations()
    success &= check_hook_types()
    
    print("=" * 60)
    if success:
        print("✓ All type checks passed!")
        print("The modern interface has proper type annotations.")
    else:
        print("✗ Some type checks failed!")
        sys.exit(1)