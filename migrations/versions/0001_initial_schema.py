"""initial schema

The whole schema in one revision. It is a baseline, not the first step of a
history: this project keeps no upgrade path from anything older, because
there is nothing older deployed. A clone runs ``alembic upgrade head`` once
and has the schema the models describe.

Two things in here are decisions rather than mechanics, and are stated so
they are not quietly undone later:

* ``urls.owner_id`` is ``ON DELETE CASCADE``. Links do not outlive the
  account that made them, and there is no recovery. Deleting a user is
  normally done by ``DeleteUserUseCase``, in the transaction that removes
  the account, because rows that vanish behind the application leave their
  cache entries behind -- every level would go on answering for a link that
  no longer exists, for the rest of its TTL, with nothing able to clear it.
  This constraint is the backstop for a deletion done outside the
  application, and the statement of intent in the schema itself.

* The composite indexes on ``urls`` cover the two lookups that run on every
  guest creation and every expiry sweep. Without them both are sequential
  scans over the whole table.

* ``users.email_verified`` defaults to False in the database, not only in
  the model. A row written by anything that does not know about
  confirmation -- a repair script, a fixture, a later revision -- is then
  unconfirmed rather than trusted, and an account nobody confirmed cannot
  sign in.

* ``email_verifications`` keeps the digest of a mailed token and never the
  token. A row read out of a backup or a replica is worth nothing on its
  own: it cannot be turned back into the link that was sent. The digest is
  SHA-256 in hex, which is why the column is exactly 64 characters -- a
  narrower one would keep a prefix, and a prefix never matches. The
  uniqueness is not decoration either: two accounts sharing a digest would
  be two accounts sharing a token.

Revision ID: 0001
Revises:
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create every table, index and constraint the models declare."""
    op.create_table('permissions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('resource', sa.String(length=50), nullable=False),
    sa.Column('action', sa.String(length=50), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('roles',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=50), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=True),
    sa.Column('is_system', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('users',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('email_verified', sa.Boolean(), nullable=False,
              server_default=sa.false()),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_login', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_table('email_verifications',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_email_verifications_token_hash'), 'email_verifications', ['token_hash'], unique=True)
    op.create_index(op.f('ix_email_verifications_user_id'), 'email_verifications', ['user_id'], unique=False)
    op.create_table('refresh_sessions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('token_id', sa.String(length=36), nullable=False),
    sa.Column('chain_id', sa.String(length=36), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('replaced_by', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_refresh_sessions_chain_id'), 'refresh_sessions', ['chain_id'], unique=False)
    op.create_index(op.f('ix_refresh_sessions_token_id'), 'refresh_sessions', ['token_id'], unique=True)
    op.create_index(op.f('ix_refresh_sessions_user_id'), 'refresh_sessions', ['user_id'], unique=False)
    op.create_table('role_permissions',
    sa.Column('role_id', sa.String(length=36), nullable=False),
    sa.Column('permission_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('role_id', 'permission_id')
    )
    op.create_table('urls',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('url_hash', sa.String(length=64), nullable=False),
    sa.Column('original_url', sa.String(length=2048), nullable=False),
    sa.Column('short_code', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('clicks', sa.Integer(), nullable=False),
    sa.Column('last_accessed', sa.DateTime(timezone=True), nullable=True),
    sa.Column('owner_id', sa.String(length=36), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('guest_identifier', sa.String(length=45), nullable=True),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], name='fk_urls_owner_id_users', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_urls_clicks'), 'urls', ['clicks'], unique=False)
    op.create_index('ix_urls_expires_at', 'urls', ['expires_at'], unique=False)
    op.create_index('ix_urls_guest_identifier_created_at', 'urls', ['guest_identifier', 'created_at'], unique=False)
    op.create_index(op.f('ix_urls_owner_id'), 'urls', ['owner_id'], unique=False)
    op.create_index(op.f('ix_urls_short_code'), 'urls', ['short_code'], unique=True)
    op.create_index('ix_urls_url_hash_guest_identifier', 'urls', ['url_hash', 'guest_identifier'], unique=False)
    op.create_index('ix_urls_url_hash_owner_id', 'urls', ['url_hash', 'owner_id'], unique=False)
    op.create_table('user_roles',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('role_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'role_id')
    )


def downgrade() -> None:
    """Remove everything this revision created."""
    op.drop_table('user_roles')
    op.drop_index('ix_urls_url_hash_owner_id', table_name='urls')
    op.drop_index('ix_urls_url_hash_guest_identifier', table_name='urls')
    op.drop_index(op.f('ix_urls_short_code'), table_name='urls')
    op.drop_index(op.f('ix_urls_owner_id'), table_name='urls')
    op.drop_index('ix_urls_guest_identifier_created_at', table_name='urls')
    op.drop_index('ix_urls_expires_at', table_name='urls')
    op.drop_index(op.f('ix_urls_clicks'), table_name='urls')
    op.drop_table('urls')
    op.drop_table('role_permissions')
    op.drop_index(op.f('ix_refresh_sessions_user_id'), table_name='refresh_sessions')
    op.drop_index(op.f('ix_refresh_sessions_token_id'), table_name='refresh_sessions')
    op.drop_index(op.f('ix_refresh_sessions_chain_id'), table_name='refresh_sessions')
    op.drop_table('refresh_sessions')
    op.drop_index(op.f('ix_email_verifications_user_id'), table_name='email_verifications')
    op.drop_index(op.f('ix_email_verifications_token_hash'), table_name='email_verifications')
    op.drop_table('email_verifications')
    op.drop_index(op.f('ix_users_email'), table_name='users')
    op.drop_table('users')
    op.drop_table('roles')
    op.drop_table('permissions')
