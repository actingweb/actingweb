"""The DynamoDB ``creators`` table: one item per held creator.

With ``with_unique_creator()`` on, every non-exempt creator has an item here
naming the actor that holds it, written in the same ``TransactWriteItems`` as
the actor create, so a second create for the same creator fails its condition.
The actor table stays keyed by id, and its scans stay clean.

``actingweb-unique-creators enable`` backfills the table and then writes the
item :data:`~actingweb.db.creator_rules.BACKFILL_KEY`; the startup check
refuses to run with the flag on until that item exists.
"""

import os

from pynamodb.attributes import UnicodeAttribute
from pynamodb.constants import PAY_PER_REQUEST_BILLING_MODE
from pynamodb.models import Model


class Creator(Model):
    """A held creator and the actor holding it."""

    class Meta:  # type: ignore[misc]
        table_name = os.getenv("AWS_DB_PREFIX", "demo_actingweb") + "_creators"
        billing_mode = PAY_PER_REQUEST_BILLING_MODE
        region = os.getenv("AWS_DEFAULT_REGION", "us-west-1")
        host = os.getenv("AWS_DB_HOST", None)

    creator = UnicodeAttribute(hash_key=True)
    # Absent on the backfill-complete item.
    actor_id = UnicodeAttribute(null=True)
