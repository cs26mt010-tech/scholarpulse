"""
SQLAlchemy 2.0 ORM Models for ScholarPulse (MS-3).
Defines all 12 related tables specified in MS-1 Section 7 and MS-2 ER Diagram:
1. users
2. categories
3. resources
4. resource_chunks
5. tags
6. resource_tags
7. ratings
8. comments
9. collections
10. collection_items
11. reports
12. ai_queries
"""
from datetime import datetime, date
from typing import List, Optional

try:
    from sqlalchemy import (
        Column,
        Integer,
        String,
        Text,
        Boolean,
        Float,
        Date,
        DateTime,
        ForeignKey,
        UniqueConstraint,
        Index,
        CheckConstraint,
    )
    from sqlalchemy.orm import declarative_base, relationship

    Base = declarative_base()

    class User(Base):
        __tablename__ = "users"

        id = Column(Integer, primary_key=True, autoincrement=True)
        username = Column(String(50), unique=True, nullable=False, index=True)
        email = Column(String(120), unique=True, nullable=False, index=True)
        password_hash = Column(String(255), nullable=False)
        bio = Column(String(500), nullable=True)
        role = Column(String(20), nullable=False, default="student", index=True)  # student | ta | moderator
        consent_accepted = Column(Boolean, nullable=False, default=True)
        created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

        resources = relationship("Resource", back_populates="uploader", cascade="all, delete-orphan")
        ratings = relationship("Rating", back_populates="user", cascade="all, delete-orphan")
        comments = relationship("Comment", back_populates="user", cascade="all, delete-orphan")
        collections = relationship("Collection", back_populates="owner", cascade="all, delete-orphan")

    class Category(Base):
        __tablename__ = "categories"

        id = Column(Integer, primary_key=True, autoincrement=True)
        course_code = Column(String(20), unique=True, nullable=False, index=True)  # CS301, CS402, CS205, SE101
        course_name = Column(String(150), nullable=False)
        department = Column(String(100), nullable=False, default="Computer Science & Engineering")
        description = Column(String(500), nullable=True)
        created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

        resources = relationship("Resource", back_populates="category")

    class Resource(Base):
        __tablename__ = "resources"

        id = Column(Integer, primary_key=True, autoincrement=True)
        title = Column(String(200), nullable=False, index=True)  # Indexed VARCHAR(200) per MS-1 Field Mapping
        content_text = Column(Text, nullable=False)
        tldr_summary = Column(String(1000), nullable=True)
        resource_type = Column(String(30), nullable=False, default="paper_summary", index=True)
        category_id = Column(Integer, ForeignKey("categories.id", ondelete="RESTRICT"), nullable=False, index=True)
        uploader_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
        source_authors = Column(String(500), nullable=True)  # Plain text arXiv authors
        source_ref = Column(String(100), nullable=True, unique=True, index=True)  # arXiv ID or note ref
        published_on = Column(Date, nullable=True, index=True)
        file_name = Column(String(255), nullable=True)
        file_size_bytes = Column(Integer, nullable=True)
        is_official = Column(Boolean, nullable=False, default=False, index=True)
        rights_confirmed = Column(Boolean, nullable=False, default=True)
        status = Column(String(20), nullable=False, default="active", index=True)  # active | hidden | removed
        embedding_status = Column(String(20), nullable=False, default="completed")  # pending | completed | failed
        avg_rating = Column(Float, nullable=False, default=0.0, index=True)
        rating_count = Column(Integer, nullable=False, default=0)
        comment_count = Column(Integer, nullable=False, default=0)
        created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
        updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

        category = relationship("Category", back_populates="resources")
        uploader = relationship("User", back_populates="resources")
        chunks = relationship("ResourceChunk", back_populates="resource", cascade="all, delete-orphan")
        resource_tags = relationship("ResourceTag", back_populates="resource", cascade="all, delete-orphan")
        ratings = relationship("Rating", back_populates="resource", cascade="all, delete-orphan")
        comments = relationship("Comment", back_populates="resource", cascade="all, delete-orphan")

        __table_args__ = (
            Index("ix_resources_cat_status_rating", "category_id", "status", "avg_rating"),
            Index("ix_resources_type_status_created", "resource_type", "status", "created_at"),
        )

    class ResourceChunk(Base):
        __tablename__ = "resource_chunks"

        id = Column(Integer, primary_key=True, autoincrement=True)
        resource_id = Column(Integer, ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
        chunk_index = Column(Integer, nullable=False)
        chunk_text = Column(Text, nullable=False)
        char_length = Column(Integer, nullable=False)
        embedding_json = Column(Text, nullable=True)  # JSON-serialized float vector from gemini-embedding-001
        embedding_model = Column(String(60), nullable=False, default="gemini-embedding-001")
        created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

        resource = relationship("Resource", back_populates="chunks")

        __table_args__ = (
            UniqueConstraint("resource_id", "chunk_index", name="uq_resource_chunk_idx"),
            Index("ix_chunks_resource_idx", "resource_id", "chunk_index"),
        )

    class Tag(Base):
        __tablename__ = "tags"

        id = Column(Integer, primary_key=True, autoincrement=True)
        name = Column(String(60), unique=True, nullable=False, index=True)
        slug = Column(String(60), unique=True, nullable=False, index=True)
        created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

        resource_tags = relationship("ResourceTag", back_populates="tag", cascade="all, delete-orphan")

    class ResourceTag(Base):
        __tablename__ = "resource_tags"

        resource_id = Column(Integer, ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True)
        tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
        created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

        resource = relationship("Resource", back_populates="resource_tags")
        tag = relationship("Tag", back_populates="resource_tags")

        __table_args__ = (
            Index("ix_resource_tags_tag_id", "tag_id"),
        )

    class Rating(Base):
        __tablename__ = "ratings"

        id = Column(Integer, primary_key=True, autoincrement=True)
        resource_id = Column(Integer, ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
        user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
        score = Column(Integer, nullable=False)  # 1 to 5 stars
        created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
        updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

        resource = relationship("Resource", back_populates="ratings")
        user = relationship("User", back_populates="ratings")

        __table_args__ = (
            UniqueConstraint("resource_id", "user_id", name="uq_rating_resource_user"),
            CheckConstraint("score >= 1 AND score <= 5", name="ck_rating_score_range"),
        )

    class Comment(Base):
        __tablename__ = "comments"

        id = Column(Integer, primary_key=True, autoincrement=True)
        resource_id = Column(Integer, ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
        user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
        body = Column(Text, nullable=False)
        status = Column(String(20), nullable=False, default="active", index=True)  # active | hidden | removed
        created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
        updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

        resource = relationship("Resource", back_populates="comments")
        user = relationship("User", back_populates="comments")

    class Collection(Base):
        __tablename__ = "collections"

        id = Column(Integer, primary_key=True, autoincrement=True)
        title = Column(String(150), nullable=False, index=True)
        description = Column(String(1000), nullable=True)
        owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
        category_id = Column(Integer, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True)
        is_official = Column(Boolean, nullable=False, default=False, index=True)
        is_public = Column(Boolean, nullable=False, default=True, index=True)
        created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
        updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

        owner = relationship("User", back_populates="collections")
        items = relationship("CollectionItem", back_populates="collection", cascade="all, delete-orphan")

        __table_args__ = (
            Index("ix_collections_official_public", "is_official", "is_public", "created_at"),
        )

    class CollectionItem(Base):
        __tablename__ = "collection_items"

        id = Column(Integer, primary_key=True, autoincrement=True)
        collection_id = Column(Integer, ForeignKey("collections.id", ondelete="CASCADE"), nullable=False, index=True)
        resource_id = Column(Integer, ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
        position = Column(Integer, nullable=False, default=1)
        notes = Column(String(300), nullable=True)
        added_at = Column(DateTime, nullable=False, default=datetime.utcnow)

        collection = relationship("Collection", back_populates="items")
        resource = relationship("Resource")

        __table_args__ = (
            UniqueConstraint("collection_id", "resource_id", name="uq_collection_resource"),
            Index("ix_collection_items_order", "collection_id", "position"),
        )

    class Report(Base):
        __tablename__ = "reports"

        id = Column(Integer, primary_key=True, autoincrement=True)
        reporter_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
        target_type = Column(String(20), nullable=False)  # resource | comment
        target_id = Column(Integer, nullable=False)
        reason = Column(String(50), nullable=False)
        details = Column(String(1000), nullable=True)
        status = Column(String(20), nullable=False, default="open", index=True)  # open | reviewing | resolved | dismissed
        moderator_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
        moderation_action = Column(String(30), nullable=True)  # hide | restore | remove | dismiss
        moderation_note = Column(String(500), nullable=True)
        created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
        resolved_at = Column(DateTime, nullable=True)

        __table_args__ = (
            Index("ix_reports_status_created", "status", "created_at"),
            Index("ix_reports_target", "target_type", "target_id"),
        )

    class AIQuery(Base):
        __tablename__ = "ai_queries"

        id = Column(Integer, primary_key=True, autoincrement=True)
        user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
        scope_type = Column(String(20), nullable=False, index=True)  # resource | collection | course
        scope_id = Column(String(50), nullable=False, index=True)
        question = Column(String(300), nullable=False)
        answer_text = Column(Text, nullable=False)
        cited_chunk_ids_json = Column(String(500), nullable=False, default="[]")
        not_found = Column(Boolean, nullable=False, default=False)
        fallback_used = Column(Boolean, nullable=False, default=False)
        model_used = Column(String(60), nullable=False, default="gemini-2.5-flash")
        latency_ms = Column(Integer, nullable=False, default=0)
        created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

        __table_args__ = (
            Index("ix_ai_queries_user_created", "user_id", "created_at"),
            Index("ix_ai_queries_scope", "scope_type", "scope_id"),
        )

except ImportError:
    Base = None
