"""add guest_identifier and expires_at to urls

Revision ID: a1b2c3d4e5f6
Revises: eebb728dfdb9
Create Date: 2026-06-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'eebb728dfdb9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('urls', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('urls', sa.Column('guest_identifier', sa.String(length=45), nullable=True))


def downgrade() -> None:
    op.drop_column('urls', 'guest_identifier')
    op.drop_column('urls', 'expires_at')
