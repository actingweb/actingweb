"""
Process-wide DynamoDB table-existence guard.

Historically every ``Db*`` accessor ``__init__`` ran
``if not Model.exists(): Model.create_table(wait=True)``. pynamodb's
``exists()`` always issues a live ``DescribeTable`` control-plane call (it
populates its metadata cache but never reads from it), so every accessor
construction paid a network round trip — measured at >1,000 calls/minute in
a near-idle production deployment. ``ensure_table()`` collapses that to at
most one check per model class per process.

Auto-creation can be disabled entirely for deployments that manage tables
via infrastructure-as-code (CloudFormation/Terraform):

- environment: ``AWS_DB_AUTO_CREATE_TABLES=false`` (default: enabled), or
- fluent API: ``ActingWebApp(...).with_dynamodb(auto_create_tables=False)``.

With auto-creation disabled, neither ``DescribeTable`` nor ``CreateTable``
is ever called, so both permissions can be dropped from the runtime IAM
role.
"""

import logging
import os
import threading

from pynamodb.models import Model

logger = logging.getLogger(__name__)

# Model classes whose table is known to exist. Keyed by class (not
# Meta.table_name) so distinct model classes sharing a table name — e.g. a
# legacy and a current schema variant — are tracked independently.
_ensured: set[type[Model]] = set()
_lock = threading.Lock()

# Tri-state override set via set_auto_create(); None means "consult the
# AWS_DB_AUTO_CREATE_TABLES environment variable".
_auto_create_override: bool | None = None
_flag_logged = False


def auto_create_enabled() -> bool:
    """Whether table auto-creation is currently enabled (override, else env)."""
    if _auto_create_override is not None:
        return _auto_create_override
    return os.getenv("AWS_DB_AUTO_CREATE_TABLES", "true").strip().lower() not in (
        "false",
        "0",
        "no",
    )


def set_auto_create(enabled: bool) -> None:
    """Programmatically enable/disable table auto-creation.

    Takes precedence over the ``AWS_DB_AUTO_CREATE_TABLES`` environment
    variable. Must be called before the first database access to be fully
    effective; a warning is logged if tables have already been ensured.
    """
    global _auto_create_override
    with _lock:
        if _ensured and not enabled:
            logger.warning(
                "set_auto_create(False) called after %d table(s) were already "
                "ensured; the setting only affects tables not yet accessed. "
                "Configure it before the first database access.",
                len(_ensured),
            )
        _auto_create_override = enabled


def ensure_table(model: type[Model]) -> None:
    """Create the model's table if absent — at most once per process per model.

    No-op when auto-creation is disabled (the caller's subsequent data-plane
    operation will fail loudly if the table genuinely does not exist).
    """
    global _flag_logged
    if model in _ensured:
        return
    if not auto_create_enabled():
        # Skip exists() too: production roles without dynamodb:DescribeTable
        # must not pay (or leak) an AccessDenied on every construction.
        if not _flag_logged:
            _flag_logged = True
            logger.info(
                "DynamoDB table auto-creation is disabled; tables are assumed "
                "to be managed externally."
            )
        return
    with _lock:
        if model in _ensured:
            return
        if not model.exists():
            try:
                model.create_table(wait=True)
                logger.info("Created DynamoDB table %s", model.Meta.table_name)
            except Exception as e:
                # Another process may have created the table between the
                # exists() check and create_table(). Anything else (including
                # AccessDenied) must propagate: swallowing it would turn a
                # configuration error into silent data loss.
                if "ResourceInUseException" not in str(e):
                    raise
        # Only reached on success — never cache a negative.
        _ensured.add(model)


def reset_ensure_cache() -> None:
    """Forget which tables were ensured (test hook).

    Must be called by any code that deletes tables in-process (e.g. the
    integration-test cleanup), otherwise ensure_table() keeps asserting a
    deleted table exists. Does not reset the auto-create override.
    """
    with _lock:
        _ensured.clear()
