"""Add password reset fields to users.

Revision ID: 0004_password_reset
Revises: 0003_email_verification
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_password_reset"
down_revision = "0003_email_verification"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("password_reset_code_hash", sa.String(64), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("password_reset_expires_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column(
            "password_reset_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0")
        )
    )


def downgrade():
    op.drop_column("users", "password_reset_attempts")
    op.drop_column("users", "password_reset_expires_at")
    op.drop_column("users", "password_reset_code_hash")
