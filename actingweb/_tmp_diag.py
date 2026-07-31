"""TEMPORARY CI diagnostic. Delete before merge."""

import logging
import os
import threading
from typing import Any

logger = logging.getLogger("actingweb.TMPDIAG")


def _pg_state(actor_id: str) -> str:
    try:
        from .db.postgresql.connection import get_connection

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT current_schema(), "
                    "(SELECT count(*) FROM trusts), "
                    "(SELECT count(*) FROM trusts WHERE id=%s), "
                    "(SELECT count(*) FROM actors WHERE id=%s)",
                    (actor_id, actor_id),
                )
                row = cur.fetchone()
                if row is None:
                    return "pg=norow"
                return f"schema={row[0]} trusts_total={row[1]} trusts_mine={row[2]} actor_rows={row[3]}"
    except Exception as e:  # pragma: no cover
        return f"pg_err={type(e).__name__}:{e}"


def _diag_probe(tag: str, actor_id: str, client_id: str, actor_interface: Any) -> None:
    """Log the trust-visibility state from the caller's own connection."""
    try:
        try:
            rels = list(actor_interface.trust.relationships)
            n = len(rels)
            peers = [str(getattr(r, "peerid", ""))[:60] for r in rels]
        except Exception as e:
            n = -1
            peers = [f"err={e}"]
        logger.error(
            "TMPDIAG %s pid=%s tid=%s actor=%s client=%s n_via_api=%s %s peers=%s",
            tag,
            os.getpid(),
            threading.get_ident(),
            actor_id,
            client_id,
            n,
            _pg_state(actor_id),
            peers,
        )
    except Exception:  # pragma: no cover
        pass
