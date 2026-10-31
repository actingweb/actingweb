import base64
import datetime
import json
import logging
import os
import time
from typing import Any

import requests

from actingweb import attribute, deletion, peertrustee, property, subscription, trust
from actingweb.constants import (
    DEFAULT_CREATOR,
)
from actingweb.db import get_actor, get_actor_list, get_subscription_suspension
from actingweb.log_summary import summarize_payload
from actingweb.permission_evaluator import PermissionResult, get_permission_evaluator
from actingweb.property_list import ListCorruptionError
from actingweb.secret_compare import secret_digest_equals

from .db.creator_rules import (
    is_exempt,
    is_refused_from_callers,
    is_reserved,
    normalise_creator,
)
from .db.exceptions import CreatorTaken, DbError

logger = logging.getLogger(__name__)

# Rate limit for the suspension-check failure ERROR (see
# is_subscription_suspended()). Time-windowed rather than once-per-process:
# a warm serverless container — or any long-lived one — can outlive the
# incident by days, and "once ever" would report a broken suspensions table a
# single time and then stay silent through every later failure, including a
# different one. A repeating heartbeat is alertable and stops on its own once
# the fault is fixed, while still costing at most one line per window per
# container.
_SUSPENSION_ERROR_LOG_INTERVAL_SECONDS = 300.0
_suspension_check_error_logged_at: float | None = None


class ActorError(Exception):
    """Base exception class for Actor-related errors."""

    pass


class ActorNotFoundError(ActorError):
    """Raised when an actor cannot be found."""

    pass


class InvalidActorDataError(ActorError):
    """Raised when actor data is invalid or corrupted."""

    pass


class PeerCommunicationError(ActorError):
    """Raised when communication with peer actors fails."""

    pass


class TrustRelationshipError(ActorError):
    """Raised when trust relationship operations fail."""

    pass


class DummyPropertyClass:
    """Only used to deprecate get_property() in 2.4.4"""

    def __init__(self, v: Any = None) -> None:
        self.value = v


def relationship_summary(
    trusts: list[Any] | None, subscriptions: list[Any] | None
) -> tuple[list[dict[str, Any]], list[str]]:
    """What an adoption removed, for its log line and the ``actor_adopted``
    hook: each trust's ``peerid``, ``relationship``, ``approved`` and
    ``established_via`` (never its ``secret``), and the sorted subscription
    peer ids."""
    removed_trusts = [
        {
            "peerid": t.get("peerid", ""),
            "relationship": t.get("relationship", ""),
            "approved": t.get("approved"),
            "established_via": t.get("established_via"),
        }
        for t in (trusts or [])
        if isinstance(t, dict)
    ]
    peers = sorted(
        {
            str(s.get("peerid", ""))
            for s in (subscriptions or [])
            if isinstance(s, dict) and s.get("peerid")
        }
    )
    return removed_trusts, peers


