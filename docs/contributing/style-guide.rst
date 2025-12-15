=============
Style Guide
=============

**Audience**: Contributors to the ActingWeb codebase.

This guide covers code style, type annotations, and conventions used in the ActingWeb project.

Code Quality Standards
======================

The ActingWeb project maintains **zero errors and zero warnings** for both type checking and linting.

Current Status
--------------

- Pyright: 0 errors, 0 warnings
- Ruff: All checks passing
- Tests: 100% passing

Running Checks
--------------

Before committing, always run:

.. code-block:: bash

    # Type checking
    poetry run pyright actingweb tests

    # Linting
    poetry run ruff check actingweb tests

    # Formatting
    poetry run ruff format actingweb tests

    # Tests
    poetry run pytest tests/

Type Annotations
================

Always use proper type annotations:

.. code-block:: python

    # Good - explicit types
    def handle_method(
        actor: ActorInterface,
        method_name: str,
        data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        return {"result": "success"}

    # Bad - missing types
    def handle_method(actor, method_name, data):
        return {"result": "success"}

Common Type Patterns
--------------------

**Optional values**:

.. code-block:: python

    from typing import Optional

    def get_value(key: str) -> Optional[str]:
        return self._data.get(key)

**Union types**:

.. code-block:: python

    from typing import Union

    body: Union[str, bytes, None] = request.body

**Callable types**:

.. code-block:: python

    from typing import Callable, Any

    def register_hook(self, func: Callable[..., Any]) -> None:
        pass

**Dict and List**:

.. code-block:: python

    from typing import Dict, List, Any

    def process(data: Dict[str, Any]) -> List[str]:
        return list(data.keys())

Null Safety
===========

Always check for None before using optional values:

.. code-block:: python

    # Good
    result = some_method()
    if result is not None:
        process(result)

    # Bad
    result = some_method()
    process(result)  # May be None!

Early returns for None checks:

.. code-block:: python

    def process(actor_id: str) -> Dict[str, Any]:
        actor = get_actor(actor_id)
        if actor is None:
            return {"error": "Not found"}

        # Continue with actor guaranteed non-None
        return {"id": actor.id}

Method Overrides
================

Match base class signatures exactly:

.. code-block:: python

    # Good - matches base class
    def method(self, param1: str, param2: Dict[str, Any]) -> bool:
        ...

    # Bad - different parameter names
    def method(self, param1: str, _param2: Dict[str, Any]) -> bool:
        ...

Import Management
=================

Remove unused imports:

.. code-block:: python

    # Good
    from typing import Dict, Optional

    # Bad - List and Union not used
    from typing import Dict, Optional, List, Union

Use TYPE_CHECKING for forward references:

.. code-block:: python

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from .some_module import SomeClass

Docstrings
==========

Use Google-style docstrings:

.. code-block:: python

    def create_trust(
        self,
        peer_id: str,
        relationship: str,
        baseuri: str
    ) -> Optional[Dict[str, Any]]:
        """Create a trust relationship with a peer.

        Args:
            peer_id: Unique identifier for the peer
            relationship: Type of relationship (e.g., "friend")
            baseuri: Base URI of the peer's actor

        Returns:
            Trust record dict if successful, None if failed

        Raises:
            ValueError: If peer_id is empty
        """
        pass

Error Handling
==============

Use specific exceptions:

.. code-block:: python

    # Good
    raise ValueError("peer_id cannot be empty")
    raise PermissionError("Not authorized to access this resource")

    # Bad
    raise Exception("Error")

Handle exceptions appropriately:

.. code-block:: python

    try:
        result = risky_operation()
    except SpecificError as e:
        logger.error(f"Operation failed: {e}")
        return None
    except Exception as e:
        logger.exception("Unexpected error")
        raise

Logging
=======

Use module-level loggers:

.. code-block:: python

    import logging

    logger = logging.getLogger(__name__)

    def process():
        logger.debug("Starting process")
        logger.info("Process completed")
        logger.warning("Unexpected state")
        logger.error("Operation failed")

Naming Conventions
==================

**Classes**: PascalCase

.. code-block:: python

    class ActorInterface:
    class PropertyStore:

**Functions/Methods**: snake_case

.. code-block:: python

    def get_properties():
    def create_trust_relationship():

**Constants**: UPPER_SNAKE_CASE

.. code-block:: python

    DEFAULT_TIMEOUT = 30
    MAX_RETRIES = 3

**Private members**: Leading underscore

.. code-block:: python

    self._internal_state = {}
    def _helper_method(self):

**Async methods**: Suffix with ``_async``

.. code-block:: python

    async def create_trust_async():
    async def get_peer_info_async():

Code Organization
=================

Imports order:

.. code-block:: python

    # Standard library
    import logging
    import json
    from typing import Dict, Optional

    # Third-party
    import httpx
    from pynamodb.models import Model

    # Local
    from actingweb.config import Config
    from actingweb.interface import ActorInterface

Class organization:

.. code-block:: python

    class MyClass:
        # Class variables
        DEFAULT_VALUE = 10

        # __init__
        def __init__(self, ...):
            pass

        # Properties
        @property
        def value(self):
            pass

        # Public methods
        def public_method(self):
            pass

        # Private methods
        def _private_method(self):
            pass

        # Class methods
        @classmethod
        def from_config(cls, config):
            pass

        # Static methods
        @staticmethod
        def utility_function():
            pass

Testing Conventions
===================

Test file naming:

.. code-block::

    tests/test_<module>.py
    tests/integration/test_<feature>.py

Test function naming:

.. code-block:: python

    def test_<function>_<scenario>():
    def test_create_trust_with_valid_peer():
    def test_create_trust_with_invalid_peer_raises_error():

Test structure (Arrange-Act-Assert):

.. code-block:: python

    def test_property_set():
        # Arrange
        actor = create_test_actor()
        store = PropertyStore(actor)

        # Act
        store["key"] = "value"

        # Assert
        assert store["key"] == "value"

Git Commit Messages
===================

Format:

.. code-block::

    <type>: <description>

    <body>

    <footer>

Types:

- ``feat``: New feature
- ``fix``: Bug fix
- ``docs``: Documentation
- ``refactor``: Code refactoring
- ``test``: Adding tests
- ``chore``: Maintenance

Example:

.. code-block::

    feat: Add async variants to TrustManager

    - Added create_reciprocal_trust_async()
    - Added delete_peer_trust_async()
    - Updated tests

    Closes #123

See Also
========

- :doc:`architecture` - Codebase architecture
- :doc:`testing` - Testing guide
- `PEP 8 <https://peps.python.org/pep-0008/>`_ - Python style guide
- `Google Python Style Guide <https://google.github.io/styleguide/pyguide.html>`_
