"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scan_state",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("source_name", sa.Text, unique=True, nullable=False),
        sa.Column("watermark", sa.Text),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "tpdb_networks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text),
        sa.Column("slug", sa.String),
    )

    op.create_table(
        "tpdb_sites",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text),
        sa.Column(
            "network_id",
            sa.Integer,
            sa.ForeignKey("tpdb_networks.id", ondelete="SET NULL"),
        ),
        sa.Column("slug", sa.String),
        sa.Column("logo_url", sa.Text),
    )

    op.create_table(
        "releases",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_type", sa.String, nullable=False),
        sa.Column("source_name", sa.String, nullable=False),
        sa.Column("source_key", sa.String, nullable=False),
        sa.Column("raw_title", sa.Text, nullable=False),
        sa.Column("raw_category", sa.String),
        sa.Column("file_size_bytes", sa.BigInteger),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("date", sa.Date),
        sa.Column("quality", sa.String),
        sa.Column("content_type", sa.String),
        sa.Column("season", sa.Integer),
        sa.Column("episode", sa.Integer),
        sa.Column("hints", JSONB),
        sa.Column("enricher", sa.String),
        sa.Column("metadata_status", sa.String),
        sa.Column("metadata_score", sa.Float),
        sa.Column("matched_at", sa.DateTime(timezone=True)),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("source_key", name="uq_releases_source_key"),
    )
    op.create_index("ix_releases_published_at", "releases", ["published_at"])
    op.create_index("ix_releases_content_type", "releases", ["content_type"])
    op.create_index("ix_releases_metadata_status", "releases", ["metadata_status"])

    op.create_table(
        "usenet_releases",
        sa.Column(
            "release_id",
            UUID(as_uuid=True),
            sa.ForeignKey("releases.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("groups", sa.Text),
        sa.Column("poster", sa.Text),
        sa.Column("nzb_xml", sa.LargeBinary, nullable=False),
    )

    op.create_table(
        "torrent_releases",
        sa.Column(
            "release_id",
            UUID(as_uuid=True),
            sa.ForeignKey("releases.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("info_hash", sa.String(40)),
        sa.Column("magnet_uri", sa.Text),
        sa.Column("size_bytes", sa.BigInteger),
        sa.Column("seeders", sa.Integer),
        sa.Column("leechers", sa.Integer),
    )

    op.create_table(
        "pending_enrichment",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "release_id",
            UUID(as_uuid=True),
            sa.ForeignKey("releases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("enricher", sa.String, nullable=False),
        sa.Column("attempts", sa.Integer, server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_pending_enrichment_next_attempt", "pending_enrichment", ["next_attempt"])

    op.create_table(
        "tmdb_metadata",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tmdb_id", sa.Integer, unique=True, nullable=False),
        sa.Column("imdb_id", sa.String),
        sa.Column("tvdb_id", sa.Integer),
        sa.Column("external_ids", JSONB),
        sa.Column("tmdb_type", sa.String, nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("original_title", sa.Text),
        sa.Column("overview", sa.Text),
        sa.Column("release_year", sa.Integer),
        sa.Column("rating", sa.Float),
        sa.Column("genres", JSONB),
        sa.Column("poster_path", sa.Text),
        sa.Column("backdrop_path", sa.Text),
        sa.Column("extra", JSONB),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_tmdb_metadata_imdb_id", "tmdb_metadata", ["imdb_id"])
    op.create_index("ix_tmdb_metadata_tvdb_id", "tmdb_metadata", ["tvdb_id"])

    op.create_table(
        "release_tmdb_titles",
        sa.Column(
            "release_id",
            UUID(as_uuid=True),
            sa.ForeignKey("releases.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tmdb_id",
            sa.Integer,
            sa.ForeignKey("tmdb_metadata.tmdb_id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "tmdb_people",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tmdb_person_id", sa.Integer, unique=True, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("profile_path", sa.Text),
        sa.Column("popularity", sa.Float),
        sa.Column("imdb_id", sa.String),
        sa.Column("extra", JSONB),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "tmdb_metadata_cast",
        sa.Column(
            "tmdb_metadata_id",
            sa.Integer,
            sa.ForeignKey("tmdb_metadata.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tmdb_person_id",
            sa.Integer,
            sa.ForeignKey("tmdb_people.tmdb_person_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("character", sa.Text),
        sa.Column("cast_order", sa.Integer),
    )

    op.create_table(
        "tpdb_scenes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tpdb_type", sa.String, nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("description", sa.Text),
        sa.Column("date", sa.Date),
        sa.Column("duration_secs", sa.Integer),
        sa.Column(
            "site_id",
            sa.Integer,
            sa.ForeignKey("tpdb_sites.id", ondelete="SET NULL"),
        ),
        sa.Column("performers", JSONB),
        sa.Column("tags", JSONB),
        sa.Column("poster_url", sa.Text),
        sa.Column("background_url", sa.Text),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "release_tpdb_scenes",
        sa.Column(
            "release_id",
            UUID(as_uuid=True),
            sa.ForeignKey("releases.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "scene_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tpdb_scenes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "tpdb_performers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text),
        sa.Column("gender", sa.String),
        sa.Column("birthday", sa.Date),
        sa.Column("height_cm", sa.Integer),
        sa.Column("rating", sa.Float),
        sa.Column("poster_url", sa.Text),
        sa.Column("extra", JSONB),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("tpdb_performers")
    op.drop_table("release_tpdb_scenes")
    op.drop_table("tpdb_scenes")
    op.drop_table("tmdb_metadata_cast")
    op.drop_table("tmdb_people")
    op.drop_table("release_tmdb_titles")
    op.drop_table("tmdb_metadata")
    op.drop_table("pending_enrichment")
    op.drop_table("torrent_releases")
    op.drop_table("usenet_releases")
    op.drop_table("releases")
    op.drop_table("tpdb_sites")
    op.drop_table("tpdb_networks")
    op.drop_table("scan_state")
