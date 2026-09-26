"""
ActingWeb Token Management for MCP clients.

This module manages ActingWeb tokens that are separate from Google OAuth2 tokens.
These tokens are issued to MCP clients and validated by MCP endpoints.
"""

import base64
import hashlib
import logging
import secrets
import time
from typing import Any

from .. import config as config_class
from ..constants import (
    ACCESS_TOKEN_INDEX_BUCKET,
    AUTH_CODE_INDEX_BUCKET,
    OAUTH2_SYSTEM_ACTOR,
    REFRESH_TOKEN_INDEX_BUCKET,
)
from ..secret_compare import secret_digest_equals, secret_equals
from ..single_use import PurgeThrottle

logger = logging.getLogger(__name__)


class TokenStoreUnavailable(Exception):
    """The MCP token store could not be read or could not confirm a write.

    Raised instead of answering "no such token" or reporting work that did
    not happen, so a caller can fail closed on a store fault rather than
    treat it as an invalid token:

    - token lookups (``validate_access_token``, the refresh and code grants);
    - the single-use consume, when the store cannot confirm it either way;
    - the client lookup at the token endpoint
      (``MCPClientRegistry.load_client_strict``);
    - revocation (``revoke_token``, a theft revocation, and
      ``revoke_client_tokens`` when a bucket is unreadable or a delete is
      unconfirmed).
    """


def _mask_token(token: str) -> str:
    """Mask a token for safe logging, showing only first 8 chars."""
    if not token or len(token) < 8:
        return "***"
    return f"{token[:8]}..."


