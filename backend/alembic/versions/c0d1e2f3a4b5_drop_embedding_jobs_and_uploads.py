"""drop asynchronous embedding jobs and media uploads

The gateway's embeddings were narrowed to the OpenAI-compatible
``/v1/embeddings`` endpoint with inline text and images. Asynchronous jobs
(y6z7a8b9c0d1) and presigned uploads (b9c0d1e2f3a4) were removed.

Those revisions stay in history because deployed databases may already be at
them; deleting applied revisions would make ``alembic upgrade`` fail with
"Can't locate revision". This migration drops their tables instead, so
fresh and already-upgraded databases converge on the same schema.

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c0d1e2f3a4b5"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS embedding_uploads")
    op.execute("DROP TABLE IF EXISTS embedding_jobs")


def downgrade() -> None:
    # Recreate the empty tables so earlier downgrades remain valid.
    op.create_table(
        "embedding_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("region", sa.String(length=32), nullable=False),
        sa.Column("invocation_arn", sa.String(length=2048), nullable=True),
        sa.Column("output_s3_uri", sa.String(length=1024), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("request_metadata", sa.JSON(), nullable=True),
        sa.Column("failure_message", sa.String(length=500), nullable=True),
        sa.Column("usage_recorded_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["token_id"], ["api_tokens.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("invocation_arn"),
        sa.UniqueConstraint(
            "token_id", "idempotency_key", name="uq_embedding_job_token_key"
        ),
    )
    op.create_index(
        "ix_embedding_jobs_status_updated", "embedding_jobs", ["status", "updated_at"]
    )
    op.create_index(
        "ix_embedding_jobs_token_created", "embedding_jobs", ["token_id", "created_at"]
    )
    op.create_table(
        "embedding_uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("s3_uri", sa.String(length=1024), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("declared_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["token_id"], ["api_tokens.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("s3_uri"),
    )
    op.create_index(
        "ix_embedding_uploads_token_created",
        "embedding_uploads",
        ["token_id", "created_at"],
    )
