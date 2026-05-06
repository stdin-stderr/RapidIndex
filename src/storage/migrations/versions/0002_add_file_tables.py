"""Add usenet_files and torrent_files tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "usenet_files",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "release_id",
            UUID(as_uuid=True),
            sa.ForeignKey("releases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger, nullable=False),
        sa.Column("file_index", sa.Integer, nullable=False),
        sa.Column("segment_ids", sa.ARRAY(sa.String), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("release_id", "filename", name="uq_usenet_files_release_filename"),
    )
    op.create_index("ix_usenet_files_release_id", "usenet_files", ["release_id"])

    op.create_table(
        "torrent_files",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "release_id",
            UUID(as_uuid=True),
            sa.ForeignKey("releases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger, nullable=False),
        sa.Column("file_index", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("release_id", "file_index", name="uq_torrent_files_release_index"),
    )
    op.create_index("ix_torrent_files_release_id", "torrent_files", ["release_id"])


def downgrade() -> None:
    op.drop_index("ix_torrent_files_release_id", "torrent_files")
    op.drop_table("torrent_files")
    op.drop_index("ix_usenet_files_release_id", "usenet_files")
    op.drop_table("usenet_files")
