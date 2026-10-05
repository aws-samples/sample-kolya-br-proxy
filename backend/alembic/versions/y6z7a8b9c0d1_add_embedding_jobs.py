"""add durable asynchronous embedding jobs

Revision ID: y6z7a8b9c0d1
Revises: x5y6z7a8b9c0
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "y6z7a8b9c0d1"
down_revision = "x5y6z7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
        "ix_embedding_jobs_status_updated",
        "embedding_jobs",
        ["status", "updated_at"],
    )
    op.create_index(
        "ix_embedding_jobs_token_created",
        "embedding_jobs",
        ["token_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_embedding_jobs_token_created", table_name="embedding_jobs")
    op.drop_index("ix_embedding_jobs_status_updated", table_name="embedding_jobs")
    op.drop_table("embedding_jobs")
