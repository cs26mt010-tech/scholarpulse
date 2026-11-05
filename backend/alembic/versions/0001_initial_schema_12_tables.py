"""Initial ScholarPulse 12-table schema with MySQL FULLTEXT and composite indexes

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-10-27 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("bio", sa.String(length=500), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="student"),
        sa.Column("consent_accepted", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_role", "users", ["role"])

    # 2. categories
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("course_code", sa.String(length=20), nullable=False),
        sa.Column("course_name", sa.String(length=150), nullable=False),
        sa.Column("department", sa.String(length=100), nullable=False, server_default="Computer Science & Engineering"),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("course_code", name="uq_categories_course_code"),
    )

    # 3. resources
    op.create_table(
        "resources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("tldr_summary", sa.String(length=1000), nullable=True),
        sa.Column("resource_type", sa.String(length=30), nullable=False, server_default="paper_summary"),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("uploader_id", sa.Integer(), nullable=True),
        sa.Column("source_authors", sa.String(length=500), nullable=True),
        sa.Column("source_ref", sa.String(length=100), nullable=True),
        sa.Column("published_on", sa.Date(), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("is_official", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("rights_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("embedding_status", sa.String(length=20), nullable=False, server_default="completed"),
        sa.Column("avg_rating", sa.Float(), nullable=False, server_default=sa.text("0.0")),
        sa.Column("rating_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("comment_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_ref", name="uq_resources_source_ref"),
    )
    op.create_index("ix_resources_title", "resources", ["title"])
    op.create_index("ix_resources_cat_status_rating", "resources", ["category_id", "status", "avg_rating"])
    op.create_index("ix_resources_type_status_created", "resources", ["resource_type", "status", "created_at"])

    # 4. resource_chunks
    op.create_table(
        "resource_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("char_length", sa.Integer(), nullable=False),
        sa.Column("embedding_json", sa.Text(), nullable=True),
        sa.Column("embedding_model", sa.String(length=60), nullable=False, server_default="gemini-embedding-001"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resource_id", "chunk_index", name="uq_resource_chunk_idx"),
    )
    op.create_index("ix_chunks_resource_idx", "resource_chunks", ["resource_id", "chunk_index"])

    # Create MySQL FULLTEXT index on resource_chunks(chunk_text) and resources(title, content_text) when running on MySQL
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute("CREATE FULLTEXT INDEX ft_resource_chunks_text ON resource_chunks (chunk_text)")
        op.execute("CREATE FULLTEXT INDEX ft_resources_title_content ON resources (title, content_text)")

    # 5. tags
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("slug", sa.String(length=60), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_tags_name"),
        sa.UniqueConstraint("slug", name="uq_tags_slug"),
    )

    # 6. resource_tags
    op.create_table(
        "resource_tags",
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("resource_id", "tag_id"),
    )
    op.create_index("ix_resource_tags_tag_id", "resource_tags", ["tag_id"])

    # 7. ratings
    op.create_table(
        "ratings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_rating_score_range"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("resource_id", "user_id", name="uq_rating_resource_user"),
    )

    # 8. comments
    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_comments_resource_status", "comments", ["resource_id", "status", "created_at"])

    # 9. collections
    op.create_table(
        "collections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("is_official", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["categories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collections_official_public", "collections", ["is_official", "is_public", "created_at"])

    # 10. collection_items
    op.create_table(
        "collection_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("notes", sa.String(length=300), nullable=True),
        sa.Column("added_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("collection_id", "resource_id", name="uq_collection_resource"),
    )
    op.create_index("ix_collection_items_order", "collection_items", ["collection_id", "position"])

    # 11. reports
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("reporter_id", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=50), nullable=False),
        sa.Column("details", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("moderator_id", sa.Integer(), nullable=True),
        sa.Column("moderation_action", sa.String(length=30), nullable=True),
        sa.Column("moderation_note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["moderator_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reports_status_created", "reports", ["status", "created_at"])
    op.create_index("ix_reports_target", "reports", ["target_type", "target_id"])

    # 12. ai_queries
    op.create_table(
        "ai_queries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.String(length=50), nullable=False),
        sa.Column("question", sa.String(length=300), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("cited_chunk_ids_json", sa.String(length=500), nullable=False, server_default="[]"),
        sa.Column("not_found", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("model_used", sa.String(length=60), nullable=False, server_default="gemini-2.5-flash"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_queries_user_created", "ai_queries", ["user_id", "created_at"])
    op.create_index("ix_ai_queries_scope", "ai_queries", ["scope_type", "scope_id"])


def downgrade() -> None:
    op.drop_table("ai_queries")
    op.drop_table("reports")
    op.drop_table("collection_items")
    op.drop_table("collections")
    op.drop_table("comments")
    op.drop_table("ratings")
    op.drop_table("resource_tags")
    op.drop_table("tags")
    op.drop_table("resource_chunks")
    op.drop_table("resources")
    op.drop_table("categories")
    op.drop_table("users")