class ActingWebTokenManager:
    """
    Manages ActingWeb tokens for MCP authentication.

    These tokens are separate from Google OAuth2 tokens and are used specifically
    for MCP client authentication. They are stored per-actor and linked to
    the user's Google OAuth2 identity.
    """

    def __init__(self, config: config_class.Config):
        self.config = config
        # Use Attributes system for private storage instead of underscore properties
        self.tokens_bucket = "mcp_tokens"  # Private attribute bucket for tokens
        self.refresh_tokens_bucket = (
            "mcp_refresh_tokens"  # Private attribute bucket for refresh tokens
        )
        self.auth_codes_bucket = (
            "mcp_auth_codes"  # Private attribute bucket for auth codes
        )
        self.google_tokens_bucket = (
            "mcp_google_tokens"  # Private attribute bucket for Google tokens
        )
        self.token_prefix = "aw_"  # Prefix to distinguish from Google tokens
        self.default_expires_in = 3600  # 1 hour
        self.refresh_token_expires_in = 2592000  # 30 days

    def create_authorization_code(
        self,
        actor_id: str,
        client_id: str,
        provider_token_data: dict[str, Any],
        user_email: str | None = None,
        trust_type: str | None = None,
        code_challenge: str | None = None,
        code_challenge_method: str | None = None,
        redirect_uri: str | None = None,
    ) -> str:
        """
        Create a temporary authorization code for OAuth2 flow.

        Args:
            actor_id: The actor this code is for
            client_id: The MCP client requesting authorization
            provider_token_data: OAuth2 token data from the upstream provider
            user_email: Email of the authenticated user, returned at exchange
            trust_type: Trust type established for the client
            code_challenge: PKCE challenge the code is bound to
            code_challenge_method: ``S256`` or ``plain``. Exchange validates
                against exactly this value; an absent method is not
                defaulted to ``plain`` and fails verification.
            redirect_uri: The redirect URI the code was issued for. When
                given, exchange refuses a different one (RFC 6749 §4.1.3).

        Returns:
            Authorization code to return to MCP client
        """
        # Generate authorization code
        auth_code = f"ac_{secrets.token_urlsafe(32)}"

        # Store provider token data in private attributes
        google_token_key = f"google_token_{auth_code}"
        self._store_google_token_data(actor_id, google_token_key, provider_token_data)

        # Store minimal authorization data (expires in 10 minutes)
        auth_data = {
            "code": auth_code,
            "actor_id": actor_id,
            "client_id": client_id,
            "google_token_key": google_token_key,  # Reference to stored Google data
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + 600,  # 10 minutes
            "used": False,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
        }
        if redirect_uri:
            auth_data["redirect_uri"] = redirect_uri
        if user_email:
            auth_data["user_email"] = user_email
        if trust_type:
            auth_data["trust_type"] = trust_type

        self._store_auth_code(actor_id, auth_code, auth_data)

        logger.debug(
            f"Created authorization code for client {client_id}, actor {actor_id}"
        )
        return auth_code

    def exchange_authorization_code(
        self,
        code: str,
        client_id: str,
        client_secret: str | None = None,
        code_verifier: str | None = None,
        redirect_uri: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Exchange authorization code for ActingWeb access token.

        A code is single-use, atomically: it is consumed with a
        compare-and-swap before PKCE is checked, so of two concurrent
        exchanges exactly one mints tokens, and a wrong verifier burns the
        code. The code row is deleted on success.

        Args:
            code: Authorization code from authorize endpoint
            client_id: MCP client identifier
            client_secret: MCP client secret (authenticated by the caller)
            code_verifier: PKCE code verifier (for public clients using PKCE)
            redirect_uri: The redirect URI of the token request; compared with
                the one the code was issued for when the code records one

        Returns:
            Token response with ActingWeb access token or None if invalid
        """
        # Load and validate authorization code
        auth_data = self._load_auth_code(code)
        if not auth_data:
            logger.warning(f"Invalid authorization code: {_mask_token(code)}")
            return None

        actor_id = auth_data["actor_id"]

        # Check if code has expired
        if int(time.time()) > auth_data["expires_at"]:
            logger.warning(f"Expired authorization code: {_mask_token(code)}")
            # Clean up both auth code and Google token data
            if "google_token_key" in auth_data:
                self._remove_google_token_data(actor_id, auth_data["google_token_key"])
            self._remove_auth_code(code)
            return None

        # Validate client
        if auth_data["client_id"] != client_id:
            logger.warning(f"Client ID mismatch for code {_mask_token(code)}")
            return None

        stored_redirect_uri = auth_data.get("redirect_uri")
        if stored_redirect_uri and stored_redirect_uri != redirect_uri:
            logger.warning(f"redirect_uri mismatch for code {_mask_token(code)}")
            return None

        # Consume the code before anything else can use it. A code that is
        # already used, or that a concurrent exchange consumed first, is
        # refused; the winner's tokens are left alone.
        consumed, _current = self._consume(
            actor_id, self.auth_codes_bucket, code, auth_data, consumed_ttl=None
        )
        if not consumed:
            logger.warning(f"Authorization code already used: {_mask_token(code)}")
            return None

        # PKCE validation, after the consume: a failed verifier burns the code.
        stored_challenge = auth_data.get("code_challenge")
        stored_method = str(auth_data.get("code_challenge_method"))

        if stored_challenge:  # PKCE was used in authorization
            pkce_ok = bool(code_verifier) and self._validate_pkce(
                code_verifier or "", stored_challenge, stored_method
            )
            if not pkce_ok:
                logger.warning(f"PKCE validation failed for code {_mask_token(code)}")
                if "google_token_key" in auth_data:
                    self._remove_google_token_data(
                        actor_id, auth_data["google_token_key"]
                    )
                self._remove_auth_code(code)
                return None

        # Load Google token data
        google_token_data = self._load_google_token_data(
            actor_id, auth_data["google_token_key"]
        )
        if not google_token_data:
            logger.error(
                f"Failed to load Google token data for auth code {_mask_token(code)}"
            )
            self._remove_auth_code(code)
            return None

        # Each authorization starts a new refresh-token chain.
        chain_id = self._new_chain_id()

        # Create ActingWeb access token
        access_token = self._create_access_token(
            actor_id, client_id, google_token_data, chain_id=chain_id
        )

        # Create refresh token
        refresh_token = self._create_refresh_token(
            actor_id,
            client_id,
            access_token["token"],
            access_token_id=access_token["token_id"],
            chain_id=chain_id,
            google_token_key=access_token.get("google_token_key"),
        )

        # Clean up authorization code and Google token data
        self._remove_google_token_data(actor_id, auth_data["google_token_key"])
        self._remove_auth_code(code)

        # Return token response
        # Prepare extra context for trust creation at token issuance
        user_email = auth_data.get("user_email")
        trust_type = auth_data.get("trust_type", "mcp_client")

        return {
            "access_token": access_token["token"],
            "token_type": "Bearer",
            "expires_in": access_token["expires_in"],
            "refresh_token": refresh_token["token"],
            "scope": "mcp",  # MCP scope
            "actor_id": actor_id,
            "email": user_email,
            "trust_type": trust_type,
        }

    def validate_access_token(
        self, token: str
    ) -> tuple[str, str, dict[str, Any]] | None:
        """
        Validate ActingWeb access token.

        Args:
            token: ActingWeb access token

        Returns:
            Tuple of (actor_id, client_id, token_data) or None if invalid

        Raises:
            TokenStoreUnavailable: the token store could not be read. This is
                not an invalid token; callers should fail closed (the MCP
                endpoint answers 503).
        """
        if not token.startswith(self.token_prefix):
            return None

        token_data = self._load_access_token(token)
        if not token_data:
            return None

        # Check if token has expired
        if int(time.time()) > token_data["expires_at"]:
            logger.debug(f"Access token expired: {_mask_token(token)}")
            self._remove_access_token(token)
            return None

        return token_data["actor_id"], token_data["client_id"], token_data

    def refresh_access_token(
        self, refresh_token: str, client_id: str, client_secret: str | None = None
    ) -> dict[str, Any] | None:
        """
        Rotate a refresh token: issue a new access token and a new refresh
        token, and consume the presented one.

        Refresh tokens are single-use (RFC 9700 §4.14.2). The presented token
        is consumed with a compare-and-swap; the access token it was issued
        with is deleted and popped from this process's MCP token cache. A
        consumed token presented again is judged by how long ago it was used:

        - within ``MCP_REFRESH_TOKEN_GRACE_PERIOD`` (60 s): a concurrent
          request, or a client that lost the previous response; it rotates
          again in the same chain and nothing is revoked;
        - within ``MCP_REFRESH_TOKEN_REUSE_WINDOW`` (2 days): potential theft;
          every token in the chain is revoked and the grant fails;
        - beyond the window: expired, not theft; the row is removed and
          nothing is revoked (storage TTLs lag, so the row can outlive it).

        The grace period is also the recovery contract when minting fails
        after the consume (a storage fault): the grant errors, the client
        still holds a consumed token, and a retry within 60 s rotates; a
        retry after 60 s reads as theft.

        Every rotation stamps a fresh 30-day expiry on the new refresh token,
        so the lifetime is sliding: 30 days of inactivity ends a chain.

        Args:
            refresh_token: Refresh token
            client_id: MCP client identifier (must match the token's)
            client_secret: Client secret (authenticated by the caller)

        Returns:
            New token response, including the new ``refresh_token``, or None
            if the token is invalid, expired, reused or not the client's.

        Raises:
            TokenStoreUnavailable: the token could not be read, the consume
                could not be confirmed either way, or a theft revocation
                could not be completed. The token is left for a retry.
        """
        from ..constants import (
            INDEX_TTL_BUFFER,
            MCP_REFRESH_TOKEN_GRACE_PERIOD,
            MCP_REFRESH_TOKEN_REUSE_WINDOW,
        )

        refresh_data = self._load_refresh_token(refresh_token)
        if not refresh_data:
            logger.warning("Invalid refresh token")
            return None

        # Check if refresh token has expired
        if int(time.time()) > refresh_data["expires_at"]:
            logger.warning("Refresh token expired")
            self._remove_refresh_token(refresh_token)
            return None

        # Validate client
        if refresh_data["client_id"] != client_id:
            logger.warning("Client ID mismatch for refresh token")
            return None

        actor_id = refresh_data["actor_id"]
        # A legacy (pre-3.15) record has no chain; the one its rotation starts
        # is stamped on the consumed row too, so a replay of it is judged
        # against that chain like any other.
        chain_id = refresh_data.get("chain_id") or self._new_chain_id()
        consumed, current = self._consume(
            actor_id,
            self.refresh_tokens_bucket,
            refresh_token,
            refresh_data,
            consumed_ttl=MCP_REFRESH_TOKEN_REUSE_WINDOW,
            stamp=None if refresh_data.get("chain_id") else {"chain_id": chain_id},
        )

        if consumed:
            # The global index row only needs to outlive the consumed row.
            try:
                from .. import attribute

                attribute.Attributes(
                    actor_id=OAUTH2_SYSTEM_ACTOR,
                    bucket=REFRESH_TOKEN_INDEX_BUCKET,
                    config=self.config,
                ).set_attr(
                    name=refresh_token,
                    data=actor_id,
                    ttl_seconds=MCP_REFRESH_TOKEN_REUSE_WINDOW + INDEX_TTL_BUFFER,
                )
            except Exception as e:
                logger.debug(f"Could not shorten refresh index TTL: {e}")

            # Revoke the access token this refresh token was issued with.
            old_access_token = refresh_data.get("access_token")
            if old_access_token:
                try:
                    from ..mcp.invalidation import evict_caches_for_token

                    self._remove_access_token(
                        old_access_token,
                        actor_id=actor_id,
                        google_token_key=refresh_data.get("google_token_key"),
                    )
                    evict_caches_for_token(old_access_token, actor_wide=False)
                except Exception as e:
                    logger.warning(
                        f"Could not revoke the previous access token for actor "
                        f"{actor_id} on refresh: {e}"
                    )
            else:
                logger.debug(
                    "Legacy refresh token without an access-token reference; "
                    "rotating into a new chain"
                )
        else:
            if not current:
                logger.warning("Refresh token vanished during rotation")
                return None
            used_at = current.get("used_at")
            if not used_at:
                # A used row always carries used_at; one without it is
                # malformed. Refuse it, but never delete on that basis.
                logger.warning(
                    f"Consumed refresh token {_mask_token(refresh_token)} has no "
                    f"used_at; refusing it"
                )
                return None
            age = int(time.time()) - int(used_at)
            if age <= MCP_REFRESH_TOKEN_GRACE_PERIOD:
                # Rotate in the chain the winner recorded (a legacy record's
                # new chain lives only on the consumed row).
                chain_id = current.get("chain_id") or chain_id
                logger.debug(
                    f"Refresh token reused {age}s after rotation for actor "
                    f"{actor_id} (within grace) - rotating again in the same chain"
                )
                # Fall through to a full rotation below.
            elif age <= MCP_REFRESH_TOKEN_REUSE_WINDOW:
                chain_id = current.get("chain_id")
                if chain_id:
                    revoked = self._revoke_chain(
                        actor_id,
                        chain_id,
                        anchor=(self.refresh_tokens_bucket, refresh_token),
                    )
                else:
                    self._remove_refresh_token(refresh_token)
                    revoked = 1
                logger.warning(
                    f"Refresh token {_mask_token(refresh_token)} reused {age}s "
                    f"after rotation for actor {actor_id} - potential theft, "
                    f"revoked {revoked} token(s) in its chain"
                )
                return None
            else:
                logger.debug(
                    f"Refresh token reused {age}s after rotation for actor "
                    f"{actor_id} - past the reuse window, treating as expired"
                )
                self._remove_refresh_token(refresh_token)
                return None

        # Create new access token without Google token data (refresh flow)
        access_token = self._create_access_token_from_refresh(
            actor_id, client_id, chain_id=chain_id
        )
        new_refresh = self._create_refresh_token(
            actor_id,
            client_id,
            access_token["token"],
            access_token_id=access_token["token_id"],
            chain_id=chain_id,
            google_token_key=None,
        )

        return {
            "access_token": access_token["token"],
            "token_type": "Bearer",
            "expires_in": access_token["expires_in"],
            "refresh_token": new_refresh["token"],
            "scope": "mcp",
        }

    def revoke_token(self, token: str, token_type_hint: str | None = None) -> bool:
        """
        Revoke an access or refresh token, and the rest of its chain.

        A token that belongs to a refresh-token chain (every token issued
        since 3.15) revokes every access and refresh token in that chain,
        consumed ones included (RFC 7009 §2.1: revoking a refresh token
        invalidates the tokens of the same grant). Without that, a consumed
        refresh token could still rotate inside the grace period after its
        successor was revoked. A pre-chain (pre-3.15) access token revokes
        only itself: its refresh token links to it by ``access_token_id``
        alone, which nothing indexes, and it gains a chain on its first
        rotation. A pre-chain refresh token revokes itself. Cache eviction is
        per-process (see ``mcp/invalidation.py``).

        On a fault nothing is reported as revoked: when the chain cannot be
        revoked, or a delete of the presented token (or its linked access
        token) cannot be confirmed, :class:`TokenStoreUnavailable` is raised
        and the presented token's row is left in place, so presenting it
        again retries the whole revocation. This process's cache forgets it
        either way.

        Args:
            token: Token to revoke
            token_type_hint: "access_token" or "refresh_token"

        Raises:
            TokenStoreUnavailable: the token could not be looked up, its
                chain could not be revoked, or a delete could not be
                confirmed. The presented token is kept for a retry.

        Returns:
            True if token was revoked successfully
        """
        # Imported lazily, like the other callers in trust.py,
        # trust_permissions.py and oauth_session.py: MCP is an optional
        # higher layer and these are the modules it sits above.
        from ..mcp.invalidation import evict_caches_for_actor, evict_caches_for_token

        if token.startswith(self.token_prefix):
            # Access token
            token_data = self._load_access_token(token)
            if token_data:
                actor_id = token_data.get("actor_id")
                chain_id = token_data.get("chain_id")
                if actor_id and chain_id:
                    try:
                        self._revoke_chain(
                            actor_id, chain_id, anchor=(self.tokens_bucket, token)
                        )
                    except TokenStoreUnavailable:
                        # Keep the row: it is the anchor the next
                        # presentation retries the revocation from.
                        evict_caches_for_token(token)
                        raise
                if actor_id:
                    # With the owner known the delete skips the index read and
                    # is confirmed; after a chain revocation it only cleans up
                    # what the snapshot could not name.
                    gone = self._remove_access_token(
                        token,
                        actor_id=actor_id,
                        google_token_key=token_data.get("google_token_key"),
                    )
                else:
                    gone = self._remove_access_token(token)
                evict_caches_for_token(token)
                if not gone:
                    raise TokenStoreUnavailable(
                        f"Could not confirm revocation of access token "
                        f"{_mask_token(token)}"
                    )
                return True
        else:
            # Might be refresh token
            refresh_data = self._load_refresh_token(token)
            if refresh_data:
                actor_id = refresh_data.get("actor_id")
                chain_id = refresh_data.get("chain_id")
                access_token = refresh_data.get("access_token")
                if actor_id and chain_id:
                    try:
                        self._revoke_chain(
                            actor_id,
                            chain_id,
                            anchor=(self.refresh_tokens_bucket, token),
                        )
                    except TokenStoreUnavailable:
                        # Keep the row for the retry; forget what this
                        # process cached.
                        if access_token:
                            evict_caches_for_token(access_token)
                        evict_caches_for_actor(actor_id)
                        raise
                # The linked access token first, the presented token last: if
                # either delete is unconfirmed the presented token is still
                # there to retry with.
                access_gone = True
                gone = False
                if access_token and actor_id:
                    access_gone = self._remove_access_token(
                        access_token,
                        actor_id=actor_id,
                        google_token_key=refresh_data.get("google_token_key"),
                    )
                    evict_caches_for_token(access_token)
                if access_gone:
                    if actor_id:
                        gone = self._remove_refresh_token_row(actor_id, token)
                    else:
                        self._remove_refresh_token(token)
                        gone = True
                # The actor's cached identity should not outlive its
                # revocation.
                if actor_id:
                    evict_caches_for_actor(actor_id)
                if not access_gone or not gone:
                    raise TokenStoreUnavailable(
                        f"Could not confirm revocation of refresh token "
                        f"{_mask_token(token)}"
                    )
                return True

        return False

    @staticmethod
    def _new_chain_id() -> str:
        """A fresh refresh-token chain (family) identifier."""
        return secrets.token_urlsafe(16)

    def _consume(
        self,
        actor_id: str,
        bucket: str,
        name: str,
        record: dict[str, Any],
        *,
        consumed_ttl: int | None,
        stamp: dict[str, Any] | None = None,
    ) -> tuple[bool, dict[str, Any] | None]:
        """Atomically mark a single-use record (code or refresh token) used.

        See :func:`actingweb.single_use.consume_once`, shared with the SPA
        session store.

        Raises:
            TokenStoreUnavailable: the store could not confirm the consume
                either way; the record is untouched and the client may retry.
        """
        from ..single_use import StoreFault, consume_once

        try:
            return consume_once(
                self.config,
                actor_id,
                bucket,
                name,
                record,
                consumed_ttl=consumed_ttl,
                stamp=stamp,
            )
        except StoreFault as e:
            raise TokenStoreUnavailable(
                f"Could not consume a record in {bucket} for actor {actor_id}"
            ) from e

    def _snapshot_bucket(self, actor_id: str, bucket: str) -> dict[str, Any] | None:
        """All rows of one of the actor's token buckets (one query).

        Returns None when the backend could not be read, in either fault
        shape: PostgreSQL's backend answers None, which ``Attributes``
        reports as an empty bucket (only ``Attributes.loaded`` tells it from
        a real one); DynamoDB's raises when a page of the Query is throttled.
        """
        from .. import attribute

        store = attribute.Attributes(
            actor_id=actor_id, bucket=bucket, config=self.config
        )
        try:
            rows = store.get_bucket()
        except Exception as e:
            logger.warning(f"Could not read bucket {bucket} for actor {actor_id}: {e}")
            return None
        if not store.loaded:
            logger.warning(f"Could not read bucket {bucket} for actor {actor_id}")
            return None
        return dict(rows or {})

    def _revoke_chain(
        self,
        actor_id: str,
        chain_id: str,
        *,
        anchor: tuple[str, str] | None = None,
    ) -> int:
        """Revoke every access and refresh token in one refresh-token chain.

        The actor's two token buckets are read once to find the chain's token
        names (for the global index rows and the provider-token rows), then
        the rows are deleted with the backend's ``delete_by_chain``.

        ``anchor`` is the ``(bucket, name)`` of the row the caller just loaded
        (the replayed or revoked token). It is deleted last, so a DynamoDB
        fault part-way through its row-by-row delete leaves it in place and
        the next presentation of it retries the revocation. And it tells the
        two reasons a delete can remove nothing apart: when the anchor is gone
        too, a concurrent revocation of the same chain already did the work
        and this is not a fault; when it is still there, the delete failed
        (PostgreSQL's ``delete_by_chain`` answers 0 on an error, DynamoDB's
        raises) and :class:`TokenStoreUnavailable` is raised rather than
        report a revocation that did not happen. Without an anchor, 0 is
        always a fault. A snapshot that could not be read only skips the
        index and provider-row cleanup.

        This process's cached tokens and wrapper for the actor are evicted
        whatever the outcome, fault included. Eviction is **per-process**:
        another worker or container keeps serving a deleted access token from
        its own MCP cache for up to its cache TTL (300 s). See
        ``thoughts/todo/mcp-cache-lifecycle-and-revocation.md``.

        Returns:
            Number of token rows deleted from the actor's buckets.
        """
        from .. import attribute
        from ..db import get_attribute
        from ..mcp.invalidation import evict_caches_for_actor

        try:
            # A bucket that cannot be read (either backend's fault shape)
            # yields no names: the chain's actor rows are still deleted below,
            # and the index rows it could not enumerate are cleaned by the
            # lookups that find them stale, or expire.
            access_names: list[str] = []
            provider_keys: list[str] = []
            access_rows = self._snapshot_bucket(actor_id, self.tokens_bucket) or {}
            for name, attr in access_rows.items():
                data = (attr or {}).get("data")
                if isinstance(data, dict) and data.get("chain_id") == chain_id:
                    access_names.append(name)
                    if data.get("google_token_key"):
                        provider_keys.append(data["google_token_key"])
            refresh_names: list[str] = []
            refresh_rows = (
                self._snapshot_bucket(actor_id, self.refresh_tokens_bucket) or {}
            )
            for name, attr in refresh_rows.items():
                data = (attr or {}).get("data")
                if isinstance(data, dict) and data.get("chain_id") == chain_id:
                    refresh_names.append(name)

            try:
                revoked = get_attribute(self.config).delete_by_chain(
                    actor_id=actor_id,
                    buckets=[self.tokens_bucket, self.refresh_tokens_bucket],
                    chain_id=chain_id,
                    defer_name=anchor[1] if anchor else None,
                )
            except Exception as e:
                raise TokenStoreUnavailable(
                    f"Could not revoke token chain for actor {actor_id}"
                ) from e
            if not revoked:
                if anchor and self._strict_read(actor_id, *anchor) is None:
                    logger.info(f"Token chain for actor {actor_id} was already revoked")
                    return 0
                logger.error(
                    f"Revoking token chain for actor {actor_id} deleted nothing; "
                    f"treating it as a store fault"
                )
                raise TokenStoreUnavailable(
                    f"Token chain revocation for actor {actor_id} deleted nothing"
                )

            access_index = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=ACCESS_TOKEN_INDEX_BUCKET,
                config=self.config,
            )
            for name in access_names:
                access_index.delete_attr(name=name)
            refresh_index = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=REFRESH_TOKEN_INDEX_BUCKET,
                config=self.config,
            )
            for name in refresh_names:
                refresh_index.delete_attr(name=name)
            for key in provider_keys:
                self._remove_google_token_data(actor_id, key)
            return revoked
        finally:
            # Pops every cached token of the actor too.
            evict_caches_for_actor(actor_id)

    def _create_access_token(
        self,
        actor_id: str,
        client_id: str,
        provider_token_data: dict[str, Any],
        chain_id: str | None = None,
    ) -> dict[str, Any]:
        """Create an ActingWeb access token."""
        token_id = secrets.token_hex(16)
        token = f"{self.token_prefix}{secrets.token_urlsafe(32)}"

        # Store provider token data in private attributes
        google_token_key = f"google_token_access_{token_id}"
        self._store_google_token_data(actor_id, google_token_key, provider_token_data)

        token_data = {
            "token_id": token_id,
            "token": token,
            "actor_id": actor_id,
            "client_id": client_id,
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + self.default_expires_in,
            "expires_in": self.default_expires_in,
            "scope": "mcp",
            "google_token_key": google_token_key,  # Reference to stored Google data
        }
        if chain_id:
            token_data["chain_id"] = chain_id

        self._store_access_token(actor_id, token, token_data)
        return token_data

    def _create_access_token_from_refresh(
        self, actor_id: str, client_id: str, chain_id: str | None = None
    ) -> dict[str, Any]:
        """Create an ActingWeb access token from refresh token (no Google token data needed)."""
        token_id = secrets.token_hex(16)
        token = f"{self.token_prefix}{secrets.token_urlsafe(32)}"

        token_data = {
            "token_id": token_id,
            "token": token,
            "actor_id": actor_id,
            "client_id": client_id,
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + self.default_expires_in,
            "expires_in": self.default_expires_in,
            "scope": "mcp",
            # No Google token data needed for refresh flow
        }
        if chain_id:
            token_data["chain_id"] = chain_id

        self._store_access_token(actor_id, token, token_data)
        return token_data

    def _create_refresh_token(
        self,
        actor_id: str,
        client_id: str,
        access_token: str,
        *,
        access_token_id: str | None = None,
        chain_id: str | None = None,
        google_token_key: str | None = None,
    ) -> dict[str, Any]:
        """Create an ActingWeb refresh token.

        The record carries the access token **string** it was issued with,
        so rotation and revocation delete that token directly, and the
        provider-token row the access token owns (``google_token_key``,
        ``None`` for refresh-minted tokens).
        """
        token = f"rt_{secrets.token_urlsafe(32)}"

        refresh_data: dict[str, Any] = {
            "token": token,
            "actor_id": actor_id,
            "client_id": client_id,
            "access_token": access_token,
            # Written for one release so a pre-3.15 process in a rolling
            # deploy still finds the field; this version never reads it.
            "access_token_id": access_token_id,
            "chain_id": chain_id or self._new_chain_id(),
            "google_token_key": google_token_key,
            "used": False,
            "created_at": int(time.time()),
            "expires_at": int(time.time()) + self.refresh_token_expires_in,
        }

        self._store_refresh_token(actor_id, token, refresh_data)
        return refresh_data

    def _store_auth_code(
        self, actor_id: str, code: str, auth_data: dict[str, Any]
    ) -> None:
        """Store authorization code in private attributes."""
        try:
            from .. import attribute
            from ..constants import INDEX_TTL_BUFFER, MCP_AUTH_CODE_TTL

            # Store auth code in private attributes bucket
            auth_bucket = attribute.Attributes(
                actor_id=actor_id, bucket=self.auth_codes_bucket, config=self.config
            )
            # Auth codes expire in 10 minutes
            auth_bucket.set_attr(
                name=code, data=auth_data, ttl_seconds=MCP_AUTH_CODE_TTL
            )

            # Also store in global index for efficient lookup
            index_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=AUTH_CODE_INDEX_BUCKET,
                config=self.config,
            )
            # Index entry gets slightly longer TTL
            index_bucket.set_attr(
                name=code,
                data=actor_id,
                ttl_seconds=MCP_AUTH_CODE_TTL + INDEX_TTL_BUFFER,
            )

            logger.info(f"Stored auth code for actor {actor_id}")

        except Exception as e:
            logger.error(f"Error storing auth code for actor {actor_id}: {e}")
            import traceback

            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise

    def _load_auth_code(self, code: str) -> dict[str, Any] | None:
        """Load authorization code data."""
        # Search through actors for the code
        # This is a simplified implementation - in production you'd want indexing
        return self._search_auth_code_in_actors(code)

    def _search_auth_code_in_actors(self, code: str) -> dict[str, Any] | None:
        """Search for auth code across actors."""
        try:
            # Use the system actor to store a global index of auth codes
            from .. import attribute

            # Create a global index bucket for auth codes
            index_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=AUTH_CODE_INDEX_BUCKET,
                config=self.config,
            )

            # Look up which actor has this code
            found_actor_data = index_bucket.get_attr(name=code)
            if not found_actor_data or "data" not in found_actor_data:
                logger.debug(f"Auth code {_mask_token(code)} not found in global index")
                return None

            found_actor_id = found_actor_data["data"]
            if not found_actor_id:
                logger.debug(
                    f"Auth code {_mask_token(code)} has no actor ID in global index"
                )
                return None

            # Load the actual auth code data from private attributes
            auth_bucket = attribute.Attributes(
                actor_id=found_actor_id,
                bucket=self.auth_codes_bucket,
                config=self.config,
            )
            auth_attr = auth_bucket.get_attr(name=code)

            if not auth_attr or "data" not in auth_attr:
                logger.warning(
                    f"Auth code {_mask_token(code)} found in index but not in actor {found_actor_id}"
                )
                # Clean up the stale index entry
                index_bucket.delete_attr(name=code)
                return None

            auth_data = auth_attr["data"]
            if isinstance(auth_data, dict):
                logger.debug(
                    f"Found auth code {_mask_token(code)} in actor {found_actor_id}"
                )
                return auth_data
            else:
                logger.warning(f"Invalid auth code data format for {_mask_token(code)}")
                return None

        except Exception as e:
            logger.error(f"Error searching for auth code {_mask_token(code)}: {e}")
            return None

    def _remove_auth_code(self, code: str) -> None:
        """Remove authorization code."""
        try:
            # First find which actor has this code
            from .. import attribute

            index_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=AUTH_CODE_INDEX_BUCKET,
                config=self.config,
            )

            found_actor_data = index_bucket.get_attr(name=code)
            if found_actor_data and "data" in found_actor_data:
                found_actor_id = found_actor_data["data"]
                # Remove from private attributes
                auth_bucket = attribute.Attributes(
                    actor_id=found_actor_id,
                    bucket=self.auth_codes_bucket,
                    config=self.config,
                )
                auth_bucket.delete_attr(name=code)
                logger.debug(
                    f"Removed auth code {_mask_token(code)} from actor {found_actor_id}"
                )

            # Remove from global index
            index_bucket.delete_attr(name=code)
            logger.debug(f"Removed auth code {_mask_token(code)} from global index")

        except Exception as e:
            logger.error(f"Error removing auth code {_mask_token(code)}: {e}")

    def _store_google_token_data(
        self, actor_id: str, token_key: str, google_token_data: dict[str, Any]
    ) -> None:
        """Store Google OAuth2 token data in private attributes."""
        try:
            from .. import attribute
            from ..constants import MCP_ACCESS_TOKEN_TTL

            # Store Google token data in private attributes bucket
            google_bucket = attribute.Attributes(
                actor_id=actor_id, bucket=self.google_tokens_bucket, config=self.config
            )
            # Google token data is tied to access token lifetime
            google_bucket.set_attr(
                name=token_key, data=google_token_data, ttl_seconds=MCP_ACCESS_TOKEN_TTL
            )
            logger.debug(
                f"Stored Google token data for actor {actor_id} with key {_mask_token(token_key)}"
            )

        except Exception as e:
            logger.error(f"Error storing Google token data for actor {actor_id}: {e}")
            raise

    def _load_google_token_data(
        self, actor_id: str, token_key: str
    ) -> dict[str, Any] | None:
        """Load Google OAuth2 token data from private attributes."""
        try:
            from .. import attribute

            # Load Google token data from private attributes bucket
            google_bucket = attribute.Attributes(
                actor_id=actor_id, bucket=self.google_tokens_bucket, config=self.config
            )
            token_attr = google_bucket.get_attr(name=token_key)

            if not token_attr or "data" not in token_attr:
                logger.warning(
                    f"Google token data not found for key {_mask_token(token_key)}"
                )
                return None

            token_data = token_attr["data"]
            return token_data if isinstance(token_data, dict) else None

        except Exception as e:
            logger.error(
                f"Error loading Google token data for actor {actor_id}, key {_mask_token(token_key)}: {e}"
            )
            return None

    def _remove_google_token_data(self, actor_id: str, token_key: str) -> None:
        """Remove Google OAuth2 token data from private attributes."""
        try:
            from .. import attribute

            # Remove Google token data from private attributes bucket
            google_bucket = attribute.Attributes(
                actor_id=actor_id, bucket=self.google_tokens_bucket, config=self.config
            )
            google_bucket.delete_attr(name=token_key)
            logger.debug(
                f"Removed Google token data for actor {actor_id} with key {_mask_token(token_key)}"
            )
        except Exception as e:
            logger.error(
                f"Error removing Google token data for actor {actor_id}, key {_mask_token(token_key)}: {e}"
            )

    def _store_access_token(
        self, actor_id: str, token: str, token_data: dict[str, Any]
    ) -> None:
        """Store access token in private attributes."""
        try:
            from .. import attribute
            from ..constants import INDEX_TTL_BUFFER, MCP_ACCESS_TOKEN_TTL

            # Store access token in private attributes bucket
            tokens_bucket = attribute.Attributes(
                actor_id=actor_id, bucket=self.tokens_bucket, config=self.config
            )
            # Access tokens expire in 1 hour
            tokens_bucket.set_attr(
                name=token, data=token_data, ttl_seconds=MCP_ACCESS_TOKEN_TTL
            )

            # Also store in global index for efficient lookup
            index_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=ACCESS_TOKEN_INDEX_BUCKET,
                config=self.config,
            )
            # Index entry gets slightly longer TTL
            index_bucket.set_attr(
                name=token,
                data=actor_id,
                ttl_seconds=MCP_ACCESS_TOKEN_TTL + INDEX_TTL_BUFFER,
            )

            logger.info(f"Stored access token for actor {actor_id}")

        except Exception as e:
            logger.error(f"Error storing access token for actor {actor_id}: {e}")
            raise

    def _load_access_token(self, token: str) -> dict[str, Any] | None:
        """Load access token data."""
        # Search through actors for the token
        return self._search_token_in_actors(token)

    def _strict_read(self, actor_id: str, bucket: str, name: str) -> Any:
        """Point-read one row, telling absence from a backend fault.

        Returns the stored ``data``, or None when the row is absent or
        expired. Raises :class:`TokenStoreUnavailable` when the backend
        could not be read: ``Attributes.get_attr`` would answer None for
        that too, which reads as "no such token".
        """
        from ..db import get_attribute

        try:
            row = get_attribute(self.config).get_attr_strict(
                actor_id=actor_id, bucket=bucket, name=name
            )
        except Exception as e:
            raise TokenStoreUnavailable(
                f"Could not read {bucket} for actor {actor_id}"
            ) from e
        if not row or "data" not in row:
            return None
        return row["data"]

    def _search_indexed_token(
        self, token: str, index_bucket_name: str, bucket: str, kind: str
    ) -> dict[str, Any] | None:
        """Resolve a token through its global index to the actor's row.

        None means the token does not exist (absent, stale index row,
        malformed). A store fault raises :class:`TokenStoreUnavailable`.
        """
        found_actor_id = self._strict_read(
            OAUTH2_SYSTEM_ACTOR, index_bucket_name, token
        )
        if not found_actor_id:
            logger.debug(f"{kind} {_mask_token(token)} not found in global index")
            return None

        token_data = self._strict_read(str(found_actor_id), bucket, token)
        if token_data is None:
            logger.warning(
                f"{kind} {_mask_token(token)} found in index but not in actor "
                f"{found_actor_id}"
            )
            # Clean up the stale index entry
            try:
                from .. import attribute

                attribute.Attributes(
                    actor_id=OAUTH2_SYSTEM_ACTOR,
                    bucket=index_bucket_name,
                    config=self.config,
                ).delete_attr(name=token)
            except Exception as e:
                logger.debug(f"Could not remove stale index row: {e}")
            return None

        if not isinstance(token_data, dict):
            logger.warning(
                f"Invalid {kind.lower()} data format for {_mask_token(token)}"
            )
            return None
        logger.debug(
            f"Found {kind.lower()} {_mask_token(token)} in actor {found_actor_id}"
        )
        return token_data

    def _search_token_in_actors(self, token: str) -> dict[str, Any] | None:
        """Search for an access token across actors.

        Raises:
            TokenStoreUnavailable: the token store could not be read.
        """
        return self._search_indexed_token(
            token, ACCESS_TOKEN_INDEX_BUCKET, self.tokens_bucket, "Access token"
        )

    def _search_refresh_token_in_actors(self, token: str) -> dict[str, Any] | None:
        """Search for a refresh token across actors.

        Raises:
            TokenStoreUnavailable: the token store could not be read.
        """
        return self._search_indexed_token(
            token,
            REFRESH_TOKEN_INDEX_BUCKET,
            self.refresh_tokens_bucket,
            "Refresh token",
        )

    def _remove_access_token(
        self,
        token: str,
        *,
        actor_id: str | None = None,
        google_token_key: str | None = None,
    ) -> bool:
        """Remove access token.

        With ``actor_id`` the owner is known (rotation, revocation from a
        refresh record): the row, its index row and, when
        ``google_token_key`` is given, its provider-token row are deleted
        directly without re-loading the token, and the actor row's delete is
        confirmed (:func:`actingweb.single_use.delete_confirmed`). Without it,
        the token is looked up through the global index first.

        Returns:
            With ``actor_id``: whether the actor row is confirmed gone. An
            unconfirmed delete is logged at ERROR and leaves the index and
            provider rows, so the token stays reachable for a retry. Without
            it: False only when the removal raised.
        """
        if actor_id:
            from .. import attribute
            from ..single_use import delete_confirmed

            gone = delete_confirmed(self.config, actor_id, self.tokens_bucket, token)
            if not gone:
                # Keep the index and provider rows: the token must stay
                # reachable so presenting it again retries the removal.
                logger.error(
                    f"Could not confirm removal of access token "
                    f"{_mask_token(token)} for actor {actor_id}"
                )
                return False
            if google_token_key:
                self._remove_google_token_data(actor_id, google_token_key)
            attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=ACCESS_TOKEN_INDEX_BUCKET,
                config=self.config,
            ).delete_attr(name=token)
            logger.debug(
                f"Removed access token {_mask_token(token)} from actor {actor_id}"
            )
            return True
        try:
            # First load token data to get Google token key
            token_data = self._load_access_token(token)

            # First find which actor has this token
            from .. import attribute

            index_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=ACCESS_TOKEN_INDEX_BUCKET,
                config=self.config,
            )

            found_actor_data = index_bucket.get_attr(name=token)
            if found_actor_data and "data" in found_actor_data:
                found_actor_id = found_actor_data["data"]
                # Remove from private attributes
                tokens_bucket = attribute.Attributes(
                    actor_id=found_actor_id,
                    bucket=self.tokens_bucket,
                    config=self.config,
                )
                tokens_bucket.delete_attr(name=token)
                logger.debug(
                    f"Removed access token {_mask_token(token)} from actor {found_actor_id}"
                )

                # Also remove associated Google token data
                if token_data and "google_token_key" in token_data:
                    self._remove_google_token_data(
                        found_actor_id, token_data["google_token_key"]
                    )

            # Remove from global index
            index_bucket.delete_attr(name=token)
            logger.debug(f"Removed access token {_mask_token(token)} from global index")
            return True

        except Exception as e:
            logger.error(f"Error removing access token {_mask_token(token)}: {e}")
            return False

    def _store_refresh_token(
        self, actor_id: str, token: str, refresh_data: dict[str, Any]
    ) -> None:
        """Store refresh token in private attributes."""
        try:
            from .. import attribute
            from ..constants import INDEX_TTL_BUFFER, MCP_REFRESH_TOKEN_TTL

            # Store refresh token in private attributes bucket
            refresh_bucket = attribute.Attributes(
                actor_id=actor_id, bucket=self.refresh_tokens_bucket, config=self.config
            )
            # Refresh tokens expire in 30 days
            refresh_bucket.set_attr(
                name=token, data=refresh_data, ttl_seconds=MCP_REFRESH_TOKEN_TTL
            )

            # Also store in global index for efficient lookup
            index_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=REFRESH_TOKEN_INDEX_BUCKET,
                config=self.config,
            )
            # Index entry gets slightly longer TTL
            index_bucket.set_attr(
                name=token,
                data=actor_id,
                ttl_seconds=MCP_REFRESH_TOKEN_TTL + INDEX_TTL_BUFFER,
            )

            logger.info(f"Stored refresh token for actor {actor_id}")

        except Exception as e:
            logger.error(f"Error storing refresh token for actor {actor_id}: {e}")
            raise

    def _load_refresh_token(self, token: str) -> dict[str, Any] | None:
        """Load refresh token data."""
        # Search through actors for the token
        return self._search_refresh_token_in_actors(token)

    def _remove_refresh_token_row(self, actor_id: str, token: str) -> bool:
        """Remove a refresh token whose owner is known, confirming the delete.

        Returns whether the actor row is confirmed gone. The index row is
        removed only then: while the row may still be there, the token must
        stay reachable so presenting it again retries the removal.
        """
        from .. import attribute
        from ..single_use import delete_confirmed

        gone = delete_confirmed(
            self.config, actor_id, self.refresh_tokens_bucket, token
        )
        if not gone:
            logger.error(
                f"Could not confirm removal of refresh token "
                f"{_mask_token(token)} for actor {actor_id}"
            )
            return False
        attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=REFRESH_TOKEN_INDEX_BUCKET,
            config=self.config,
        ).delete_attr(name=token)
        return True

    def _remove_refresh_token(self, token: str) -> None:
        """Remove refresh token."""
        try:
            # First find which actor has this token
            from .. import attribute

            index_bucket = attribute.Attributes(
                actor_id=OAUTH2_SYSTEM_ACTOR,
                bucket=REFRESH_TOKEN_INDEX_BUCKET,
                config=self.config,
            )

            found_actor_data = index_bucket.get_attr(name=token)
            if found_actor_data and "data" in found_actor_data:
                found_actor_id = found_actor_data["data"]
                # Remove from private attributes
                refresh_bucket = attribute.Attributes(
                    actor_id=found_actor_id,
                    bucket=self.refresh_tokens_bucket,
                    config=self.config,
                )
                refresh_bucket.delete_attr(name=token)
                logger.debug(
                    f"Removed refresh token {_mask_token(token)} from actor {found_actor_id}"
                )

            # Remove from global index
            index_bucket.delete_attr(name=token)
            logger.debug(
                f"Removed refresh token {_mask_token(token)} from global index"
            )

        except Exception as e:
            logger.error(f"Error removing refresh token {_mask_token(token)}: {e}")

    def _validate_pkce(
        self, code_verifier: str, code_challenge: str, code_challenge_method: str
    ) -> bool:
        """
        Validate PKCE code_verifier against stored code_challenge.

        Args:
            code_verifier: The code verifier provided in token request
            code_challenge: The code challenge stored from authorization request
            code_challenge_method: The method used for the challenge (plain or S256)

        Returns:
            True if valid, False otherwise
        """
        try:
            # Basic format validation
            if not code_verifier or len(code_verifier) < 43 or len(code_verifier) > 128:
                logger.warning(
                    f"Invalid PKCE code_verifier length: {len(code_verifier) if code_verifier else 0}"
                )
                return False

            if not code_challenge or len(code_challenge) < 43:
                logger.warning(
                    f"Invalid PKCE code_challenge length: {len(code_challenge) if code_challenge else 0}"
                )
                return False

            # Validate based on method
            if code_challenge_method == "plain":
                return secret_equals(code_verifier, code_challenge)
            elif code_challenge_method == "S256":
                # Create SHA256 hash of code_verifier and base64url encode it
                digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
                expected_challenge = (
                    base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
                )
                return secret_digest_equals(expected_challenge, code_challenge)
            else:
                logger.warning(
                    f"Unsupported PKCE challenge method: {code_challenge_method}"
                )
                return False
        except Exception as e:
            logger.error(f"Error validating PKCE: {e}")
            return False

    def create_access_token(
        self,
        actor_id: str,
        client_id: str,
        scope: str = "mcp",
        trust_type: str = "mcp_client",
        grant_type: str = "client_credentials",
    ) -> dict[str, Any] | None:
        """
        Create an access token for client credentials flow.

        Args:
            actor_id: The actor this token is for
            client_id: The client requesting the token
            scope: The requested scope
            trust_type: The trust relationship type
            grant_type: The grant type (client_credentials)

        Returns:
            Token response dictionary or None if failed
        """
        try:
            token_id = secrets.token_hex(16)
            token = f"{self.token_prefix}{secrets.token_urlsafe(32)}"
            current_time = int(time.time())

            token_data = {
                "token_id": token_id,
                "token": token,
                "actor_id": actor_id,
                "client_id": client_id,
                "scope": scope,
                "trust_type": trust_type,
                "grant_type": grant_type,
                "created_at": current_time,
                "expires_at": current_time + self.default_expires_in,
            }

            # Store token in actor's private attributes
            self._store_access_token(actor_id, token, token_data)

            # Return standard OAuth2 token response
            response = {
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": self.default_expires_in,
                "scope": scope,
            }

            logger.info(
                f"Created access token for client credentials flow: {client_id} -> {actor_id}"
            )
            return response

        except Exception as e:
            logger.error(f"Error creating access token for client credentials: {e}")
            return None

    def revoke_client_tokens(self, actor_id: str, client_id: str) -> int:
        """
        Revoke all tokens (access and refresh) associated with a specific client.

        This ensures that when a client is deleted, all its tokens are immediately
        invalidated and cannot be used for further access.

        Args:
            actor_id: The actor the client belongs to
            client_id: The client identifier whose tokens should be revoked

        Returns:
            Number of tokens confirmed revoked (access + refresh tokens)

        Raises:
            TokenStoreUnavailable: one of the two token buckets could not be
                read, or a delete could not be confirmed, so some of the
                client's tokens may be left. Whatever could be revoked is
                revoked first.
        """
        revoked_count = 0
        unreadable: list[str] = []
        unconfirmed = 0

        from ..mcp.invalidation import evict_caches_for_token

        def remove_access(name: str, data: dict[str, Any]) -> bool:
            removed = self._remove_access_token(
                name, actor_id=actor_id, google_token_key=data.get("google_token_key")
            )
            # Evict either way: a token of a deleted client must not keep
            # authenticating from this process's cache (per process; see
            # revoke_token).
            evict_caches_for_token(name)
            return removed

        def remove_refresh(name: str, _data: dict[str, Any]) -> bool:
            return self._remove_refresh_token_row(actor_id, name)

        for bucket, kind, remove in (
            (self.tokens_bucket, "access", remove_access),
            (self.refresh_tokens_bucket, "refresh", remove_refresh),
        ):
            rows = self._snapshot_bucket(actor_id, bucket)
            if rows is None:
                unreadable.append(bucket)
                continue
            for token_name, token_attr in rows.items():
                token_data = (token_attr or {}).get("data")
                if not (
                    isinstance(token_data, dict)
                    and token_data.get("client_id") == client_id
                ):
                    continue
                # One token's failure is counted, never allowed to stop the
                # rest or to be swallowed.
                try:
                    removed = remove(token_name, token_data)
                except Exception as e:
                    logger.error(
                        f"Error revoking {kind} token {_mask_token(token_name)} "
                        f"for client {client_id}: {e}"
                    )
                    removed = False
                if not removed:
                    unconfirmed += 1
                    continue
                revoked_count += 1
                logger.debug(
                    f"Revoked {kind} token {_mask_token(token_name)} for client "
                    f"{client_id}"
                )

        if revoked_count > 0:
            logger.info(
                f"Revoked {revoked_count} tokens for client {client_id} in actor {actor_id}"
            )
        else:
            logger.debug(f"No tokens found to revoke for client {client_id}")

        if unreadable or unconfirmed:
            problems = [f"could not read {bucket}" for bucket in unreadable]
            if unconfirmed:
                problems.append(f"could not confirm {unconfirmed} delete(s)")
            raise TokenStoreUnavailable(
                f"{'; '.join(problems)} for actor {actor_id}; "
                f"revoked {revoked_count} token(s) of client {client_id}"
            )
        return revoked_count

    def cleanup_expired_tokens(self) -> dict[str, int]:
        """
        Clean up expired MCP tokens and associated data.

        .. warning::
            **SCHEDULED LAMBDA ONLY** - Do NOT call from request handlers.

        This method iterates through all token indexes and removes expired
        entries. It should only be invoked by a scheduled cleanup Lambda
        triggered via EventBridge/CloudWatch Events.

        Calling this from the request path will:
        - Add significant latency to requests
        - Impact Lambda cold start time
        - Cause unpredictable performance

        Returns:
            Dictionary with counts of cleaned items by type:
            - access_tokens: Number of expired access tokens removed
            - refresh_tokens: Number of expired refresh tokens removed
            - auth_codes: Number of expired auth codes removed
            - index_entries: Number of orphaned index entries removed
            - provider_tokens: Number of TTL-expired provider-token rows
              removed (always 0 on DynamoDB, where native TTL removes them)

        A consumed refresh token counts as expired once it is past
        ``MCP_REFRESH_TOKEN_REUSE_WINDOW``.
        """
        from .. import attribute
        from ..constants import MCP_REFRESH_TOKEN_REUSE_WINDOW
        from ..db import get_attribute

        current_time = int(time.time())
        cleaned: dict[str, int] = {
            "access_tokens": 0,
            "refresh_tokens": 0,
            "auth_codes": 0,
            "index_entries": 0,
        }

        # Clean up access token index
        access_index = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=ACCESS_TOKEN_INDEX_BUCKET,
            config=self.config,
        )
        access_index_data = access_index.get_bucket()

        if access_index_data:
            for token, index_attr in list(access_index_data.items()):
                if not index_attr or "data" not in index_attr:
                    # Orphaned index entry
                    access_index.delete_attr(name=token)
                    cleaned["index_entries"] += 1
                    continue

                # Check if the actual token still exists and is valid
                token_data = self._load_access_token(token)
                if not token_data:
                    # Token doesn't exist, clean index
                    access_index.delete_attr(name=token)
                    cleaned["index_entries"] += 1
                elif current_time > token_data.get("expires_at", 0):
                    # Token expired, clean both
                    self._remove_access_token(token)
                    cleaned["access_tokens"] += 1

        # Clean up refresh token index
        refresh_index = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=REFRESH_TOKEN_INDEX_BUCKET,
            config=self.config,
        )
        refresh_index_data = refresh_index.get_bucket()

        if refresh_index_data:
            for token, index_attr in list(refresh_index_data.items()):
                if not index_attr or "data" not in index_attr:
                    refresh_index.delete_attr(name=token)
                    cleaned["index_entries"] += 1
                    continue

                token_data = self._load_refresh_token(token)
                if not token_data:
                    refresh_index.delete_attr(name=token)
                    cleaned["index_entries"] += 1
                elif current_time > token_data.get("expires_at", 0) or (
                    token_data.get("used")
                    and int(token_data.get("used_at") or 0)
                    + MCP_REFRESH_TOKEN_REUSE_WINDOW
                    < current_time
                ):
                    # Expired, or consumed and past the reuse window: a used
                    # refresh token only exists for reuse detection.
                    self._remove_refresh_token(token)
                    cleaned["refresh_tokens"] += 1

        # Clean up auth code index
        auth_index = attribute.Attributes(
            actor_id=OAUTH2_SYSTEM_ACTOR,
            bucket=AUTH_CODE_INDEX_BUCKET,
            config=self.config,
        )
        auth_index_data = auth_index.get_bucket()

        if auth_index_data:
            for code, index_attr in list(auth_index_data.items()):
                if not index_attr or "data" not in index_attr:
                    auth_index.delete_attr(name=code)
                    cleaned["index_entries"] += 1
                    continue

                auth_data = self._load_auth_code(code)
                if not auth_data:
                    auth_index.delete_attr(name=code)
                    cleaned["index_entries"] += 1
                elif current_time > auth_data.get("expires_at", 0):
                    self._remove_auth_code(code)
                    cleaned["auth_codes"] += 1

        # Provider-token rows have no index to walk; they are swept by their
        # storage TTL (a no-op on DynamoDB, where native TTL removes them).
        try:
            cleaned["provider_tokens"] = get_attribute(self.config).delete_expired(
                buckets=[self.google_tokens_bucket]
            )
        except Exception as e:
            logger.warning(f"Provider-token sweep failed: {e}")
            cleaned["provider_tokens"] = 0

        total = sum(cleaned.values())
        if total > 0:
            logger.info(f"Cleanup complete: {cleaned}")

        return cleaned

    def purge_expired_tokens(self) -> int:
        """Delete TTL-expired rows from every MCP token bucket.

        Covers the actor buckets (access tokens, refresh tokens, provider
        tokens, auth codes) and the three global indexes. One set-based delete
        on PostgreSQL; on DynamoDB it returns 0 and native TTL on the
        attributes table does the work.

        Returns:
            Number of rows deleted.
        """
        from ..db import get_attribute

        try:
            return get_attribute(self.config).delete_expired(
                buckets=[
                    self.tokens_bucket,
                    self.refresh_tokens_bucket,
                    self.google_tokens_bucket,
                    self.auth_codes_bucket,
                    ACCESS_TOKEN_INDEX_BUCKET,
                    REFRESH_TOKEN_INDEX_BUCKET,
                    AUTH_CODE_INDEX_BUCKET,
                ]
            )
        except Exception as e:
            logger.warning(f"MCP token purge failed: {e}")
            return 0

    def maybe_purge_expired_tokens(self) -> int:
        """Run :meth:`purge_expired_tokens` at most once per
        ``MCP_TOKEN_PURGE_INTERVAL`` per process.

        Called from the token endpoint, so consumed and expired token rows
        are reaped on PostgreSQL without a scheduled job. Lock-free: two
        threads racing past the throttle both run an idempotent delete.

        Returns:
            Number of rows deleted (0 when throttled or on DynamoDB).
        """
        from ..constants import MCP_TOKEN_PURGE_INTERVAL

        if not _mcp_purge_throttle.claim(MCP_TOKEN_PURGE_INTERVAL):
            return 0
        return self.purge_expired_tokens()


# When this process last ran the opportunistic MCP token purge.
_mcp_purge_throttle = PurgeThrottle()

# Global token manager
_token_manager: ActingWebTokenManager | None = None
# The config the manager was built from; a different one must rebuild it.
_token_manager_config: config_class.Config | None = None


def get_actingweb_token_manager(config: config_class.Config) -> ActingWebTokenManager:
    """Get or create the global ActingWeb token manager.

    Rebuilds when handed a different ``Config`` so one application's tokens
    are never read from or written to another application's store.
    """
    global _token_manager, _token_manager_config
    if _token_manager is None or _token_manager_config is not config:
        _token_manager = ActingWebTokenManager(config)
        _token_manager_config = config
    return _token_manager
