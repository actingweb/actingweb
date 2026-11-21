"""Actor rows written as stored, for the creator-uniqueness tests."""

from __future__ import annotations

import uuid

from .conftest import DATABASE_BACKEND

DYNAMODB = DATABASE_BACKEND == "dynamodb"


def raw_actor(creator: str) -> str:
    """An actor row written as stored, bypassing the lowercasing and the
    creator records (a legacy mixed-case address, or a restored row)."""
    actor_id = uuid.uuid4().hex
    if DYNAMODB:
        from actingweb.db.dynamodb.actor import Actor as ActorModel

        ActorModel(id=actor_id, creator=creator, passphrase="pw").save()
    else:
        from actingweb.db.postgresql.connection import get_connection

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO actors (id, creator, passphrase, created_at) "
                    "VALUES (%s, %s, 'pw', NOW())",
                    (actor_id, creator),
                )
            conn.commit()
    return actor_id
