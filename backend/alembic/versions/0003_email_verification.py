"""Add Gmail-only email verification fields to users.

Revision ID: 0003_email_verification
Revises: 0002_profile_settings
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_email_verification"
down_revision = "0002_profile_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing accounts remain usable; new registrations explicitly set this to false.
    op.add_column("users", sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("1")))
    op.add_column("users", sa.Column("verification_code_hash", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("verification_expires_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("verification_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    op.drop_column("users", "verification_attempts")
    op.drop_column("users", "verification_expires_at")
    op.drop_column("users", "verification_code_hash")
    op.drop_column("users", "email_verified")
