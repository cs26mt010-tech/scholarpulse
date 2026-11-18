"""Add profile fields used by the latest ScholarPulse prototype.

Revision ID: 0002_profile_settings
Revises: 0001_initial_schema
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_profile_settings"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("programme", sa.String(length=120), nullable=True))
    op.add_column("users", sa.Column("profile_photo_path", sa.String(length=500), nullable=True))
    op.add_column("users", sa.Column("email_notifications", sa.Boolean(), nullable=False, server_default=sa.text("1")))
    op.add_column("users", sa.Column("public_profile", sa.Boolean(), nullable=False, server_default=sa.text("1")))


def downgrade() -> None:
    op.drop_column("users", "public_profile")
    op.drop_column("users", "email_notifications")
    op.drop_column("users", "profile_photo_path")
    op.drop_column("users", "programme")
