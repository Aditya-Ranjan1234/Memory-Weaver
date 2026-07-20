"""Hash invitation tokens that predate hashed storage."""

import hashlib
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260721_03"
down_revision: Union[str, None] = "20260721_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    tokens = list(connection.execute(sa.text("SELECT token FROM invites")).scalars())
    for token in tokens:
        if re.fullmatch(r"[0-9a-f]{64}", token):
            continue
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        connection.execute(
            sa.text("UPDATE invites SET token = :digest WHERE token = :token"),
            {"digest": digest, "token": token},
        )


def downgrade() -> None:
    # Cryptographic hashes are intentionally irreversible.
    pass