class Actor:
    ###################
    # Basic operations
    ###################

    def __init__(self, actor_id: str | None = None, config: Any | None = None) -> None:
        self.config = config
        self.property_list: Any | None = None
        self.subs_list: list[dict[str, Any]] | None = None
        self.actor: dict[str, Any] | None = None
        self.passphrase: str | None = None
        self.creator: str | None = None
        self.last_response_code: int = 0
        self.last_response_message: str = ""
        self.id: str | None = actor_id
        # Set by get_from_creator: the other actors with this creator that are
        # marked for replacement (``factory``), for a sign-in to sweep.
        self.factory_sibling_ids: list[str] = []
        self.creator_ids: list[str] = []
        self.creator_classes: dict[str, str] = {}
        if self.config:
            self.handle = get_actor(self.config)
        else:
            self.handle = None
        if actor_id and config:
            self.store = attribute.InternalStore(actor_id=actor_id, config=config)
            self.property = property.PropertyStore(actor_id=actor_id, config=config)
            self.property_lists = property.PropertyListStore(
                actor_id=actor_id, config=config
            )
        else:
            self.store = None
            self.property = None
            self.property_lists = None
        self.get(actor_id=actor_id)

    def get_peer_info(
        self, url: str, max_retries: int = 3, retry_delay: float = 0.5
    ) -> dict[str, Any]:
        """Contacts another actor over http/s to retrieve meta information.

        Includes retry logic for transient network failures with exponential backoff.

        Note: This sync method blocks the event loop. In FastAPI/uvicorn contexts,
        use AsyncTrustHandler which calls create_reciprocal_trust_async() instead.

        :param url: Root URI of a remote actor
        :param max_retries: Maximum number of retry attempts (default: 3)
        :param retry_delay: Initial delay between retries in seconds (default: 0.5)
        :rtype: dict
        :return: The json response from the /meta path in the data element and
            last_response_code/last_response_message set to the results of the https request

        Example::

            {
                "last_response_code": 200,
                "last_response_message": "OK",
                "data": {}
            }
        """
        import time

        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    logger.info(
                        f"Retry attempt {attempt + 1}/{max_retries} for peer info from {url}"
                    )
                else:
                    logger.debug(f"Fetching peer info from {url}")

                response = requests.get(url=url + "/meta", timeout=(5, 10))
                res = {
                    "last_response_code": response.status_code,
                    "last_response_message": response.content,
                    "data": json.loads(response.content.decode("utf-8", "ignore")),
                }
                logger.debug(
                    f"Got peer info from url({url}) with body("
                    f"{summarize_payload(res['data'], encoded_len=len(response.content))})"
                )
                return res
            except (TypeError, ValueError, KeyError) as e:
                # JSON parsing errors - don't retry
                logger.warning(f"Invalid response from peer {url}: {e}")
                return {
                    "last_response_code": 500,
                    "last_response_message": str(e),
                }
            except requests.exceptions.RequestException as e:
                # Network errors - retry with exponential backoff
                last_error = e
                if attempt < max_retries - 1:
                    delay = retry_delay * (2**attempt)  # Exponential backoff
                    logger.warning(
                        f"Network error fetching peer info from {url}: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                else:
                    logger.warning(
                        f"Network error fetching peer info from {url} after "
                        f"{max_retries} attempts: {e}"
                    )

        # All retries exhausted
        return {
            "last_response_code": 500,
            "last_response_message": str(last_error) if last_error else "Unknown error",
        }

    async def get_peer_info_async(self, url: str) -> dict[str, Any]:
        """Async version of get_peer_info using httpx.

        Contacts another actor over HTTP/S to retrieve meta information without blocking.

        :param url: Root URI of a remote actor
        :return: Dict with last_response_code, last_response_message, and data
        """
        import httpx

        try:
            logger.debug(f"Fetching peer info async from {url}")
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url + "/meta")
                res = {
                    "last_response_code": response.status_code,
                    "last_response_message": response.content,
                    "data": response.json(),
                }
                logger.debug(
                    f"Got peer info async from url({url}) with body("
                    f"{summarize_payload(res['data'], encoded_len=len(response.content))})"
                )
                return res
        except (TypeError, ValueError, KeyError) as e:
            # JSON parsing errors
            logger.warning(f"Invalid response from peer {url}: {e}")
            return {
                "last_response_code": 500,
                "last_response_message": str(e),
                "data": {},
            }
        except httpx.TimeoutException as e:
            logger.warning(f"Timeout fetching peer info async from {url}: {e}")
            return {
                "last_response_code": 408,
                "last_response_message": "Timeout",
                "data": {},
            }
        except httpx.RequestError as e:
            logger.warning(f"Network error fetching peer info async from {url}: {e}")
            return {
                "last_response_code": 500,
                "last_response_message": str(e),
                "data": {},
            }

    def _write_marker(self, store: "attribute.InternalStore", auth_method: str) -> bool:
        """Write ``auth_method``, and first, for a vouched one, the address
        it vouches for (:data:`actingweb.oauth2.VOUCHED_CREATOR`), both
        confirmed. Bound first: a marker without its address would be judged
        by the marker alone. Raises ``DbError`` on a fault."""
        from .oauth2 import UNVOUCHED_AUTH_METHODS, VOUCHED_CREATOR

        if auth_method not in UNVOUCHED_AUTH_METHODS and not store.set_confirmed(
            VOUCHED_CREATOR, normalise_creator(self.creator), raise_on_fault=True
        ):
            return False
        return store.set_confirmed("auth_method", auth_method, raise_on_fault=True)

    @staticmethod
    def _restore_marker(
        store: "attribute.InternalStore", marker: Any, creator: str | None
    ) -> bool:
        """Put back the marker a failed creator change replaced. A vouched
        one is bound to ``creator`` (the one the re-read confirmed) first,
        so a concurrent change that lands after this restore leaves the
        actor unvouched, whatever order the writes take."""
        from .oauth2 import UNVOUCHED_AUTH_METHODS, VOUCHED_CREATOR

        if (
            isinstance(marker, str)
            and marker
            and marker not in UNVOUCHED_AUTH_METHODS
            and not store.set_confirmed(VOUCHED_CREATOR, normalise_creator(creator))
        ):
            return False
        # Only while it still reads this change's "creator_changed": a
        # sign-in that cleaned the actor meanwhile wrote its own marker, and
        # an unconditional restore would put the stale one back over it.
        db = store.__dict__["_db"]
        if not db.conditional_update_attr(
            name="auth_method", old_data="creator_changed", new_data=marker or None
        ):
            logger.warning(
                "auth_method changed since this creator change wrote it; not restored"
            )
            return False
        store.__dict__["auth_method"] = marker or None
        return True

    @staticmethod
    def _drop_pre_marker(
        store: "attribute.InternalStore | None", actor_id: str | None
    ) -> None:
        """Remove the marker written ahead of a create refused with
        ``CreatorTaken`` (its condition failed, so nothing committed), so no
        bucket is left for an id with no actor. Best effort: a
        leftover is an orphan bucket for an id nobody uses, which
        ``verify_orphans`` lists."""
        if store is None:
            return
        from .oauth2 import VOUCHED_CREATOR

        try:
            store.set_confirmed(VOUCHED_CREATOR, None)
            if not store.set_confirmed("auth_method", None):
                logger.warning(f"Marker for {actor_id} left behind a failed create")
        except Exception as e:  # folds DbError: best-effort cleanup of an unused id
            logger.warning(f"Marker for {actor_id} left behind: {e}")

    def get(
        self, actor_id: str | None = None, *, rewrite_email: bool = True
    ) -> dict[str, Any] | None:
        """Retrieves an actor from storage or initialises if it does not exist.

        ``rewrite_email=False`` skips the ``force_email_prop_as_creator``
        rewrite, for a lookup that just matched the stored creator.
        """
        if not actor_id and not self.id:
            return None
        elif not actor_id:
            actor_id = self.id
        if self.handle and self.actor and len(self.actor) > 0:
            return self.actor
        if self.handle:
            self.actor = self.handle.get(actor_id=actor_id)
        else:
            self.actor = None
        if self.actor and len(self.actor) > 0:
            self.id = self.actor["id"]
            self.creator = self.actor["creator"]
            self.passphrase = self.actor["passphrase"]
            self.store = attribute.InternalStore(actor_id=self.id, config=self.config)
            self.property = property.PropertyStore(actor_id=self.id, config=self.config)
            self.property_lists = property.PropertyListStore(
                actor_id=self.id, config=self.config
            )
            if (
                rewrite_email
                and self.config
                and self.config.force_email_prop_as_creator
            ):
                em = self.store.email
                if em and em.lower() != self.creator:
                    try:
                        self.modify(creator=em.lower())
                    except CreatorTaken:  # folds DbError: email held elsewhere
                        logger.warning(
                            f"Actor {self.id}: stored email is another actor's "
                            "creator; creator left unchanged"
                        )
        else:
            self.id = None
            self.creator = None
            self.passphrase = None
        return self.actor

    def get_from_property(
        self, name: str = "oauthId", value: str | None = None
    ) -> None:
        """Initialise an actor by matching on a stored property.

        Use with caution as the property's value de-facto becomes
        a security token. If multiple properties are found with the
        same value, no actor will be initialised.
        Also note that this is a costly operation as all properties
        of this type will be retrieved and proceessed.
        """
        actor_id = property.Property(
            name=name, value=value, config=self.config
        ).get_actor_id()
        if not actor_id:
            self.id = None
            self.creator = None
            self.passphrase = None
            return
        self.get(actor_id=actor_id)

    def get_from_creator(self, creator: str | None = None) -> bool:
        """Initialise an actor by matching on creator/email.

        Returns True if an actor could be loaded, otherwise False. With
        ``unique_creator`` on, the one holder of a non-exempt creator is read
        consistently (:meth:`DbActorProtocol.get_creator_holder`) and the rest
        of this docstring does not apply. When
        several actors share the creator (possible with ``unique_creator``
        off) the pick is, in order: a vouched actor, any other unvouched
        actor, a ``factory`` one; the lowest id within each group.

        The actors are listed by id only and read in id order: each is
        loaded (one gone since the listing is left out) and its marker
        classified, until the first vouched actor, which is the pick. After
        it at most :data:`actingweb.oauth2.SWEEP_LIMIT` more markers are read
        to find the ``factory`` actors a sign-in removes beside it, so the
        reads are bounded by the ranked prefix plus that limit.

        Raises ``DbError`` on a read fault, and when a marker in the ranked
        prefix cannot be read: ranking an unreadable actor like an unvouched
        one could strand the owner's actor behind it (BR).

        Sets ``factory_sibling_ids`` (the ``factory`` actors classified beside
        the pick), ``creator_ids`` (every id the listing returned) and
        ``creator_classes`` (the class of every actor read) for the sign-in to
        reuse instead of listing again.
        """
        from .oauth2 import SWEEP_LIMIT, classify_marker

        self.id = None
        self.creator = None
        self.passphrase = None
        self.factory_sibling_ids = []
        self.creator_ids = []
        self.creator_classes = {}

        if not self.config or not creator:
            return False

        lookup_creator = creator.lower() if "@" in creator else creator
        db = get_actor(self.config)
        if self.config.unique_creator and not is_exempt(lookup_creator):
            # Enforced: one holder, read consistently from the creators
            # record (DynamoDB) or the unique row (PostgreSQL), not from the
            # lagging index; nothing to rank and no siblings to sweep. A
            # stale record (its actor gone, or holding another creator) is
            # removed and answers False, so the create that follows takes
            # the address.
            holder = db.get_creator_holder(lookup_creator)
            self.creator_ids = [holder] if holder else []
            if not holder:
                return False
            # The row as stored, read consistently, before any force-email
            # rewrite could change the creator being looked up.
            row = get_actor(self.config).get(actor_id=holder)
            if not row or normalise_creator(row.get("creator")) != lookup_creator:
                # A stale record: its actor is gone, or holds another creator
                # now (a release that faulted, an old process's delete or
                # rename). Loading it would sign this identity into that
                # actor; repairing it lets the create that follows take the
                # address.
                repaired = db.release_stale_creator(lookup_creator, holder)
                logger.warning(
                    f"The creator record of {lookup_creator!r} named actor "
                    f"{holder}, which no longer holds it; "
                    + ("removed" if repaired else "it changed meanwhile")
                )
                self.creator_ids = []
                return False
            self.get(actor_id=holder, rewrite_email=False)
            if self.id and normalise_creator(self.creator) != lookup_creator:
                # Renamed between the check and the load: not this identity's
                # actor any more. The create that follows settles the record.
                logger.warning(
                    f"Actor {holder} was renamed away from {lookup_creator!r} "
                    "during the sign-in lookup; not loaded"
                )
                self.id = None
                self.creator = None
                self.passphrase = None
                self.actor = None
                self.store = None
                self.property = None
                self.property_lists = None
                self.creator_ids = []
                return False
            return bool(self.id)

        listed = db.get_by_creator(creator=lookup_creator, ids_only=True) or []
        rows: list[dict[str, Any]] = [listed] if isinstance(listed, dict) else listed
        ids = sorted({str(r["id"]) for r in rows if r and r.get("id")})
        self.creator_ids = ids
        if not ids:
            return False
        if len(ids) == 1:
            self.get(actor_id=ids[0])
            return bool(self.id)

        logger.warning(f"Multiple actors share creator {lookup_creator!r}: {ids}")
        rank_of = {"vouched": 0, "unvouched": 1, "replace": 2}
        classes: dict[str, str] = {}
        ranked: list[tuple[int, str]] = []
        tail_left: int | None = None
        for candidate_id in ids:
            if tail_left is not None:
                # Past the pick: only factory actors to remove beside it
                # matter, and one whose marker cannot be read is not touched.
                if tail_left <= 0:
                    break
                tail_left -= 1
                tail_class = classify_marker(self.config, candidate_id, lookup_creator)
                if tail_class is not None:
                    classes[candidate_id] = tail_class
                    # A fallback if the pick vanishes before its load.
                    ranked.append((rank_of[tail_class], candidate_id))
                continue
            if not db.get(actor_id=candidate_id):
                continue  # deleted since the index listed it
            marker = classify_marker(self.config, candidate_id, lookup_creator)
            if marker is None:
                raise DbError("actor marker read", candidate_id)
            classes[candidate_id] = marker
            rank = rank_of[marker]
            ranked.append((rank, candidate_id))
            if rank == 0:
                tail_left = SWEEP_LIMIT
        self.creator_classes = classes
        # Best first; an actor deleted between the ranking and its load is
        # passed over for the next one, as the per-row loop did before 3.16.
        for _rank, candidate_id in sorted(ranked):
            self.get(actor_id=candidate_id)
            if self.id:
                break
        if not self.id:
            return False
        self.factory_sibling_ids = [
            i for i, c in classes.items() if c == "replace" and i != self.id
        ]
        return True

    def create(
        self,
        url: str,
        creator: str,
        passphrase: str,
        actor_id: str | None = None,
        delete: bool = False,
        trustee_root: str | None = None,
        hooks: Any = None,
        auth_method: str = "app",
        *,
        replace_holder: str | None = None,
    ) -> bool:
        """ "Creates a new actor and persists it.

        With ``unique_creator`` a non-exempt creator another actor holds
        raises :class:`~actingweb.db.exceptions.CreatorTaken`. If delete is
        True, the existing actors with the same creator are deleted first
        (not atomically). ``replace_holder`` names the actor that holds the
        creator now: the backend moves the creator to the new actor in the
        same step as the create (:meth:`DbActorProtocol.replace_creator_holder`),
        and the caller removes the old actor afterwards. Without the flag, a
        create never returns an existing actor.

        ``auth_method`` records how the actor came to exist and is written to
        the ``_internal`` store before ``actor_created`` fires, only when a
        row was actually persisted. It is a trust assertion: ``"app"`` means
        the calling application vouches for ``creator``; pass ``"factory"``
        for anything created from unauthenticated input. An unvouched actor
        (see :func:`actingweb.oauth2.is_vouched_actor`) is replaced or
        cleaned when a sign-in later proves the address.

        Raises:
            ValueError: A caller-supplied ``actor_id`` contains ``$`` (it
                separates an actor's property-list side partition,
                ``{actor_id}$aux``) or is longer than 251 characters (the
                side partition key must fit PostgreSQL's 255-character
                ``properties.id``). Raised before any write; generated ids
                are 32 hex characters and never affected.
        """
        if actor_id is not None and ("$" in actor_id or len(actor_id) > 251):
            raise ValueError(
                "A caller-supplied actor id may not contain '$' or be longer "
                "than 251 characters"
            )
        seed = url
        now = datetime.datetime.now(datetime.UTC)
        seed += now.strftime("%Y%m%dT%H%M%S%f")
        # Random bytes too: two creates in the same microsecond (two
        # processes) would otherwise get the same id, and the marker written
        # ahead of the row would land in the other actor's bucket.
        seed += os.urandom(16).hex()
        if len(creator) > 0:
            self.creator = creator
        else:
            self.creator = DEFAULT_CREATOR
        if is_reserved(self.creator):
            # "#…" and "#dup-" belong to the uniqueness bookkeeping; only
            # actingweb-unique-creators writes them, through modify().
            logger.warning(
                f"Refusing to create an actor with reserved creator {self.creator!r}"
            )
            self.creator = None
            return False
        if self.config and self.config.unique_creator:
            # The backend enforces uniqueness: a create for a held creator
            # raises CreatorTaken, which propagates. There is no passphrase
            # match any more (it returned the existing actor to whoever
            # guessed its passphrase).
            if delete:
                # Not atomic: the caller asked for the existing actors to go.
                # A held creator has one holder, read consistently (the
                # index can still miss a just-created one).
                db = get_actor(self.config)
                if is_exempt(self.creator):
                    ids = [
                        c["id"]
                        for c in db.get_by_creator(
                            creator=self.creator, consistent=True
                        )
                        or []
                        if c
                    ]
                else:
                    holder = db.get_creator_holder(self.creator)
                    ids = [holder] if holder else []
                for victim_id in ids:
                    # The constructor loads it; delete() acts on a loaded row.
                    victim = Actor(actor_id=victim_id, config=self.config)
                    if victim.id:
                        victim.delete()
            elif (
                self.config.force_email_prop_as_creator
                and self.creator == DEFAULT_CREATOR
            ):
                # Uniqueness turned on later can leave many actors with the
                # default creator: move each to its stored email.
                existing = get_actor(self.config).get_by_creator(
                    creator=self.creator, consistent=True
                )
                # Loading each (the constructor does) moves it to its stored
                # email; get()'s rewrite leaves an address another actor
                # holds alone.
                for c in existing or []:
                    if c:
                        Actor(actor_id=c["id"], config=self.config)

        if passphrase and len(passphrase) > 0:
            self.passphrase = passphrase
        else:
            self.passphrase = self.config.new_token() if self.config else ""
        if actor_id:
            self.id = actor_id
        else:
            self.id = self.config.new_uuid(seed) if self.config else ""
        if not self.handle and self.config:
            self.handle = get_actor(self.config)
        # A generated id is new, so its bucket is empty and nobody else
        # writes it: the marker goes in before the row. The row (and under
        # unique_creator its record) then never becomes visible to a sign-in
        # without it; unmarked, a sign-in arriving in between would take the
        # new actor for a legacy one and clean it in place. A caller-supplied
        # id (a system actor) can own older buckets, and keeps the marker
        # after the row (below).
        pre_marked: attribute.InternalStore | None = None
        if self.handle and not actor_id and auth_method and self.config:
            pre_marked = attribute.InternalStore(actor_id=self.id, config=self.config)
            pre_marked.mark_empty()
            try:
                marked = self._write_marker(pre_marked, auth_method)
            except DbError:  # folds DbError: re-raised (503), nothing created
                self.id = None
                self.passphrase = None
                self.handle = None
                raise
            if not marked:
                logger.error(
                    f"Actor {self.id}: the auth_method marker did not land; "
                    "nothing created"
                )
                self.id = None
                self.passphrase = None
                self.handle = None
                return False
        created = False
        if self.handle:
            try:
                created = self.handle.create(
                    creator=self.creator,
                    passphrase=self.passphrase,
                    actor_id=self.id,
                    replace_holder=replace_holder,
                )
            except CreatorTaken:
                self._drop_pre_marker(pre_marked, self.id)
                self.id = None
                self.passphrase = None
                self.handle = None
                self.store = None
                raise
            except DbError:
                # Ambiguous: the create may have committed (a lost
                # acknowledgement). Keep the marker: on an unused id it is an
                # orphan bucket, on a committed row it is what keeps the next
                # sign-in from cleaning it as legacy.
                raise
        # Generated ids are never reused, but create(actor_id=...) accepts a
        # caller-supplied one. A stale tombstone would report the new actor as
        # deleted for the rest of the retention window.
        #
        # Only when the row was actually persisted. create() returns False if
        # the id is already taken — including by an actor mid-deletion, whose
        # row survives until the wipe's last step — and clearing the tombstone
        # there would strip the marker off a deletion still in progress,
        # reopening the very race it guards. A backend insert failure is the
        # same shape: nothing created, so nothing to un-tombstone.
        if created:
            deletion.clear_actor_tombstone(self.id, self.config)
        if not created:
            # The id was taken (by a live actor, or one mid-deletion) or the
            # insert failed: nothing was created, and the bucket under this id
            # is not ours to write. Unbind, so a caller that ignores the False
            # cannot modify or delete the actor that holds the id. With a
            # generated id that bucket is not touched either: nothing here
            # proves the marker in it is the one this create wrote.
            self.id = None
            self.passphrase = None
            self.handle = None
            self.store = None
            return False
        if pre_marked is not None:
            self.store = pre_marked
        else:
            self.store = attribute.InternalStore(actor_id=self.id, config=self.config)
            if not actor_id:
                # A generated id is new, so its bucket is empty; skip the
                # read. A caller-supplied one (a system actor) can own older
                # buckets.
                self.store.mark_empty()
        self.property = property.PropertyStore(actor_id=self.id, config=self.config)
        self.property_lists = property.PropertyListStore(
            actor_id=self.id, config=self.config
        )

        # Record how the actor was created, before anything else lands in
        # its bucket, so a rollback has only the row to remove (a generated
        # id already has it, written before the row).
        if self.store and auth_method and pre_marked is None:
            try:
                marked = self._write_marker(self.store, auth_method)
                fault: DbError | None = None
            except DbError as e:  # folds DbError: re-raised after the rollback
                # A store fault answers 503, like the trustee_root write
                # below; a mismatch stays the False refusal.
                marked, fault = False, e
            if not marked:
                # An actor without its marker reads as legacy, and the next
                # sign-in would wipe it. Undo the creation: only the row, since
                # a fixed id (a system actor) can own buckets that predate it.
                if replace_holder is not None:
                    # The swap moved the creator to this row: deleting it
                    # would leave the creator held by nobody while the old
                    # holder lives on. Keep it; unmarked, the next sign-in
                    # cleans it in place.
                    logger.error(
                        f"Actor {self.id}: the auth_method marker did not land "
                        f"after taking the creator from {replace_holder}; "
                        "keeping the row"
                    )
                    rolled_back = True
                else:
                    logger.error(
                        f"Actor {self.id}: the auth_method marker did not land; "
                        "removing the new actor row"
                    )
                    rolled_back = False

                try:
                    rolled_back = rolled_back or bool(
                        self.handle and self.handle.delete()
                    )
                except Exception as e:  # folds DbError: rollback of a create whose marker did not land; logged, next sign-in cleans the row
                    logger.error(f"Actor {self.id}: row removal raised: {e}")
                    rolled_back = False
                if not rolled_back:
                    logger.error(
                        f"Actor {self.id}: removing the unmarked actor failed; "
                        "its next sign-in cleans it in place"
                    )
                self.id = None
                self.passphrase = None
                self.handle = None
                self.store = None
                if fault is not None:
                    raise fault
                return False

        if (
            trustee_root
            and isinstance(trustee_root, str)
            and len(trustee_root) > 0
            and self.store
        ):
            try:
                self.store.trustee_root = trustee_root
            except DbError:
                # The actor would exist without its trustee_root and without
                # actor_created having fired. Remove the row, as for a lost
                # marker, and let the fault reach the caller (503): a retry
                # starts clean instead of leaving an unannounced actor.
                logger.error(
                    f"Actor {self.id}: the trustee_root write faulted; "
                    "removing the new actor row"
                )
                try:
                    # Not after a swap: the row holds the creator now (see
                    # the marker rollback above).
                    if self.handle and replace_holder is None:
                        self.handle.delete()
                except Exception as e:  # folds DbError: rollback inside the DbError handler, which re-raises the original fault
                    logger.error(f"Actor {self.id}: row removal raised: {e}")
                self.id = None
                self.passphrase = None
                self.handle = None
                self.store = None
                raise

        # Execute actor_created lifecycle hook if hooks are provided
        if hooks:
            try:
                from actingweb.interface.actor_interface import ActorInterface

                registry = getattr(self.config, "service_registry", None)
                actor_interface = ActorInterface(self, service_registry=registry)
                hooks.execute_lifecycle_hooks("actor_created", actor_interface)
            except Exception as e:  # folds DbError: notification after commit
                # Log hook execution error but don't fail actor creation
                logger.warning(
                    f"Actor created successfully but lifecycle hook failed: {e}"
                )

        return True

    def creator_change_pinned(self, creator: str) -> bool:
        """Whether ``force_email_prop_as_creator`` refuses changing the creator
        to ``creator``: on, with a stored email that ``creator`` is not (nor
        ``"trustee"``). :meth:`get` would put the stored email back on the next
        load, and a sign-in for the new address in between would resolve to
        this actor. False when ``_internal`` cannot be read."""
        store = self.store
        if not self.config or not self.config.force_email_prop_as_creator:
            return False
        if not store or not store.loaded:
            return False
        own_email = store.email
        target = creator.lower() if "@" in creator else creator
        return (
            isinstance(own_email, str)
            and bool(own_email)
            and target not in ("trustee", own_email.lower())
        )

    def modify_creator_unvouched(self, creator: str) -> bool:
        """Change the creator to an address nobody proved, and unvouch.

        A sign-in that later proves ``creator`` then cleans the actor in place
        instead of adopting it as is (:func:`actingweb.oauth2.adopt_actor`).
        The marker becomes ``creator_changed``, written and confirmed before
        the creator changes, except when the change hands the actor to nobody
        new: ``"trustee"`` (the protocol's handoff; no sign-in resolves to it),
        the actor's own stored ``email`` (a provider or the emailed link wrote
        it), or the current creator. A marker in
        :data:`actingweb.oauth2.REPLACE_AUTH_METHODS` (``"factory"``) is kept:
        that actor is already unvouched, and is replaced rather than cleaned.

        Returns False when the creator did not change, including when
        :meth:`creator_change_pinned` refuses it. The previous marker is
        restored then, but only once a fresh read shows the stored creator
        unchanged (a failure can be a lost acknowledgement of a write that
        landed). Raises only ``DbError``, with the actor left unvouched.
        """
        from actingweb.oauth2 import REPLACE_AUTH_METHODS

        store = self.store
        if not store or not store.loaded or not self.config:
            logger.error(f"Actor {self.id}: _internal unreadable; creator not changed")
            return False
        if self.creator_change_pinned(creator):
            logger.warning(
                f"Actor {self.id}: creator is pinned to the stored email "
                "(force_email_prop_as_creator); creator not changed"
            )
            return False
        if is_refused_from_callers(creator):
            # The uniqueness bookkeeping's values and the system actors'.
            logger.warning(f"Actor {self.id}: creator {creator!r} is reserved")
            return False

        target = creator.lower() if "@" in creator else creator
        own_email = store.email
        previous_marker = store.auth_method
        unvouch = (
            target != self.creator
            and target != "trustee"
            and not (isinstance(own_email, str) and own_email.lower() == target)
            and previous_marker not in REPLACE_AUTH_METHODS
        )
        # Marker first: a change that lands without it would leave the actor
        # vouched under an address nobody proved.
        if unvouch and not store.set_confirmed("auth_method", "creator_changed"):
            logger.error(
                f"Actor {self.id}: could not unvouch before a creator change; "
                "creator not changed"
            )
            return False
        original = self.creator
        fault: DbError | None = None
        try:
            if self.modify(creator=creator):
                return True
        except DbError as e:  # folds DbError: raised after the marker restore below
            # Ambiguous: the creator may have landed. Put the marker back
            # only if the stored creator is unchanged, then raise.
            fault = e
        except Exception as e:
            logger.error(f"Actor {self.id}: creator change failed: {e}")
        if unvouch:
            try:
                row = get_actor(self.config).get(actor_id=self.id)
            except DbError as e:  # folds DbError: unconfirmed, so the marker stays
                if fault is None:
                    raise
                logger.error(f"Actor {self.id}: creator re-read faulted: {e}")
                row = None
            if not row or row.get("creator") != original:
                logger.error(
                    f"Actor {self.id}: creator change failed and the stored "
                    "creator could not be confirmed unchanged; auth_method left "
                    "'creator_changed'"
                )
            elif not self._restore_marker(store, previous_marker, original):
                # Unvouched, so the owner's next sign-in cleans it.
                logger.error(
                    f"Actor {self.id}: creator unchanged but auth_method is "
                    f"still 'creator_changed' (was {previous_marker!r})"
                )
        if fault is not None:
            raise fault
        return False

    def modify(self, creator: str | None = None, passphrase: str | None = None) -> bool:
        """Change the actor's creator and/or passphrase.

        Returns the backend result. DynamoDB raises when the save fails and
        PostgreSQL returns ``False``; callers that must know treat both as
        failure. The in-memory values change only after the backend reported
        success.
        """
        if not self.handle or not (creator or passphrase):
            logger.debug("Attempted modify of actor with no handle or no param changed")
            return False
        if creator and "@" in creator:
            creator = creator.lower()
        ok = self.handle.modify(
            creator=creator or None,
            passphrase=passphrase.encode("utf-8") if passphrase else None,
        )
        if not ok:
            return False
        if creator:
            self.creator = creator
            if self.actor:
                self.actor["creator"] = creator
        if passphrase:
            self.passphrase = passphrase
            if self.actor:
                self.actor["passphrase"] = passphrase
        return True

    def delete(self, notify_peers: bool = True) -> bool:
        """Deletes an actor and cleans up all relevant stored data.

        ``notify_peers=False`` skips the remote DELETE calls to peers and
        trustees (``requests.delete``) and keeps every local cleanup. Use it
        when the peer URLs are not trustworthy.

        Returns True when the actor row is gone. A backend fault raises
        ``DbError``.

        The trust and subscription lists are read **first**, strictly: a read
        fault raises before anything is deleted and before the tombstone is
        written, so a throttle never deletes an actor without notifying its
        peers (B8). Once the reads pass, the tombstone is written and the wipe
        runs; a fault after that point is the tombstone path's to finish.

        The actor row is removed **last**, so the actor keeps resolving for the
        duration of the wipe. Existence checks therefore fail open here, and
        that is why the tombstone is written before the first destructive
        step: it is readable throughout the wipe, whereas ``get()`` cannot
        distinguish mid-deletion from live. See :mod:`actingweb.deletion`.
        """
        if not self.handle:
            logger.debug("Attempted delete of actor with no handle")
            return False
        subs = subscription.Subscriptions(actor_id=self.id, config=self.config)
        subs.fetch()  # strict: raises DbError before anything is removed
        trusts = trust.Trusts(actor_id=self.id, config=self.config)
        relationships = trusts.fetch()  # strict, same
        deletion.mark_actor_deleted(self.id, self.config)
        self.delete_peer_trustee(shorttype="*", notify_peers=notify_peers)
        if not self.property_list:
            self.property_list = property.Properties(
                actor_id=self.id, config=self.config
            )
        self.property_list.delete()
        subs.delete()
        if relationships:
            for rel in relationships:
                if isinstance(rel, dict) and "peerid" in rel:
                    self.delete_reciprocal_trust(
                        peerid=rel.get("peerid", ""),
                        delete_peer=True,
                        notify_peers=notify_peers,
                    )
        trusts.delete()
        buckets = attribute.Buckets(actor_id=self.id, config=self.config)
        buckets.delete()
        return bool(self.handle.delete())

    ######################
    # Advanced operations
    ######################

    def set_property(self, name, value):
        """Sets an actor's property name to value. (DEPRECATED, use actor's property store!)"""
        if self.property:
            self.property[name] = value

    def get_property(self, name):
        """Retrieves a property object named name. (DEPRECATED, use actor's property store!)"""
        return DummyPropertyClass(self.property[name] if self.property else None)

    def delete_property(self, name):
        """Deletes a property name. (DEPRECATED, use actor's property store!)"""
        if self.property:
            self.property[name] = None

    def delete_properties(self):
        """Deletes all properties."""
        if not self.property_list:
            self.property_list = property.Properties(
                actor_id=self.id, config=self.config
            )
        return self.property_list.delete()

    def get_properties(self):
        """Retrieves properties from db and returns a dict."""
        self.property_list = property.Properties(actor_id=self.id, config=self.config)
        return self.property_list.fetch()

    def delete_peer_trustee(self, shorttype=None, peerid=None, notify_peers=True):
        if not peerid and not shorttype:
            return False
        if shorttype == "*":
            if self.config and self.config.actors:
                for t in self.config.actors:
                    self.delete_peer_trustee(shorttype=t, notify_peers=notify_peers)
            return True
        if (
            shorttype
            and self.config
            and self.config.actors
            and shorttype not in self.config.actors
        ):
            logger.error(f"Got a request to delete an unknown actor type({shorttype})")
            return False
        peer_data = None
        new_peer = None
        if peerid:
            new_peer = peertrustee.PeerTrustee(
                actor_id=self.id, peerid=peerid, config=self.config
            )
            peer_data = new_peer.get()
            if (
                isinstance(peer_data, bool)
                or not peer_data
                or (isinstance(peer_data, dict) and len(peer_data) == 0)
            ):
                return False
        elif shorttype:
            new_peer = peertrustee.PeerTrustee(
                actor_id=self.id, short_type=shorttype, config=self.config
            )
            peer_data = new_peer.get()
            if (
                isinstance(peer_data, bool)
                or not peer_data
                or (isinstance(peer_data, dict) and len(peer_data) == 0)
            ):
                return False
        if not peer_data or isinstance(peer_data, bool):
            return False
        if notify_peers:
            logger.info(f"Deleting peer actor at {peer_data['baseuri']}")
            u_p = b"trustee:" + peer_data["passphrase"].encode("utf-8")
            headers = {
                "Authorization": "Basic " + base64.b64encode(u_p).decode("utf-8"),
            }
            try:
                response = requests.delete(
                    url=peer_data["baseuri"], headers=headers, timeout=(5, 10)
                )
                self.last_response_code = response.status_code
                self.last_response_message = (
                    response.content.decode("utf-8", "ignore")
                    if isinstance(response.content, bytes)
                    else str(response.content)
                )
            except Exception:  # folds DbError: peer HTTP only
                logger.debug(
                    "Not able to delete peer actor remotely due to network issues"
                )
                self.last_response_code = 408
                return False
            if response.status_code < 200 or response.status_code > 299:
                logger.debug(
                    "Not able to delete peer actor remotely, peer is unwilling"
                )
                return False
        # Delete trust, peer is already deleted remotely
        if peer_data and not self.delete_reciprocal_trust(
            peerid=peer_data["peerid"], delete_peer=False, notify_peers=notify_peers
        ):
            logger.debug("Not able to delete peer actor trust in db")
        if new_peer and not new_peer.delete():
            logger.debug("Not able to delete peer actor in db")
            return False
        return True

    def get_peer_trustee(self, shorttype=None, peerid=None):
        """Get a peer, either existing or create it as trustee

        Will retrieve an existing peer or create a new and establish trust.
        If no trust exists, a new trust will be established.
        Use either peerid to target a specific known peer, or shorttype to
        allow creation of a new peer if none exists
        """
        if not peerid and not shorttype:
            return None
        if (
            shorttype
            and self.config
            and self.config.actors
            and shorttype not in self.config.actors
        ):
            logger.error(f"Got a request to create an unknown actor type({shorttype})")
            return None
        if peerid:
            new_peer = peertrustee.PeerTrustee(
                actor_id=self.id, peerid=peerid, config=self.config
            )
        else:
            new_peer = peertrustee.PeerTrustee(
                actor_id=self.id, short_type=shorttype, config=self.config
            )
        peer_data = new_peer.get()
        if peer_data and not isinstance(peer_data, bool) and len(peer_data) > 0:
            logger.debug("Found peer in getPeer, now checking existing trust...")
            dbtrust = trust.Trust(
                actor_id=self.id, peerid=peer_data["peerid"], config=self.config
            )
            new_trust = dbtrust.get()
            if new_trust and len(new_trust) > 0:
                return peer_data
            logger.debug("Did not find existing trust, will create a new one")
        factory = ""
        if (
            self.config
            and self.config.actors
            and shorttype
            and shorttype in self.config.actors
        ):
            factory = self.config.actors[shorttype]["factory"]
        # If peer did not exist, create it as trustee
        if not peer_data or isinstance(peer_data, bool) or len(peer_data) == 0:
            if len(factory) == 0:
                logger.error(
                    f"Peer actor of shorttype({shorttype}) does not have factory set."
                )
            params = {
                "creator": "trustee",
                "trustee_root": (self.config.root + self.id) if self.config else "",
            }
            data = json.dumps(params)
            logger.debug(f"Creating peer actor at factory({factory})")
            response = None
            try:
                response = requests.post(
                    url=factory,
                    data=data,
                    timeout=(5, 10),
                    headers={"Content-Type": "application/json"},
                )
                if response:
                    self.last_response_code = response.status_code
                    self.last_response_message = (
                        response.content.decode("utf-8", "ignore")
                        if isinstance(response.content, bytes)
                        else str(response.content)
                    )
            except Exception:  # folds DbError: peer HTTP only
                logger.debug("Not able to create new peer actor")
                self.last_response_code = 408
            logger.info(f"Created peer actor, response code: {self.last_response_code}")
            if self.last_response_code < 200 or self.last_response_code > 299:
                return None
            try:
                if response and response.content:
                    content_str = (
                        response.content.decode("utf-8", "ignore")
                        if isinstance(response.content, bytes)
                        else str(response.content)
                    )
                    data = json.loads(content_str)
                else:
                    data = {}
            except (TypeError, ValueError, KeyError):
                logger.warning(
                    f"Not able to parse response when creating peer at factory({factory})"
                )
                return None
            if response and "Location" in response.headers:
                baseuri = response.headers["Location"]
            elif response and "location" in response.headers:
                baseuri = response.headers["location"]
            else:
                logger.warning(
                    "No location uri found in response when creating a peer as trustee"
                )
                baseuri = ""
            res = self.get_peer_info(baseuri)
            if (
                not res
                or res["last_response_code"] < 200
                or res["last_response_code"] >= 300
            ):
                return None
            info_peer = res["data"]
            if (
                not info_peer
                or ("id" in info_peer and not info_peer["id"])
                or ("type" in info_peer and not info_peer["type"])
            ):
                logger.info(
                    f"Received invalid peer info when trying to create peer actor at: {factory}"
                )
                return None
            new_peer = peertrustee.PeerTrustee(
                actor_id=self.id,
                peerid=info_peer["id"],
                peer_type=info_peer["type"],
                config=self.config,
            )
            if not new_peer.create(baseuri=baseuri, passphrase=data["passphrase"]):
                logger.error(
                    f"Failed to create in db new peer Actor({self.id}) at {baseuri}"
                )
                return None
        # Now peer exists, create trust
        new_peer_data = new_peer.get()
        if not new_peer_data or isinstance(new_peer_data, bool):
            return None
        secret = self.config.new_token() if self.config else ""
        relationship = ""
        if (
            self.config
            and self.config.actors
            and shorttype
            and shorttype in self.config.actors
        ):
            relationship = self.config.actors[shorttype]["relationship"]
        new_trust = self.create_reciprocal_trust(
            url=new_peer_data["baseuri"],
            secret=secret,
            desc="Trust from trustee to " + (shorttype or ""),
            relationship=relationship,
        )
        if not new_trust or len(new_trust) == 0:
            logger.warning(
                f"Not able to establish trust relationship with peer at factory({factory})"
            )
        else:
            # Approve the relationship
            params = {
                "approved": True,
            }
            u_p = b"trustee:" + new_peer_data["passphrase"].encode("utf-8")
            headers = {
                "Authorization": "Basic " + base64.b64encode(u_p).decode("utf-8"),
                "Content-Type": "application/json",
            }
            data = json.dumps(params)
            try:
                response = requests.put(
                    url=new_peer_data["baseuri"]
                    + "/trust/"
                    + relationship
                    + "/"
                    + (self.id or ""),
                    data=data,
                    headers=headers,
                    timeout=(5, 10),
                )
                if response:
                    self.last_response_code = response.status_code
                    self.last_response_message = (
                        response.content.decode("utf-8", "ignore")
                        if isinstance(response.content, bytes)
                        else str(response.content)
                    )
            except Exception:  # folds DbError: peer HTTP only
                self.last_response_code = 408
                self.last_response_message = (
                    "Not able to approve peer actor trust remotely"
                )
            if self.last_response_code < 200 or self.last_response_code > 299:
                logger.debug("Not able to delete peer actor remotely")
        return new_peer_data

    def get_trust_relationship(self, peerid=None):
        if not peerid:
            return None
        return trust.Trust(actor_id=self.id, peerid=peerid, config=self.config).get()

    def get_trust_relationships(self, relationship="", peerid="", trust_type=""):
        """Retrieves all trust relationships or filtered."""
        trust_list = trust.Trusts(actor_id=self.id, config=self.config)
        relationships = trust_list.fetch()
        rels = []
        if relationships:
            for rel in relationships:
                if isinstance(rel, dict):
                    if len(relationship) > 0 and relationship != rel.get(
                        "relationship", ""
                    ):
                        continue
                    if len(peerid) > 0 and peerid != rel.get("peerid", ""):
                        continue
                    if len(trust_type) > 0 and trust_type != rel.get("type", ""):
                        continue
                rels.append(rel)
        return rels

    def modify_trust_and_notify(
        self,
        relationship=None,
        peerid=None,
        baseuri="",
        secret="",
        desc="",
        approved=None,
        verified=None,
        verification_token=None,
        peer_approved=None,
        # Client metadata for OAuth2 clients
        client_name=None,
        client_version=None,
        client_platform=None,
        oauth_client_id=None,
        # Connection tracking
        last_accessed=None,
        last_connected_via=None,
    ):
        """Changes a trust relationship and noties the peer if approval is changed."""
        if not relationship or not peerid:
            return False
        relationships = self.get_trust_relationships(
            relationship=relationship, peerid=peerid
        )
        if not relationships:
            return False
        this_trust = relationships[0]

        # IMPORTANT: Save approval to database BEFORE notifying peer
        # This prevents race condition where peer tries to subscribe back
        # before our approval is saved
        dbtrust = trust.Trust(actor_id=self.id, peerid=peerid, config=self.config)
        try:
            result = dbtrust.modify(
                baseuri=baseuri,
                secret=secret,
                desc=desc,
                approved=approved,
                verified=verified,
                verification_token=verification_token,
                peer_approved=peer_approved,
                client_name=client_name,
                client_version=client_version,
                client_platform=client_platform,
                oauth_client_id=oauth_client_id,
                last_accessed=last_accessed,
                last_connected_via=last_connected_via,
            )
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Exception in dbtrust.modify: {e}", exc_info=True)
            return False

        # Now that approval is saved, notify peer so their auto-subscribe will succeed
        headers = {}
        if approved is True and this_trust["approved"] is False:
            params = {
                "approved": True,
            }
            requrl = this_trust["baseuri"] + "/trust/" + relationship + "/" + self.id
            if this_trust["secret"]:
                headers = {
                    "Authorization": "Bearer " + this_trust["secret"],
                    "Content-Type": "application/json",
                }
            data = json.dumps(params)
            # Note the POST here instead of PUT. POST is used to used to notify about
            # state change in the relationship (i.e. not change the object as PUT
            # would do)
            logger.debug(
                "Trust relationship has been approved, notifying peer at url("
                + requrl
                + ")"
            )
            try:
                response = requests.post(
                    url=requrl, data=data, headers=headers, timeout=(5, 10)
                )
                self.last_response_code = response.status_code
                self.last_response_message = (
                    response.content.decode("utf-8", "ignore")
                    if isinstance(response.content, bytes)
                    else str(response.content)
                )
            except Exception:  # folds DbError: peer HTTP only
                logger.debug("Not able to notify peer at url(" + requrl + ")")
                self.last_response_code = 500
        return result

    async def modify_trust_and_notify_async(
        self,
        relationship=None,
        peerid=None,
        baseuri="",
        secret="",
        desc="",
        approved=None,
        verified=None,
        verification_token=None,
        peer_approved=None,
        # Client metadata for OAuth2 clients
        client_name=None,
        client_version=None,
        client_platform=None,
        oauth_client_id=None,
        # Connection tracking
        last_accessed=None,
        last_connected_via=None,
    ):
        """Async version of modify_trust_and_notify - prevents blocking on peer notification.

        Changes a trust relationship and notifies the peer if approval is changed.
        Database operations remain synchronous, but peer HTTP notification is async.
        """
        if not relationship or not peerid:
            return False
        relationships = self.get_trust_relationships(
            relationship=relationship, peerid=peerid
        )
        if not relationships:
            return False
        this_trust = relationships[0]

        # IMPORTANT: Save approval to database BEFORE notifying peer
        # This prevents race condition where peer tries to subscribe back
        # before our approval is saved
        dbtrust = trust.Trust(actor_id=self.id, peerid=peerid, config=self.config)
        result = dbtrust.modify(
            baseuri=baseuri,
            secret=secret,
            desc=desc,
            approved=approved,
            verified=verified,
            verification_token=verification_token,
            peer_approved=peer_approved,
            client_name=client_name,
            client_version=client_version,
            client_platform=client_platform,
            oauth_client_id=oauth_client_id,
            last_accessed=last_accessed,
            last_connected_via=last_connected_via,
        )

        # Now that approval is saved, notify peer async so their auto-subscribe will succeed
        if approved is True and this_trust["approved"] is False:
            from .aw_proxy import AwProxy

            logger.debug(
                f"Trust relationship approved, notifying peer async at {this_trust['baseuri']}"
            )
            try:
                proxy = AwProxy(
                    peer_target={
                        "baseuri": this_trust["baseuri"],
                        "secret": this_trust.get("secret", ""),
                    },
                    config=self.config,
                )
                await proxy.change_resource_async(
                    path=f"trust/{relationship}/{self.id}",
                    params={"approved": True},
                )
                self.last_response_code = proxy.last_response_code
                self.last_response_message = (
                    proxy.last_response_message.decode("utf-8", "ignore")
                    if isinstance(proxy.last_response_message, bytes)
                    else str(proxy.last_response_message)
                )
            except Exception as e:  # folds DbError: peer HTTP only
                logger.debug(f"Not able to notify peer async: {e}")
                self.last_response_code = 500
        return result

    def create_reciprocal_trust(
        self,
        url,
        secret=None,
        desc="",
        relationship="",  # trust type/permission level (e.g., "friend", "admin") - goes in URL
        trust_type="",  # peer's expected ActingWeb mini-app type for validation (optional)
    ):
        """Creates a new reciprocal trust relationship locally and by requesting a relationship from a peer actor.

        Args:
            relationship: The trust type/permission level to request (friend, admin, etc.)
            trust_type: Expected peer mini-app type for validation (optional)
        """
        if len(url) == 0:
            return False
        if not secret or len(secret) == 0:
            return False
        res = self.get_peer_info(url)
        if (
            not res
            or res["last_response_code"] < 200
            or res["last_response_code"] >= 300
        ):
            return False
        peer = res["data"]
        if not peer["id"] or not peer["type"] or len(peer["type"]) == 0:
            logger.info(
                "Received invalid peer info when trying to establish trust: " + url
            )
            return False
        if len(trust_type) > 0:
            if trust_type.lower() != peer["type"].lower():
                logger.info("Peer is of the wrong actingweb type: " + peer["type"])
                return False
        if not relationship or len(relationship) == 0:
            relationship = self.config.default_relationship if self.config else ""
        # Create trust, so that peer can do a verify on the relationship (using
        # verification_token) when we request the relationship
        dbtrust = trust.Trust(actor_id=self.id, peerid=peer["id"], config=self.config)
        if not dbtrust.create(
            baseuri=url,
            secret=secret,
            peer_type=peer["type"],
            relationship=relationship,
            approved=True,
            verified=True,  # Requesting actor has verified=True by default per ActingWeb spec
            desc=desc,
            established_via="trust",
        ):
            logger.warning(
                "Trying to establish a new Reciprocal trust when peer relationship already exists ("
                + peer["id"]
                + ")"
            )
            return False
        # Since we are initiating the relationship, we implicitly approve it
        # It is not verified until the peer has verified us
        new_trust = dbtrust.get()
        params = {
            "baseuri": (self.config.root if self.config else "") + (self.id or ""),
            "id": self.id,
            "type": self.config.aw_type if self.config else "",
            "secret": secret,
            "desc": desc,
            "verify": new_trust["verification_token"] if new_trust else "",
        }
        requrl = url + "/trust/" + relationship
        data = json.dumps(params)
        logger.debug(
            f"Creating reciprocal trust at url({requrl}) for peer {params.get('id', 'unknown')}"
        )
        try:
            response = requests.post(
                url=requrl,
                data=data,
                timeout=(5, 10),
                headers={
                    "Content-Type": "application/json",
                },
            )
            self.last_response_code = response.status_code
            self.last_response_message = (
                response.content.decode("utf-8", "ignore")
                if isinstance(response.content, bytes)
                else str(response.content)
            )
        except Exception:  # folds DbError: peer HTTP only
            logger.debug("Not able to create trust with peer, deleting my trust.")
            dbtrust.delete()
            return False
        if self.last_response_code == 201 or self.last_response_code == 202:
            # Reload the trust to check if approval was done
            mod_trust = trust.Trust(
                actor_id=self.id, peerid=peer["id"], config=self.config
            )
            mod_trust_data = mod_trust.get()
            if not mod_trust_data or len(mod_trust_data) == 0:
                logger.error(
                    "Couldn't find trust relationship after peer POST and verification"
                )
                return False
            if self.last_response_code == 201:
                # Already approved by peer (probably auto-approved)
                # Do it direct on the trust (and not self.modifyTrustAndNotify) to avoid a callback
                # to the peer
                mod_trust.modify(peer_approved=True)
            return mod_trust.get()
        else:
            logger.debug("Not able to create trust with peer, deleting my trust.")
            dbtrust.delete()
            return False

    async def create_reciprocal_trust_async(
        self,
        url,
        secret=None,
        desc="",
        relationship="",
        trust_type="",
    ):
        """Async version of create_reciprocal_trust - prevents blocking on peer HTTP calls.

        Creates a new reciprocal trust relationship locally and by requesting a relationship from a peer actor.
        """
        if len(url) == 0:
            return False
        if not secret or len(secret) == 0:
            return False

        # Get peer info async
        res = await self.get_peer_info_async(url)
        if (
            not res
            or res["last_response_code"] < 200
            or res["last_response_code"] >= 300
        ):
            return False
        peer = res["data"]
        if not peer.get("id") or not peer.get("type") or len(peer["type"]) == 0:
            logger.info(
                "Received invalid peer info when trying to establish trust: " + url
            )
            return False
        if len(trust_type) > 0:
            if trust_type.lower() != peer["type"].lower():
                logger.info("Peer is of the wrong actingweb type: " + peer["type"])
                return False
        if not relationship or len(relationship) == 0:
            relationship = self.config.default_relationship if self.config else ""

        # Create trust locally (synchronous DB operation)
        dbtrust = trust.Trust(actor_id=self.id, peerid=peer["id"], config=self.config)
        if not dbtrust.create(
            baseuri=url,
            secret=secret,
            peer_type=peer["type"],
            relationship=relationship,
            approved=True,
            verified=True,
            desc=desc,
            established_via="trust",
        ):
            logger.warning(
                f"Trying to establish a new Reciprocal trust when peer relationship already exists ({peer['id']})"
            )
            return False

        # Request relationship from peer async
        new_trust = dbtrust.get()
        params = {
            "baseuri": (self.config.root if self.config else "") + (self.id or ""),
            "id": self.id,
            "type": self.config.aw_type if self.config else "",
            "secret": secret,
            "desc": desc,
            "verify": new_trust["verification_token"] if new_trust else "",
        }

        import httpx

        requrl = url + "/trust/" + relationship
        data = json.dumps(params)
        # The body carries the new trust secret and verification token.
        logger.info(
            f"Requesting trust relationship async from peer at ({requrl}) with "
            f"data({summarize_payload(params, encoded_len=len(data))})"
        )
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    requrl,
                    content=data,
                    headers={"Content-Type": "application/json"},
                )
                self.last_response_code = response.status_code
                self.last_response_message = (
                    response.content.decode("utf-8", "ignore")
                    if isinstance(response.content, bytes)
                    else str(response.content)
                )
        except httpx.TimeoutException:
            logger.debug("Timeout creating trust with peer async, deleting my trust.")
            dbtrust.delete()
            return False
        except httpx.RequestError as e:
            logger.debug(
                f"Not able to create trust with peer async: {e}, deleting my trust."
            )
            dbtrust.delete()
            return False

        if self.last_response_code == 201 or self.last_response_code == 202:
            # Reload trust to check if approval was done
            mod_trust = trust.Trust(
                actor_id=self.id, peerid=peer["id"], config=self.config
            )
            mod_trust_data = mod_trust.get()
            if not mod_trust_data or len(mod_trust_data) == 0:
                logger.error(
                    "Couldn't find trust relationship after peer POST and verification"
                )
                return False
            if self.last_response_code == 201:
                # Already approved by peer (probably auto-approved)
                mod_trust.modify(peer_approved=True)
            return mod_trust.get()
        else:
            logger.debug("Not able to create trust with peer async, deleting my trust.")
            dbtrust.delete()
            return False

    def create_verified_trust(
        self,
        baseuri="",
        peerid=None,
        approved=False,
        secret=None,
        verification_token=None,
        trust_type=None,  # peer's ActingWeb mini-app type (e.g., "urn:actingweb:example.com:banking")
        peer_approved=None,
        relationship=None,  # trust type/permission level (e.g., "friend", "admin", "partner")
        desc="",
    ):
        """Creates a new trust when requested and call backs to initiating actor to verify relationship.

        Args:
            trust_type: The peer's ActingWeb mini-application type URI
            relationship: The trust type/permission level (friend, admin, etc.)
        """
        if not peerid or len(baseuri) == 0 or not relationship:
            return False
        requrl = baseuri + "/trust/" + relationship + "/" + self.id
        if not secret or len(secret) == 0:
            logger.debug(
                "No secret received from requesting peer("
                + peerid
                + ") at url ("
                + requrl
                + "). Verification is not possible."
            )
            verified = False
        else:
            headers = {
                "Authorization": "Bearer " + secret,
            }
            logger.debug(
                f"Verifying trust at requesting peer({peerid}) at url ({requrl})"
            )
            try:
                response = requests.get(url=requrl, headers=headers, timeout=(5, 10))
                self.last_response_code = response.status_code
                self.last_response_message = (
                    response.content.decode("utf-8", "ignore")
                    if isinstance(response.content, bytes)
                    else str(response.content)
                )
                try:
                    content_str = (
                        response.content.decode("utf-8", "ignore")
                        if isinstance(response.content, bytes)
                        else str(response.content)
                    )
                    data = json.loads(content_str)
                    logger.debug(
                        f"Verifying trust response: verified={data.get('verified', False)}, "
                        f"approved={data.get('approved', False)}, peer_approved={data.get('peer_approved', False)}"
                    )
                    if secret_digest_equals(
                        data.get("verification_token"), verification_token
                    ):
                        verified = True
                    else:
                        verified = False
                except ValueError:
                    logger.debug(
                        "No json body in response when verifying trust at url("
                        + requrl
                        + ")"
                    )
                    verified = False
            except Exception:  # folds DbError: peer HTTP only
                logger.debug("No response when verifying trust at url" + requrl + ")")
                verified = False
        new_trust = trust.Trust(actor_id=self.id, peerid=peerid, config=self.config)
        if not new_trust.create(
            baseuri=baseuri,
            secret=secret or "",
            peer_type=trust_type or "",
            approved=approved,
            peer_approved=peer_approved if peer_approved is not None else False,
            relationship=relationship,
            verified=verified,
            desc=desc,
            established_via="trust",
        ):
            return False
        else:
            return new_trust.get()

    def delete_reciprocal_trust(
        self, peerid=None, delete_peer=False, notify_peers=True
    ):
        """Deletes a trust relationship and requests deletion of peer's relationship as well.

        ``notify_peers=False`` skips the remote DELETE (``delete_peer`` is then
        ignored) and runs only the local cleanup.
        """
        failed_once = False  # For multiple relationships, this will be True if at least one deletion at peer failed
        success_once = False  # True if at least one relationship was deleted at peer
        if not peerid:
            rels = self.get_trust_relationships()
        else:
            rels = self.get_trust_relationships(peerid=peerid)
        for rel in rels:
            # For OAuth2-established trusts, there is no remote actor endpoint to call.
            # Skip remote deletion and delete locally only.
            is_oauth2_trust = (
                (rel.get("established_via") == "oauth2")
                or (rel.get("established_via") == "oauth2_client")
                or (rel.get("type") == "oauth2")
                or (rel.get("type") == "oauth2_client")
                or (str(rel.get("peerid", "")).startswith("oauth2:"))
                or (str(rel.get("peerid", "")).startswith("oauth2_client:"))
            )
            # Additional safety check: prevent self-deletion if baseuri points to this actor
            is_self_deletion = (
                rel.get("baseuri", "").endswith(f"/{self.id}")
                or rel.get("baseuri", "") == f"{self.config.root}{self.id}"
                if self.config
                else False
            )

            if not notify_peers:
                pass
            elif delete_peer and not is_oauth2_trust and not is_self_deletion:
                url = rel["baseuri"] + "/trust/" + rel["relationship"] + "/" + self.id
                headers = {}
                if rel["secret"]:
                    headers = {
                        "Authorization": "Bearer " + rel["secret"],
                    }
                logger.info(f"Deleting reciprocal relationship at {url}")
                try:
                    response = requests.delete(
                        url=url, headers=headers, timeout=(5, 10)
                    )
                except Exception:  # folds DbError: peer HTTP only
                    logger.debug(
                        "Failed to delete reciprocal relationship at url(" + url + ")"
                    )
                    failed_once = True
                    continue
                if (
                    response.status_code < 200 or response.status_code > 299
                ) and response.status_code != 404:
                    logger.debug(
                        "Failed to delete reciprocal relationship at url(" + url + ")"
                    )
                    failed_once = True
                    continue
                else:
                    success_once = True
            elif delete_peer and (is_oauth2_trust or is_self_deletion):
                # Treat as successful remote delete for OAuth2 trusts and self-deletions
                reason = (
                    "OAuth2-established trust"
                    if is_oauth2_trust
                    else "self-deletion detected"
                )
                logger.debug(
                    f"Skipping remote delete for {reason}; deleting locally only"
                )
                success_once = True
            if not self.subs_list:
                # strict=False: a fault leaves this peer's subscriptions as
                # orphans rather than failing the trust deletion.
                self.subs_list = subscription.Subscriptions(
                    actor_id=self.id, config=self.config
                ).fetch(strict=False)
            # Delete this peer's subscriptions
            if self.subs_list:
                for sub in self.subs_list:
                    if sub["peerid"] == rel["peerid"]:
                        logger.debug(
                            "Deleting subscription("
                            + sub["subscriptionid"]
                            + ") as part of trust deletion."
                        )
                        sub_obj = self.get_subscription_obj(
                            peerid=sub["peerid"],
                            subid=sub["subscriptionid"],
                            callback=sub["callback"],
                        )
                        if sub_obj:
                            sub_obj.delete()
            # Delete associated trust permissions before deleting the trust
            try:
                from .trust_permissions import TrustPermissionStore

                if self.config is not None and self.id is not None:
                    permission_store = TrustPermissionStore(self.config)
                    permission_store.delete_permissions(self.id, rel["peerid"])
            except DbError:
                raise
            except Exception as e:
                logger.warning(
                    f"Failed to delete trust permissions for {rel['peerid']}: {e}"
                )

            # Clean up remote peer data (RemotePeerStore)
            # No config check needed - delete_all() is a no-op if no data exists
            try:
                from .interface.actor_interface import ActorInterface
                from .remote_storage import RemotePeerStore

                actor_interface = ActorInterface(self)
                store = RemotePeerStore(
                    actor_interface,
                    rel["peerid"],
                    validate_peer_id=False,
                )
                store.delete_all()
                logger.info(f"Cleaned up RemotePeerStore for peer {rel['peerid']}")
            except ImportError:
                pass  # RemotePeerStore not available
            except DbError:
                raise
            except Exception as e:
                logger.warning(
                    f"Failed to cleanup RemotePeerStore for {rel['peerid']}: {e}"
                )

            # Clean up callback processor state
            # No config check needed - clear operation is a no-op if no state exists
            try:
                from .callback_processor import CallbackProcessor

                processor = CallbackProcessor(self)  # type: ignore[arg-type]
                processor.clear_all_state_for_peer(rel["peerid"])
                logger.info(
                    f"Cleaned up CallbackProcessor state for peer {rel['peerid']}"
                )
            except ImportError:
                pass  # CallbackProcessor not available
            except DbError:
                raise
            except Exception as e:
                logger.warning(
                    f"Failed to cleanup callback state for {rel['peerid']}: {e}"
                )

            # Clean up cached peer profile
            # No config check needed - delete is a no-op if no profile exists
            if self.config is not None and self.id is not None:
                try:
                    from .peer_profile import get_peer_profile_store

                    profile_store = get_peer_profile_store(self.config)
                    profile_store.delete_profile(self.id, rel["peerid"])
                    logger.info(f"Cleaned up peer profile for peer {rel['peerid']}")
                except ImportError:
                    pass  # Peer profile system not available
                except DbError:
                    raise
                except Exception as e:
                    logger.warning(
                        f"Failed to cleanup peer profile for {rel['peerid']}: {e}"
                    )

            # Clean up cached peer capabilities (methods/actions)
            # No config check needed - delete is a no-op if nothing cached
            if self.config is not None and self.id is not None:
                try:
                    from .peer_capabilities import get_cached_capabilities_store

                    capabilities_store = get_cached_capabilities_store(self.config)
                    capabilities_store.delete_capabilities(self.id, rel["peerid"])
                    logger.info(
                        f"Cleaned up peer capabilities for peer {rel['peerid']}"
                    )
                except ImportError:
                    pass  # Peer capabilities system not available
                except DbError:
                    raise
                except Exception as e:
                    logger.warning(
                        f"Failed to cleanup peer capabilities for {rel['peerid']}: {e}"
                    )

            # Clean up cached peer permissions
            # No config check needed - delete is a no-op if nothing cached
            if self.config is not None and self.id is not None:
                try:
                    from .peer_permissions import get_peer_permission_store

                    peer_permissions_store = get_peer_permission_store(self.config)
                    peer_permissions_store.delete_permissions(self.id, rel["peerid"])
                    logger.info(
                        f"Cleaned up peer permissions cache for peer {rel['peerid']}"
                    )
                except ImportError:
                    pass  # Peer permissions caching not available
                except DbError:
                    raise
                except Exception as e:
                    logger.warning(
                        f"Failed to cleanup peer permissions cache for {rel['peerid']}: {e}"
                    )

            # Finally, delete the trust record itself
            dbtrust = trust.Trust(
                actor_id=self.id, peerid=rel["peerid"], config=self.config
            )
            dbtrust.delete()
        if notify_peers and delete_peer and (not success_once or failed_once):
            return False
        return True

    def purge_relationships(self, notify_peers: bool = False) -> dict[str, Any]:
        """Remove every trust, subscription and peer-trustee row of this actor.

        Used when a sign-in proves the address over an actor nobody vouched
        for, so a relationship made while the actor was unvouched cannot
        outlive the adoption. All side-stores are cleaned (permissions,
        remote-peer data, callback state, subscriptions with diffs). With
        ``notify_peers=False`` (the default) no request leaves the process:
        the peer URLs were chosen by whoever created the relationship.

        ``Trusts.delete()`` reports success whatever the backend did, so the
        lists are re-read afterwards and ``confirmed`` says whether they (the
        peer-trustee rows too) are empty. The reads are strict: PostgreSQL
        answers a caught fault with an empty list, which must not pass for
        "nothing left", so a fault
        before the wipe removes nothing and a fault after it leaves
        ``confirmed`` False. Trust secrets are never included in the returned
        summary.
        """
        from actingweb.db import (
            get_peer_trustee_list,
            get_subscription_list,
            get_trust_list,
        )

        unconfirmed: dict[str, Any] = {
            "trusts": [],
            "subscription_peers": [],
            "confirmed": False,
        }
        config = self.config
        if not config:
            return unconfirmed
        try:
            # Read the subscriptions first: removing a trust also removes
            # that peer's subscriptions, which would empty the summary.
            sub_rows = (
                get_subscription_list(config).fetch(actor_id=self.id, strict=True) or []
            )
            relationships = (
                get_trust_list(config).fetch(actor_id=self.id, strict=True) or []
            )
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Purge of actor {self.id}: could not read its lists: {e}")
            return unconfirmed
        removed_trusts, subscription_peers = relationship_summary(
            relationships, sub_rows
        )
        subs = subscription.Subscriptions(actor_id=self.id, config=self.config)
        trusts = trust.Trusts(actor_id=self.id, config=self.config)
        for rel in relationships:
            if isinstance(rel, dict) and rel.get("peerid"):
                self.delete_reciprocal_trust(
                    peerid=rel["peerid"],
                    delete_peer=False,
                    notify_peers=notify_peers,
                )
        trusts.delete()

        subs.delete()

        self.delete_peer_trustee(shorttype="*", notify_peers=notify_peers)
        # delete_peer_trustee("*") visits only the types in config.actors; a
        # row for a type dropped since (or never listed) stays. Remove the
        # rest locally.
        peer_list = get_peer_trustee_list(config)
        try:
            if peer_list.fetch(actor_id=self.id, strict=True):
                peer_list.delete()
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Purge of actor {self.id}: peer trustees not removed: {e}")

        try:
            trusts_left = get_trust_list(config).fetch(actor_id=self.id, strict=True)
            subs_left = get_subscription_list(config).fetch(
                actor_id=self.id, strict=True
            )
            peers_left = get_peer_trustee_list(config).fetch(
                actor_id=self.id, strict=True
            )
            confirmed = not trusts_left and not subs_left and not peers_left
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Purge of actor {self.id}: could not re-read its lists: {e}")
            confirmed = False
        return {
            "trusts": removed_trusts,
            "subscription_peers": subscription_peers,
            "confirmed": confirmed,
        }

    def create_subscription(
        self,
        peerid=None,
        target=None,
        subtarget=None,
        resource=None,
        granularity=None,
        subid=None,
        callback=False,
    ):
        new_sub = subscription.Subscription(
            actor_id=self.id,
            peerid=peerid,
            subid=subid,
            callback=callback,
            config=self.config,
        )
        new_sub.create(
            target=target,
            subtarget=subtarget,
            resource=resource,
            granularity=granularity,
        )
        # Invalidate the cached subscription list so register_diffs() on this
        # instance sees the new subscription. Previously each caller had to
        # remember this (only handlers/subscription.py did), so subscriptions
        # created through the interface layer silently received no diffs for
        # the rest of the instance's lifetime — unbounded where an Actor is
        # cached across requests. NOTE: this only refreshes *this* instance;
        # another process, or a cross-request cached Actor elsewhere, still
        # holds its own list. See thoughts/todo/subs-list-cache-asymmetry.md.
        self.subs_list = None
        return new_sub.get()

    def create_remote_subscription(
        self, peerid=None, target=None, subtarget=None, resource=None, granularity=None
    ):
        """Creates a new subscription at peerid."""
        if not peerid or not target:
            return False
        relationships = self.get_trust_relationships(peerid=peerid)
        if not relationships:
            return False
        peer = relationships[0]
        params = {
            "id": self.id,
            "target": target,
        }
        if subtarget:
            params["subtarget"] = subtarget
        if resource:
            params["resource"] = resource
        if granularity and len(granularity) > 0:
            params["granularity"] = granularity
        requrl = peer["baseuri"] + "/subscriptions/" + self.id
        data = json.dumps(params)
        headers = {
            "Authorization": "Bearer " + peer["secret"],
            "Content-Type": "application/json",
        }
        try:
            logger.debug(
                "Creating remote subscription at url("
                + requrl
                + ") with body ("
                + summarize_payload(params, encoded_len=len(data))
                + ")"
            )
            response = requests.post(
                url=requrl, data=data, headers=headers, timeout=(5, 10)
            )
            self.last_response_code = response.status_code
            self.last_response_message = (
                response.content.decode("utf-8", "ignore")
                if isinstance(response.content, bytes)
                else str(response.content)
            )
        except Exception:  # folds DbError: peer HTTP only
            return None
        try:
            logger.debug(
                "Created remote subscription at url("
                + requrl
                + ") and got JSON response ("
                + summarize_payload(response.content)
                + ")"
            )
            content_str = (
                response.content.decode("utf-8", "ignore")
                if isinstance(response.content, bytes)
                else str(response.content)
            )
            data = json.loads(content_str)
        except ValueError:
            return None
        if "subscriptionid" in data:
            subid = data["subscriptionid"]
        else:
            return None
        if self.last_response_code == 201:
            self.create_subscription(
                peerid=peerid,
                target=target,
                subtarget=subtarget,
                resource=resource,
                granularity=granularity,
                subid=subid,
                callback=True,
            )
            if "Location" in response.headers:
                return response.headers["Location"]
            elif "location" in response.headers:
                return response.headers["location"]
        else:
            return None

    def get_subscriptions(
        self,
        peerid: str | None = None,
        target: str | None = None,
        subtarget: str | None = None,
        resource: str | None = None,
        callback: bool | None = None,
        *,
        strict: bool = True,
    ) -> list[dict[str, Any]] | None:
        """Retrieves subscriptions from db.

        Args:
            peerid: Filter by peer ID (None = all peers)
            target: Filter by target (None = all targets)
            subtarget: Filter by subtarget (None = all subtargets)
            resource: Filter by resource (None = all resources)
            callback: Filter by callback flag (None = all, False = inbound, True = outbound)
            strict: When False, a read fault answers ``[]`` instead of raising

        Returns:
            List of subscription dictionaries, or None if actor has no ID

        Raises:
            DbError: on a read fault (unless ``strict=False``)
        """
        if not self.id:
            return None
        if not self.subs_list:
            self.subs_list = subscription.Subscriptions(
                actor_id=self.id, config=self.config
            ).fetch(strict=strict)
        ret = []
        if self.subs_list:
            for sub in self.subs_list:
                if not peerid or (peerid and sub["peerid"] == peerid):
                    if not target or (target and sub["target"] == target):
                        if not subtarget or (
                            subtarget and sub["subtarget"] == subtarget
                        ):
                            if not resource or (
                                resource and sub["resource"] == resource
                            ):
                                if callback is None or sub["callback"] == callback:
                                    ret.append(sub)
        return ret

    def get_subscription(self, peerid=None, subid=None, callback=False):
        """Retrieves a single subscription identified by peerid and subid."""
        if not subid:
            return False
        return subscription.Subscription(
            actor_id=self.id,
            peerid=peerid,
            subid=subid,
            callback=callback,
            config=self.config,
        ).get()

    def get_subscription_obj(self, peerid=None, subid=None, callback=False):
        """Retrieves a single subscription identified by peerid and subid."""
        if not subid:
            return False
        return subscription.Subscription(
            actor_id=self.id,
            peerid=peerid,
            subid=subid,
            callback=callback,
            config=self.config,
        )

    def delete_remote_subscription(self, peerid=None, subid=None):
        if not subid or not peerid:
            return False
        trust_rel = self.get_trust_relationship(peerid=peerid)
        if not trust_rel:
            return False
        sub = self.get_subscription(peerid=peerid, subid=subid)
        if not sub:
            sub = self.get_subscription(peerid=peerid, subid=subid, callback=True)
        if not sub or "callback" not in sub or not sub["callback"]:
            url = trust_rel["baseuri"] + "/subscriptions/" + self.id + "/" + subid
        else:
            url = (
                trust_rel["baseuri"]
                + "/callbacks/subscriptions/"
                + self.id
                + "/"
                + subid
            )
        headers = {
            "Authorization": "Bearer " + trust_rel["secret"],
        }
        try:
            logger.info(f"Deleting remote subscription at {url}")
            response = requests.delete(url=url, headers=headers, timeout=(5, 10))
            self.last_response_code = response.status_code
            self.last_response_message = (
                response.content.decode("utf-8", "ignore")
                if isinstance(response.content, bytes)
                else str(response.content)
            )
            if response.status_code == 204:
                return True
            else:
                logger.debug("Failed to delete remote subscription at url(" + url + ")")
                return False
        except Exception:  # folds DbError: peer HTTP only
            return False

    def delete_subscription(self, peerid=None, subid=None, callback=False):
        """Deletes a specified subscription"""
        if not subid:
            return False

        # For outbound subscriptions (callback=True), check if we need to clean up RemotePeerStore
        # We need to check this BEFORE deletion to know how many subscriptions exist
        should_cleanup_remote_peer_store = False
        if callback and peerid:
            try:
                # CRITICAL: Clear the subscription cache to get fresh data from database
                # Otherwise we might see stale subscriptions or the one we're about to delete
                self.subs_list = None

                # Check if we have any other outbound subscriptions to this peer
                other_subs = self.get_subscriptions(peerid=peerid, callback=True)

                # Filter out the current subscription being deleted
                # IMPORTANT: Field name is "subscriptionid" not "subid"
                remaining_subs = [
                    s for s in (other_subs or []) if s.get("subscriptionid") != subid
                ]

                if remaining_subs:
                    logger.debug(
                        f"Not cleaning up RemotePeerStore for {peerid} - "
                        f"{len(remaining_subs)} other outbound subscription(s) still active"
                    )
                else:
                    # Mark for cleanup after successful deletion
                    should_cleanup_remote_peer_store = True
            except DbError:
                raise
            except Exception as e:
                logger.warning(
                    f"Failed to check RemotePeerStore cleanup for {peerid}: {e}"
                )

        sub = subscription.Subscription(
            actor_id=self.id,
            peerid=peerid,
            subid=subid,
            callback=callback,
            config=self.config,
        )
        result = sub.delete()

        # Clear subscription cache after deletion to ensure fresh data on next access
        self.subs_list = None

        # Clean up RemotePeerStore AFTER successful deletion to avoid data loss
        # Note: should_cleanup_remote_peer_store is only True when peerid is not None
        if result and should_cleanup_remote_peer_store and peerid:
            try:
                from .interface.actor_interface import ActorInterface
                from .remote_storage import RemotePeerStore

                # No other outbound subscriptions to this peer, safe to clean up
                actor_interface = ActorInterface(self)  # type: ignore[arg-type]
                store = RemotePeerStore(
                    actor_interface,
                    peerid,
                    validate_peer_id=False,
                )
                store.delete_all()
                logger.info(f"Cleaned up RemotePeerStore for peer {peerid}")
            except ImportError:
                pass  # RemotePeerStore not available
            except Exception as e:  # folds DbError: best-effort cleanup after the subscription delete committed
                logger.warning(f"Failed to clean up RemotePeerStore for {peerid}: {e}")

        return result

    def callback_subscription(
        self, peerid=None, sub_obj=None, sub=None, diff=None, blob=None
    ):
        if not peerid or not diff or not sub or not blob:
            logger.warning("Missing parameters in callbackSubscription")
            return
        if "granularity" in sub and sub["granularity"] == "none":
            return
        trust_rel = self.get_trust_relationship(peerid)
        if not trust_rel:
            return

        # Filter blob based on peer permissions for property subscriptions
        if sub.get("target") == "properties":
            filtered_blob = self._filter_subscription_data_by_permissions(
                peerid=peerid,
                blob=blob,
                subtarget=sub.get("subtarget"),
            )
            if filtered_blob is None:
                return  # Nothing to send after filtering
            blob = filtered_blob

        params = {
            "id": self.id,
            "subscriptionid": sub["subscriptionid"],
            "target": sub["target"],
            "sequence": diff["sequence"],
            "timestamp": str(diff["timestamp"]),
            "granularity": sub["granularity"],
        }
        if sub["subtarget"]:
            params["subtarget"] = sub["subtarget"]
        if sub["resource"]:
            params["resource"] = sub["resource"]
        if sub["granularity"] == "high":
            try:
                params["data"] = json.loads(blob)
            except (TypeError, ValueError, KeyError):
                params["data"] = blob
        if sub["granularity"] == "low":
            params["url"] = (
                (self.config.root if self.config else "")
                + (self.id or "")
                + "/subscriptions/"
                + trust_rel["peerid"]
                + "/"
                + sub["subscriptionid"]
                + "/"
                + str(diff["sequence"])
            )
        requrl = (
            trust_rel["baseuri"]
            + "/callbacks/subscriptions/"
            + self.id
            + "/"
            + sub["subscriptionid"]
        )
        data = json.dumps(params)
        headers = {
            "Authorization": "Bearer " + trust_rel["secret"],
            "Content-Type": "application/json",
        }

        # Helper function for sync callback
        def _send_callback_sync():
            """Send subscription callback using requests (blocking)."""
            try:
                logger.debug(
                    "Doing sync callback on subscription at url("
                    + requrl
                    + ") with body("
                    + summarize_payload(params, encoded_len=len(data))
                    + ")"
                )
                response = requests.post(
                    url=requrl,
                    data=data.encode("utf-8"),
                    headers=headers,
                    timeout=(5, 10),
                )
                self.last_response_code = response.status_code
                self.last_response_message = (
                    response.content.decode("utf-8", "ignore")
                    if isinstance(response.content, bytes)
                    else str(response.content)
                )
                # Log the response for debugging callback delivery issues
                if response.status_code == 204:
                    logger.info(
                        f"Callback seq={diff.get('sequence')} delivered successfully (204)"
                    )
                else:
                    logger.warning(
                        f"Callback seq={diff.get('sequence')} returned {response.status_code}: "
                        f"{self.last_response_message[:200] if self.last_response_message else 'no message'}"
                    )
                # NOTE: Don't clear diffs immediately after 204 response. The subscriber
                # might have added the callback to a pending queue (due to sequence gaps),
                # and the diff would be lost. Diffs are cleared when the subscriber
                # explicitly confirms processing via PUT /subscriptions/{id} with sequence.
            except (requests.RequestException, requests.Timeout, ConnectionError) as e:
                logger.warning(
                    f"Callback seq={diff.get('sequence')} failed - peer did not respond: {e}"
                )
                self.last_response_code = 0
                self.last_response_message = (
                    "No response from peer for subscription callback"
                )

        # Check if sync callbacks are forced (recommended for Lambda/serverless)
        use_sync = getattr(self.config, "sync_subscription_callbacks", False)
        if use_sync:
            logger.info(
                f"Sync callback seq={diff.get('sequence')} to {sub.get('peerid', 'unknown')}"
            )
            _send_callback_sync()
            return

        # Fire callback asynchronously to avoid blocking the caller
        async def _send_callback_async():
            """Send subscription callback using httpx (non-blocking)."""
            import httpx

            try:
                logger.debug(
                    "Doing async callback on subscription at url("
                    + requrl
                    + ") with body("
                    + summarize_payload(params, encoded_len=len(data))
                    + ")"
                )
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(10.0, connect=5.0)
                ) as client:
                    response = await client.post(
                        requrl, content=data.encode("utf-8"), headers=headers
                    )
                self.last_response_code = response.status_code
                self.last_response_message = (
                    response.content.decode("utf-8", "ignore")
                    if isinstance(response.content, bytes)
                    else str(response.content)
                )
                # NOTE: Don't clear diffs immediately after 204 response. The subscriber
                # might have added the callback to a pending queue (due to sequence gaps),
                # and the diff would be lost. Diffs are cleared when the subscriber
                # explicitly confirms processing via PUT /subscriptions/{id} with sequence.
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                logger.debug(f"Peer did not respond to callback on url({requrl}): {e}")
                self.last_response_code = 0
                self.last_response_message = (
                    "No response from peer for subscription callback"
                )

        # Schedule the async callback without blocking (may be lost on Lambda freeze!)
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            # We're in an async context - create a background task
            loop.create_task(_send_callback_async())
            logger.debug(
                f"Async callback seq={diff.get('sequence')} to {sub.get('peerid', 'unknown')} (fire-and-forget)"
            )
        except RuntimeError:
            # No running event loop - fall back to sync request
            logger.debug("No async loop, falling back to sync callback")
            _send_callback_sync()

    async def create_verified_trust_async(
        self,
        baseuri="",
        peerid=None,
        approved=False,
        secret=None,
        verification_token=None,
        trust_type=None,
        peer_approved=None,
        relationship=None,
        desc="",
    ):
        """Async version - wraps sync method in asyncio.to_thread to prevent blocking."""
        import asyncio

        return await asyncio.to_thread(
            self.create_verified_trust,
            baseuri=baseuri,
            peerid=peerid,
            approved=approved,
            secret=secret,
            verification_token=verification_token,
            trust_type=trust_type,
            peer_approved=peer_approved,
            relationship=relationship,
            desc=desc,
        )

    async def delete_reciprocal_trust_async(self, peerid=None, delete_peer=False):
        """Async version - wraps sync method in asyncio.to_thread to prevent blocking."""
        import asyncio

        return await asyncio.to_thread(
            self.delete_reciprocal_trust, peerid=peerid, delete_peer=delete_peer
        )

    async def create_remote_subscription_async(
        self,
        peerid=None,
        target=None,
        subtarget=None,
        resource=None,
        granularity=None,
    ):
        """Async version - wraps sync method in asyncio.to_thread to prevent blocking."""
        import asyncio

        return await asyncio.to_thread(
            self.create_remote_subscription,
            peerid=peerid,
            target=target,
            subtarget=subtarget,
            resource=resource,
            granularity=granularity,
        )

    async def delete_remote_subscription_async(self, peerid=None, subid=None):
        """Async version - wraps sync method in asyncio.to_thread to prevent blocking."""
        import asyncio

        return await asyncio.to_thread(
            self.delete_remote_subscription, peerid=peerid, subid=subid
        )

    async def callback_subscription_async(
        self, peerid=None, sub_obj=None, sub=None, diff=None, blob=None
    ):
        """Async version - wraps sync method in asyncio.to_thread to prevent blocking."""
        import asyncio

        return await asyncio.to_thread(
            self.callback_subscription,
            peerid=peerid,
            sub_obj=sub_obj,
            sub=sub,
            diff=diff,
            blob=blob,
        )

    def _filter_subscription_data_by_permissions(
        self, peerid: str, blob: str | bytes, subtarget: str | None = None
    ) -> str | None:
        """Filter subscription data based on peer's property permissions.

        Returns filtered blob as JSON string, or None if nothing passes the filter.
        Implements fail-closed: errors result in no data sent.
        """
        try:
            if not self.config or not self.id:
                logger.warning("Missing config or actor ID for subscription filtering")
                return None  # Fail-closed

            evaluator = get_permission_evaluator(self.config)
            if not evaluator:
                logger.warning(
                    f"Permission evaluator not available for subscription filtering to {peerid}"
                )
                return None  # Fail-closed

            # Parse blob with explicit encoding handling for bytes
            if isinstance(blob, bytes):
                data = json.loads(blob.decode("utf-8"))
            elif isinstance(blob, str):
                data = json.loads(blob)
            else:
                data = blob

            if not isinstance(data, dict):
                logger.debug(f"Cannot filter non-dict subscription data: {type(data)}")
                return blob if isinstance(blob, str) else json.dumps(blob)

            filtered_data = {}
            for property_name, value in data.items():
                # Normalize property list keys: strip 'list:' prefix for permission checks
                # Property lists use 'list:name' internally but permissions use 'name'
                normalized_name = (
                    property_name[5:]
                    if property_name.startswith("list:")
                    else property_name
                )

                # Build full property path for permission check
                property_path = (
                    f"{subtarget}/{normalized_name}" if subtarget else normalized_name
                )
                result = evaluator.evaluate_property_access(
                    self.id, peerid, property_path, operation="read"
                )
                if result == PermissionResult.ALLOWED:
                    filtered_data[property_name] = value
                else:
                    logger.debug(
                        f"Filtered property {property_path} from subscription callback to {peerid}"
                    )

            if not filtered_data:
                logger.debug(
                    f"No permitted properties in callback to {peerid}, skipping"
                )
                return None

            return json.dumps(filtered_data)
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Permission filtering failed for subscription callback: {e}")
            return None  # Fail-closed: don't send data on error

    # =========================================================================
    # Subscription Suspension Management
    # =========================================================================

    def is_subscription_suspended(
        self, target: str, subtarget: str | None = None
    ) -> bool:
        """Check if diff registration is suspended for a target/subtarget.

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            True if suspended, False otherwise
        """
        if not self.config or not self.id:
            return False
        try:
            db = get_subscription_suspension(self.config, self.id)
            return db.is_suspended(target, subtarget)
        except Exception as e:  # folds DbError: diff registration after the property write committed; logged as not suspended
            # "Not suspended" and "could not tell" must not look the same:
            # a missing suspensions table (TableDoesNotExist) or a denied
            # read makes every target look un-suspended, so a bulk import's
            # suspend() silently no-ops and per-item callbacks fire anyway.
            # Log loudly — but at most once per window per process:
            # register_diffs() calls this on every property write, so an
            # unconditional ERROR would flood the log at write rate (the same
            # shape as the per-construction DescribeTable this release
            # removed). Failures in between stay at DEBUG.
            global _suspension_check_error_logged_at
            now = time.monotonic()
            if (
                _suspension_check_error_logged_at is None
                or now - _suspension_check_error_logged_at
                >= _SUSPENSION_ERROR_LOG_INTERVAL_SECONDS
            ):
                _suspension_check_error_logged_at = now
                logger.error(
                    "Suspension check FAILED for %s/%s%s — treating as NOT "
                    "suspended, so subscription diffs and callbacks will fire "
                    "during any suspended window. Verify the subscription "
                    "suspensions table exists and is readable "
                    "(python -m actingweb.db.verify_tables). Repeats at most "
                    "every %.0fs per process; failures in between are logged "
                    "at DEBUG: %s",
                    self.id,
                    target,
                    f"/{subtarget}" if subtarget else "",
                    _SUSPENSION_ERROR_LOG_INTERVAL_SECONDS,
                    e,
                )
            else:
                logger.debug(
                    "Suspension check failed for %s/%s%s: %s",
                    self.id,
                    target,
                    f"/{subtarget}" if subtarget else "",
                    e,
                )
            return False

    def suspend_subscriptions(self, target: str, subtarget: str | None = None) -> bool:
        """Suspend diff registration for a target/subtarget.

        While suspended, property changes will NOT register diffs or trigger callbacks.
        Call resume_subscriptions() to lift suspension and send resync callbacks.

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            True if newly suspended, False if already suspended
        """
        if not self.config or not self.id:
            return False
        try:
            db = get_subscription_suspension(self.config, self.id)
            return db.suspend(target, subtarget)
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error suspending subscriptions: {e}")
            return False

    def resume_subscriptions(self, target: str, subtarget: str | None = None) -> int:
        """Resume diff registration and send resync callbacks.

        Sends a resync callback to ALL subscriptions on this target/subtarget,
        telling them to do a full GET to re-sync their state.

        Args:
            target: Target resource (e.g., "properties")
            subtarget: Optional subtarget (e.g., property name)

        Returns:
            The number of resync callbacks sent
        """
        if not self.config or not self.id:
            return 0
        try:
            db = get_subscription_suspension(self.config, self.id)
            # The resync is the only recovery for the changes made while
            # suspended (they stored no diff and moved no sequence), so read
            # the subscribers strictly before the marker goes: a fault then
            # answers 503 with the suspension still in place.
            subs = self.get_subscriptions(
                target=target, subtarget=None, callback=False, strict=True
            )
            try:
                resumed = db.resume(target, subtarget)
            except DbError:
                # The delete may have landed with its answer lost; put the
                # marker back so the retry finds something to resume.
                self._restore_suspension(db, target, subtarget)
                raise
            if not resumed:
                return 0  # Wasn't suspended

            # Find all affected subscriptions and send resync callbacks
            return self._send_resync_callbacks(target, subtarget, subs, db)
        except DbError:
            raise
        except Exception as e:
            logger.error(f"Error resuming subscriptions: {e}")
            return 0

    def _send_resync_callbacks(
        self,
        target: str,
        subtarget: str | None,
        subs: list[dict[str, Any]] | None = None,
        suspension: Any = None,
    ) -> int:
        """Send resync callbacks to all subscriptions on target/subtarget.

        Every subscriber gets its attempt. If any hit a transient fault, the
        suspension is put back (when ``suspension`` is given) and the first
        such fault raised, so the caller's retry resends to all of them. A
        permanent fault (one a retry cannot fix, such as an item over the
        backend's size limit) is logged as that subscriber's failure: putting
        the suspension back for it would keep the target suspended for good.
        A resync that fails over HTTP is not counted either; a return value
        below the number of subscribers means some missed the resync.

        Args:
            target: Target resource
            subtarget: Optional subtarget
            subs: The subscriptions, read strictly by the caller
            suspension: The suspension store to restore on a fault

        Returns:
            Number of callbacks sent successfully
        """
        if subs is None:
            subs = self.get_subscriptions(
                target=target, subtarget=None, callback=False, strict=True
            )
        if not subs:
            return 0

        count = 0
        fault: DbError | None = None
        for sub in subs:
            sub_target = sub.get("target", "")
            sub_subtarget = sub.get("subtarget")

            # Match target
            if sub_target != target:
                continue

            # Match subtarget if specified
            # Empty subtarget in subscription means "all subtargets", so it matches any filter
            if subtarget is not None and sub_subtarget and sub_subtarget != subtarget:
                continue

            # Send resync callback
            # If we resumed a specific subtarget, use that for the resync
            # (even if the subscription itself has no subtarget or a different one)
            resync_subtarget = subtarget if subtarget else sub_subtarget
            try:
                if self._callback_subscription_resync(sub, resync_subtarget):
                    count += 1
            except DbError as e:  # folds DbError: transient ones raised after the loop
                from .interface.integrations._errors import is_permanent

                if is_permanent(e):
                    logger.error(
                        f"Resync of subscription {sub.get('subscriptionid')} hit a "
                        f"permanent store error; that subscriber missed it: {e}"
                    )
                    continue
                logger.error(
                    f"Resync of subscription {sub.get('subscriptionid')} faulted: {e}"
                )
                fault = fault or e

        logger.info(f"Sent {count} resync callbacks for {target}/{subtarget}")
        if fault is not None:
            if suspension is not None:
                self._restore_suspension(suspension, target, subtarget)
            raise fault
        return count

    def _restore_suspension(
        self, suspension: Any, target: str, subtarget: str | None
    ) -> None:
        """Put a suspension back after a resume faulted, best effort."""
        try:
            suspension.suspend(target, subtarget)
        except DbError as e:  # folds DbError: the caller raises the original fault
            logger.error(
                f"Could not confirm the suspension of {target}/{subtarget} is "
                f"back after a resume fault; a retry may find nothing to "
                f"resume: {e}"
            )

    def _send_resync_callback_sync(
        self, callback_url: str, payload: dict, secret: str, peer_id: str
    ) -> bool:
        """Send resync callback synchronously (blocking).

        Args:
            callback_url: URL to send the callback to
            payload: Callback payload
            secret: Trust secret for authentication
            peer_id: Peer ID (for logging)

        Returns:
            True if callback was sent successfully
        """
        import httpx

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    callback_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {secret}",
                    },
                )

            if response.status_code in (200, 204):
                logger.info(
                    f"Sent resync callback to {peer_id} for subscription "
                    f"{payload.get('subscriptionid')}"
                )
                return True
            else:
                logger.warning(
                    f"Resync callback to {peer_id} failed: {response.status_code}"
                )
                return False

        except Exception as e:  # folds DbError: peer HTTP only
            logger.error(f"Error sending resync callback to {peer_id}: {e}")
            return False

    def _send_resync_callback_async(
        self, callback_url: str, payload: dict, secret: str, peer_id: str
    ) -> None:
        """Send resync callback asynchronously (fire-and-forget).

        Args:
            callback_url: URL to send the callback to
            payload: Callback payload
            secret: Trust secret for authentication
            peer_id: Peer ID (for logging)
        """

        async def _send():
            import httpx

            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        callback_url,
                        json=payload,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {secret}",
                        },
                    )

                if response.status_code in (200, 204):
                    logger.info(
                        f"Sent resync callback to {peer_id} for subscription "
                        f"{payload.get('subscriptionid')}"
                    )
                else:
                    logger.warning(
                        f"Resync callback to {peer_id} failed: {response.status_code}"
                    )

            except Exception as e:  # folds DbError: peer HTTP only
                logger.error(f"Error sending resync callback to {peer_id}: {e}")

        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.create_task(_send())
            logger.debug(
                f"Async resync callback to {peer_id} for subscription "
                f"{payload.get('subscriptionid')} (fire-and-forget)"
            )
        except RuntimeError:
            # No event loop - fallback to sync
            logger.debug("No async loop, falling back to sync resync callback")
            self._send_resync_callback_sync(callback_url, payload, secret, peer_id)

    def _callback_subscription_resync(
        self, subscription: dict, override_subtarget: str | None = None
    ) -> bool:
        """Send a resync callback to a single subscription.

        Checks peer capability before sending resync. If peer doesn't support
        the subscriptionresync option, falls back to low-granularity callback.

        Respects the sync_subscription_callbacks configuration to determine
        whether to send callbacks synchronously (blocking) or asynchronously
        (fire-and-forget).

        Args:
            subscription: Subscription dict with peerid, subscriptionid, callback, etc.
            override_subtarget: Optional subtarget to use instead of subscription's subtarget
                              (used when resuming a specific subtarget on a broader subscription)

        Returns:
            True if callback was sent/scheduled successfully
        """
        from datetime import UTC, datetime

        peer_id = subscription.get("peerid", "")
        sub_id = subscription.get("subscriptionid", "")
        target = subscription.get("target", "")
        # Use override_subtarget if provided, otherwise use subscription's subtarget
        sub_subtarget = (
            override_subtarget
            if override_subtarget is not None
            else subscription.get("subtarget")
        )

        # Get trust relationship to construct callback URL
        from .trust import Trust

        trust = Trust(actor_id=self.id, peerid=peer_id, config=self.config)
        trust_data = trust.get()

        if not trust_data:
            logger.warning(f"No trust found for peer {peer_id}")
            return False

        # Construct callback URL from trust relationship (same as callback_subscription)
        callback_url = (
            trust_data.get("baseuri", "")
            + "/callbacks/subscriptions/"
            + (self.id or "")
            + "/"
            + sub_id
        )

        if not callback_url or not trust_data.get("baseuri"):
            logger.warning(
                f"No callback URL for subscription {sub_id} - missing baseuri in trust"
            )
            return False

        # Check if peer supports resync callbacks (use cached data only)
        from .interface.actor_interface import ActorInterface
        from .peer_capabilities import PeerCapabilities

        actor_interface = ActorInterface(self)
        caps = PeerCapabilities(actor_interface, peer_id)

        # Use cached capabilities without blocking on network fetch
        # If cache is expired or not available, assume support (optimistic)
        supports_resync_cached = caps.supports_resync_callbacks_cached()
        if supports_resync_cached is None:
            # Cache expired or not available - assume support to avoid blocking
            # This is optimistic but safe: if peer doesn't support resync,
            # the receiver will process it as a regular low-granularity callback
            supports_resync = True
            logger.debug(
                f"Capabilities not cached for peer {peer_id}, "
                f"assuming resync support (optimistic)"
            )

            # Schedule background refresh to update cache for next time
            # This doesn't block the current operation
            try:
                import asyncio

                async def _refresh_capabilities():
                    try:
                        await caps.refresh_async()
                        logger.debug(
                            f"Background refresh of capabilities for {peer_id}"
                        )
                    except Exception as e:  # folds DbError: background capability-cache refresh, best-effort
                        logger.debug(
                            f"Background capability refresh failed for {peer_id}: {e}"
                        )

                loop = asyncio.get_running_loop()
                loop.create_task(_refresh_capabilities())
            except RuntimeError:
                # No event loop - skip background refresh
                # Next operation will still use optimistic approach
                pass
        else:
            supports_resync = supports_resync_cached
            logger.debug(
                f"Using cached capability for peer {peer_id}: "
                f"resync_supported={supports_resync}"
            )

        # Increment sequence number
        new_seq = self._increment_subscription_sequence(peer_id, sub_id)
        if not new_seq:
            logger.warning(
                f"Subscription {sub_id} for {peer_id} is gone; no resync sent"
            )
            return False

        # Build resource URL for resync
        if not self.config:
            logger.warning("No config available for building resource URL")
            return False
        resource_url = f"{self.config.proto}{self.config.fqdn}/{self.id}/{target}"
        if sub_subtarget:
            resource_url += f"/{sub_subtarget}"

        # Build callback payload - use resync type only if peer supports it
        if supports_resync:
            # Resync callback per protocol spec v1.4
            payload = {
                "id": self.id,
                "subscriptionid": sub_id,
                "target": target,
                "subtarget": sub_subtarget,
                "sequence": new_seq,
                "timestamp": datetime.now(UTC).isoformat(),
                "granularity": subscription.get("granularity", "high"),
                "type": "resync",
                "url": resource_url,
            }
            logger.debug(f"Sending resync callback to peer {peer_id} (supports resync)")
        else:
            # Fallback: create a full-state diff and send low-granularity callback
            # Get the full current state
            list_keys: set[str] = set()
            full_state = self._get_full_state_for_subscription(
                target, sub_subtarget, list_keys
            )
            # A list's full state is an "extend" diff nested under the list
            # name. Over the span threshold, list diffs become references
            # (the subscriber re-reads), per list and then largest first
            # until the whole blob fits the diff row, so the store does not
            # fail on the row cap.
            from .property_list import fit_full_state

            full_state = fit_full_state(full_state, self.config, list_keys=list_keys)

            # Store as a subscription diff
            diff_url = self._store_subscription_diff(
                peer_id, sub_id, new_seq, full_state
            )
            if not diff_url:
                return False

            # Send low-granularity callback with URL to subscription diff
            payload = {
                "id": self.id,
                "subscriptionid": sub_id,
                "target": target,
                "subtarget": sub_subtarget,
                "sequence": new_seq,
                "timestamp": datetime.now(UTC).isoformat(),
                "granularity": "low",
                "url": diff_url,
            }
            logger.info(
                f"Peer {peer_id} does not support resync callbacks, "
                f"creating full-state diff for low-granularity callback"
            )

        # Get trust secret for authentication (already fetched above)
        secret = trust_data.get("secret", "")

        # Check sync configuration (like diff callbacks do)
        use_sync = getattr(self.config, "sync_subscription_callbacks", False)

        if use_sync:
            # Lambda mode: blocking call
            logger.info(f"Sync resync callback to {peer_id}")
            return self._send_resync_callback_sync(
                callback_url, payload, secret, peer_id
            )
        else:
            # Local mode: async fire-and-forget
            self._send_resync_callback_async(callback_url, payload, secret, peer_id)
            return True  # Scheduled (not confirmed)

    def _get_full_state_for_subscription(
        self,
        target: str,
        subtarget: str | None,
        list_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        """Get the full current state for a subscription target.

        Args:
            target: Subscription target (e.g., "properties")
            subtarget: Optional subtarget (e.g., list name for property lists)
            list_keys: When given, the keys of the result that are list diffs
                are added to it, so a caller can tell a list from a scalar
                property of the same shape (``fit_full_state``).

        Returns:
            Dict containing the full state
        """
        if target == "properties":
            if subtarget:
                # Specific property list or property
                if hasattr(self, "property_lists") and self.property_lists:
                    if self.property_lists.exists(subtarget):
                        # It's a list - return all items
                        list_attr = getattr(self.property_lists, subtarget)
                        if list_keys is not None:
                            list_keys.add(subtarget)
                        reference, pairs = self._list_state_reference(
                            subtarget, list_attr
                        )
                        if reference is not None:
                            return {subtarget: reference}
                        try:
                            if pairs is not None:
                                # The heads are in hand: resolve from them,
                                # one range read in all.
                                items = self._resolve_list_heads(list_attr, pairs)
                            else:
                                items = list(list_attr)
                        except ListCorruptionError as e:
                            logger.error(
                                f"List '{subtarget}' is corrupted, cannot build "
                                f"full-state resync for it: {e}"
                            )
                            return {}
                        logger.debug(
                            f"Getting full state for list '{subtarget}': {len(items)} items"
                        )
                        # Return as list operation format for diff
                        return {
                            subtarget: {
                                "list": subtarget,
                                "operation": "extend",
                                "items": items,
                            }
                        }

                # Try as scalar property
                prop_data = self.get_property(subtarget)
                if prop_data is not None:
                    logger.debug(f"Getting full state for property '{subtarget}'")
                    return {subtarget: prop_data}
                logger.warning(f"Subtarget '{subtarget}' not found as list or property")
                return {}
            else:
                # All properties - get both scalars and lists.
                # list_all_with_rows() pays for one whole-partition dump
                # and returns it alongside the names, so every list's
                # contents below are served from that dump
                # (to_list_from_rows()) instead of a second whole-list
                # Query per list -- this is the fallback path for peers
                # that don't support incremental resync, so it is lower
                # frequency than the web UI's equivalent fix but still one
                # headless consumers actually reach.
                result = {}
                # Get scalar properties
                all_props = self.get_properties()
                if all_props:
                    result.update(all_props)
                # Get property lists
                if hasattr(self, "property_lists") and self.property_lists:
                    list_names, list_rows = self.property_lists.list_all_with_rows()
                    for list_name in list_names:
                        list_attr = getattr(self.property_lists, list_name)
                        list_attr.prime_from_rows(list_rows)
                        if list_keys is not None:
                            list_keys.add(list_name)
                        reference, _ = self._list_state_reference(
                            list_name, list_attr, list_rows
                        )
                        if reference is not None:
                            result[list_name] = reference
                            continue
                        try:
                            items = list_attr.to_list_from_rows(list_rows)
                        except ListCorruptionError as e:
                            logger.error(
                                f"List '{list_name}' is corrupted, skipping it "
                                f"in full-state resync (other lists still "
                                f"included): {e}"
                            )
                            continue
                        result[list_name] = {
                            "list": list_name,
                            "operation": "extend",
                            "items": items,
                        }
                logger.debug(
                    f"Getting full state for all properties: {len(result)} keys"
                )
                return result
        return {}

    @staticmethod
    def _resolve_list_heads(list_attr: Any, pairs: list[tuple[Any, Any]]) -> list[Any]:
        """The items for heads read with ``resolve=False``: plain items as
        read, spanned ones through ``item_at``. An item deleted since the
        heads were read is dropped (the delete won, as in ``to_list()``); a
        broken one raises ``ListCorruptionError`` as before."""
        from .property_list import UNRESOLVED
        from .property_list import ListCorruptionError as _Corrupt

        items: list[Any] = []
        for handle, item in pairs:
            if item is not UNRESOLVED:
                items.append(item)
                continue
            try:
                items.append(list_attr.item_at(handle)[1])
            except _Corrupt:
                raise
            except IndexError:
                continue
        return items

    def _list_state_reference(
        self, list_name: str, list_attr: Any, rows: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, list[tuple[Any, Any]] | None]:
        """``(reference, pairs)`` for a list's full state.

        ``reference`` is the full-state reference for a list whose items
        together exceed the span threshold, sized from the heads alone so no
        spanned body is read only to be dropped; ``None`` when the list fits
        (or there is no threshold, or the list is v1). ``pairs`` are the
        heads this read (``items_with_handles(resolve=False)``, for a
        single list without ``rows``), so the caller resolves the items
        from them instead of reading the list again; ``None`` otherwise.
        """
        from .property_list import UNRESOLVED
        from .property_list import ListCorruptionError as _Corrupt
        from .property_list_span import encoded_size

        threshold = getattr(self.config, "list_item_span_threshold", None)
        if not isinstance(threshold, int) or isinstance(threshold, bool):
            return None, None
        core = getattr(list_attr, "_list_prop", list_attr)
        pairs: list[tuple[Any, Any]] | None = None
        try:
            if core.storage_format() != 2:
                return None, None  # a v1 list never spans: read it as before
            if rows is not None:
                sizes = list_attr.sizes_from_rows(rows)
            else:
                heads: list[tuple[Any, Any]] = list_attr.items_with_handles(
                    resolve=False
                )
                pairs = heads
                sizes = [
                    (
                        handle.bytes
                        if handle.bytes is not None
                        else encoded_size(handle.raw_value)
                    )
                    if item is UNRESOLVED
                    else encoded_size(json.dumps(item))
                    for handle, item in heads
                ]
        except (ValueError, _Corrupt):
            return None, None  # v1, or a malformed head: read as before
        total = sum(sizes)
        if total + 2 * len(sizes) + 64 <= threshold:
            return None, pairs
        return {
            "list": list_name,
            "operation": "extend",
            "spanned": True,
            "bytes": total,
        }, None

    def _store_subscription_diff(
        self, peer_id: str, subscription_id: str, sequence: int, data: dict[str, Any]
    ) -> str:
        """Store a subscription diff and return its URL.

        Args:
            peer_id: Peer actor ID
            subscription_id: Subscription ID
            sequence: Sequence number (already incremented)
            data: Diff data to store

        Returns:
            URL to fetch this diff, or "" when it was not stored
        """
        import json

        from .db import get_subscription_diff

        if not self.config:
            logger.error("No config available for storing subscription diff")
            return ""

        # Store diff using low-level diff protocol (sequence already incremented)
        logger.debug(
            f"Storing subscription diff for {subscription_id} seq={sequence}, "
            f"data keys: {list(data.keys())}"
        )

        diff_handle = get_subscription_diff(self.config)
        blob = json.dumps(data)

        logger.debug(f"Diff blob size: {len(blob)} chars")

        success = diff_handle.create(
            actor_id=self.id,
            subid=subscription_id,
            diff=blob,
            seqnr=sequence,
        )

        if not success:
            # Refused (the number already has a diff) or missing arguments: a
            # URL here would point the subscriber at another change's diff.
            logger.error(
                f"Failed to store subscription diff for {subscription_id} seq={sequence}, "
                f"actor_id={self.id}"
            )
            return ""
        logger.info(
            f"Successfully stored subscription diff for {subscription_id} seq={sequence}"
        )

        # Build URL to this diff
        # Format: /{actor_id}/subscriptions/{peer_id}/{subscription_id}/{sequence}
        diff_url = (
            f"{self.config.proto}{self.config.fqdn}/{self.id}"
            f"/subscriptions/{peer_id}/{subscription_id}/{sequence}"
        )
        logger.debug(f"Diff URL: {diff_url}")
        return diff_url

    def _increment_subscription_sequence(
        self, peer_id: str, subscription_id: str
    ) -> int:
        """Increment and return the new sequence number for a subscription.

        Args:
            peer_id: Peer actor ID
            subscription_id: Subscription ID

        Returns:
            New sequence number, or 0 when the subscription no longer exists
        """
        sub_obj = self.get_subscription_obj(peerid=peer_id, subid=subscription_id)
        if not sub_obj:
            return 0

        # Use the increase_seq() method which increments and returns new sequence.
        # 0 when the subscription row is gone: there is no number to give, and
        # 1 would repeat one the subscriber already has.
        new_seq = sub_obj.increase_seq()
        return new_seq if new_seq else 0

    def _leave_sequence_gap(self, sub: dict[str, Any]) -> None:
        """Move a subscription's sequence on without a diff, so the
        subscriber sees a gap at the next diff and recovers (the protocol's
        "MUST continue incrementing sequence numbers for each change").

        Used when a change got no diff because a read faulted. If the
        increment faults too, nothing can mark the change and it is lost.
        """
        if not self.config or not self.id:
            return
        from .db import get_subscription

        try:
            moved = get_subscription(self.config).increment_seq(
                actor_id=self.id,
                peerid=sub.get("peerid"),
                subid=sub.get("subscriptionid"),
            )
        except DbError as e:  # folds DbError: change lost; the write stands
            logger.error(
                f"Diff for subscription {sub.get('subscriptionid')} lost: no gap "
                f"could be left either: {e}"
            )
            return
        if moved:
            logger.warning(
                f"Left a gap at sequence {moved} of subscription "
                f"{sub.get('subscriptionid')} for a diff that was not registered"
            )

    # =========================================================================
    # Diff Registration
    # =========================================================================

    def register_diffs(self, target=None, subtarget=None, resource=None, blob=None):
        """Registers a blob diff against all subscriptions with the correct target, subtarget, and resource.

        If resource is set, the blob is expected to be the FULL resource object, not a diff.

        Note: Skips registration if the target/subtarget is currently suspended.
        Use suspend_subscriptions() and resume_subscriptions() to manage suspension.
        """
        if blob is None or not target:
            return

        # Get all subscriptions, both with the specific subtarget/resource and those
        # without. Deliberately BEFORE the suspension check: with no subscriptions
        # on this target, nothing below the loop runs and the old order paid a
        # suspension GetItem *plus* this fetch to reach the same no-op — on every
        # property write. Suspension and "no subscribers" are the same outcome
        # here, so the cheaper discriminator goes first. (Costs one extra fetch
        # for an actor that is both subscribed and suspended; that fetch is
        # memoised per actor instance and is dwarfed by the callback fan-out
        # suspension exists to avoid.)
        # strict=False: the write that produced the diff has committed, so a
        # fault reading the subscriptions does not fail it. No sequence moves,
        # so no subscriber can detect the lost diff; only a periodic poll or
        # resync recovers it.
        subs = self.get_subscriptions(
            target=target, subtarget=None, resource=None, callback=False, strict=False
        )
        if not subs:
            return

        # Check suspension BEFORE registering diffs
        if self.is_subscription_suspended(target, subtarget):
            logger.debug(
                f"Skipping diff registration for {target}/{subtarget}: suspended"
            )
            return
        if subtarget and resource:
            logger.debug(
                "register_diffs() - blob(%s chars), target(%s), subtarget(%s), resource(%s), # of subs(%s)",
                len(blob),
                target,
                subtarget,
                resource,
                len(subs),
            )
        elif subtarget:
            logger.debug(
                "register_diffs() - blob(%s chars), target(%s), subtarget(%s), # of subs(%s)",
                len(blob),
                target,
                subtarget,
                len(subs),
            )
        else:
            logger.debug(
                "register_diffs() - blob(%s chars), target(%s), # of subs(%s)",
                len(blob),
                target,
                len(subs),
            )
        for sub in subs:
            registered = False
            try:
                # Skip the ones without correct subtarget
                if subtarget and sub["subtarget"] and sub["subtarget"] != subtarget:
                    logger.debug("     - no match on subtarget, skipping...")
                    continue
                # Skip the ones without correct resource
                if resource and sub["resource"] and sub["resource"] != resource:
                    logger.debug("     - no match on resource, skipping...")
                    continue
                sub_obj = self.get_subscription_obj(
                    peerid=sub["peerid"], subid=sub["subscriptionid"]
                )
                if not sub_obj:
                    continue
                sub_obj_data = sub_obj.get()
                logger.debug(
                    "     - processing subscription(%s) for peer(%s) with target(%s) subtarget(%s) and resource(%s)",
                    sub["subscriptionid"],
                    sub["peerid"],
                    sub_obj_data["target"],
                    sub_obj_data["subtarget"] or "",
                    sub_obj_data["resource"] or "",
                )
                # Subscription with a resource, but this diff is on a higher level
                if (
                    (not resource or not subtarget)
                    and sub_obj_data["subtarget"]
                    and sub_obj_data["resource"]
                ):
                    # Create a json diff on the subpart that this subscription
                    # covers
                    try:
                        jsonblob = json.loads(blob)
                        if not subtarget:
                            subblob = json.dumps(
                                jsonblob[sub_obj_data["subtarget"]][
                                    sub_obj_data["resource"]
                                ]
                            )
                        else:
                            subblob = json.dumps(jsonblob[sub_obj_data["resource"]])
                    except (TypeError, ValueError, KeyError):
                        # The diff does not contain the resource
                        logger.debug(
                            "         - subscription has resource(%s), no matching blob found in diff",
                            sub_obj_data["resource"],
                        )
                        continue
                    logger.debug(
                        "         - subscription has resource(%s), adding diff(%s chars)",
                        sub_obj_data["resource"],
                        len(subblob),
                    )
                    finblob = subblob
                # The diff is on the resource, but the subscription is on a
                # higher level
                elif resource and not sub_obj_data["resource"]:
                    # Since we have a resource, we know the blob is the entire resource, not a diff
                    # If the subscription is for a sub-target, send [resource] = blob
                    # If the subscription is for a target, send [subtarget][resource] = blob
                    upblob = {}
                    try:
                        jsonblob = json.loads(blob)
                        if not sub_obj_data["subtarget"]:
                            upblob[subtarget] = {}
                            upblob[subtarget][resource] = jsonblob
                        else:
                            upblob[resource] = jsonblob
                    except (TypeError, ValueError, KeyError):
                        if not sub_obj_data["subtarget"]:
                            upblob[subtarget] = {}
                            upblob[subtarget][resource] = blob
                        else:
                            upblob[resource] = blob
                    finblob = json.dumps(upblob)
                    logger.debug(
                        "         - diff has resource(%s), subscription has not, adding diff(%s bytes)",
                        resource,
                        len(finblob),
                    )
                # Subscriptions with subtarget, but this diff is on a higher level
                elif not subtarget and sub_obj_data["subtarget"]:
                    # Create a json diff on the subpart that this subscription
                    # covers
                    subblob = None
                    try:
                        jsonblob = json.loads(blob)
                        subblob = json.dumps(jsonblob[sub_obj_data["subtarget"]])
                    except (TypeError, ValueError, KeyError):
                        # The diff blob does not contain the subtarget
                        pass
                    logger.debug(
                        "         - subscription has subtarget(%s), adding diff(%s bytes)",
                        sub_obj_data["subtarget"],
                        len(subblob) if subblob else 0,
                    )
                    finblob = subblob
                # The diff is on the subtarget, but the subscription is on the
                # higher level
                elif subtarget and not sub_obj_data["subtarget"]:
                    # Create a data["subtarget"] = blob diff to give correct level
                    # of diff to subscriber
                    upblob = {}
                    try:
                        jsonblob = json.loads(blob)
                        upblob[subtarget] = jsonblob
                    except (TypeError, ValueError, KeyError):
                        upblob[subtarget] = blob
                    finblob = json.dumps(upblob)
                    logger.debug(
                        "         - diff has subtarget(%s), subscription has not, adding diff(%s chars)",
                        subtarget,
                        len(finblob),
                    )
                else:
                    # The diff is correct for the subscription
                    logger.debug(
                        "         - exact target/subtarget match, adding diff(%s chars)",
                        len(blob),
                    )
                    finblob = blob
                if sub_obj:
                    diff = sub_obj.add_diff(blob=finblob)
                else:
                    diff = None
                # add_diff returned, so it used a sequence number: a failure
                # from here on leaves a stored diff or a gap already.
                registered = True
                if not diff:
                    logger.warning(
                        "Failed when registering a diff to subscription (%s). Will not send callback.",
                        sub["subscriptionid"],
                    )
                else:
                    # Direct call - callback_subscription handles sync/async internally
                    self.callback_subscription(
                        peerid=sub["peerid"],
                        sub_obj=sub_obj,
                        sub=sub_obj_data,
                        diff=diff,
                        blob=finblob,
                    )
            except DbError as e:  # folds DbError: one subscriber skipped; gap tried
                # One subscriber's fault must not stop the others or fail the
                # write that produced the diff, which has committed.
                logger.error(
                    f"Diff registration for subscription {sub.get('subscriptionid')} "
                    f"skipped on a store fault: {e}"
                )
                if not registered:
                    # The read faulted before the resource checks below it,
                    # so a subscriber that would have got no diff can get a
                    # gap too; it resyncs needlessly, which is safe.
                    self._leave_sequence_gap(sub)


class Actors:
    """Handles all actors"""

    def fetch(self):
        if not self.list:
            return False
        if self.actors is not None:
            return self.actors
        self.actors = self.list.fetch()
        return self.actors

    def __init__(self, config=None):
        self.config = config
        if self.config:
            self.list = get_actor_list(self.config)
        else:
            self.list = None
        self.actors = None
        self.fetch()
