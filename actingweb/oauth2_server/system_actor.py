"""
Shared utility for OAuth2 system actor management.

The OAuth2 system actor (_actingweb_oauth2) is used for:
1. Storing OAuth2 state encryption keys
2. Serving as the default actor for MCP client registrations
3. Managing the global client index

This module provides a single, reusable function to ensure the system actor exists.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .. import config as config_class

logger = logging.getLogger(__name__)


def ensure_oauth2_system_actor(config: "config_class.Config") -> str:
    """
    Ensure the OAuth2 system actor exists, creating it if necessary.

    This function is idempotent - it can be called multiple times safely.
    It handles race conditions where multiple processes try to create the
    actor concurrently.

    Args:
        config: ActingWeb configuration object

    Returns:
        The system actor ID (OAUTH2_SYSTEM_ACTOR constant)

    Raises:
        No exceptions - errors are logged as warnings
    """
    from botocore.exceptions import ClientError

    from .. import actor as actor_module
    from ..constants import OAUTH2_SYSTEM_ACTOR

    try:
        # Check if system actor already exists
        sys_actor = actor_module.Actor(OAUTH2_SYSTEM_ACTOR, config=config)

        if not sys_actor.actor:
            # Actor doesn't exist, create it
            base_root = config.root if hasattr(config, "root") else "http://localhost/"
            url = f"{base_root}{OAUTH2_SYSTEM_ACTOR}"
            passphrase = (
                config.new_token()
                if hasattr(config, "new_token")
                else "oauth2-system-pass"
            )

            try:
                created = sys_actor.create(
                    url=url,
                    creator="oauth2-system",
                    passphrase=passphrase,
                    actor_id=OAUTH2_SYSTEM_ACTOR,
                )
                if created:
                    logger.info(f"Created OAuth2 system actor: {OAUTH2_SYSTEM_ACTOR}")
                else:
                    logger.error(
                        f"Failed to create OAuth2 system actor: {OAUTH2_SYSTEM_ACTOR}"
                    )
            except ClientError as e:
                if e.response["Error"]["Code"] == "ResourceInUseException":
                    # Actor was created by another process concurrently - this is fine
                    logger.debug("OAuth2 system actor was created by another process")
                else:
                    logger.error(f"Error creating OAuth2 system actor: {e}")
                    # Don't raise - allow callers to continue even if actor creation failed
        else:
            logger.debug(f"OAuth2 system actor already exists: {OAUTH2_SYSTEM_ACTOR}")

    except Exception as e:
        # Log but don't fail - callers should handle missing actor gracefully
        logger.warning(f"Could not ensure OAuth2 system actor exists: {e}")

    return OAUTH2_SYSTEM_ACTOR
