from datetime import date, datetime
from typing import Optional
import uuid

from sqlalchemy import (
    BigInteger,
    Date,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime


class Base(DeclarativeBase):
    pass


class ScanState(Base):
    __tablename__ = "scan_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    watermark: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Release(Base):
    __tablename__ = "releases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_name: Mapped[str] = mapped_column(String, nullable=False)
    source_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    raw_title: Mapped[str] = mapped_column(Text, nullable=False)
    raw_category: Mapped[Optional[str]] = mapped_column(String)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    date: Mapped[Optional[date]] = mapped_column(Date)
    quality: Mapped[Optional[str]] = mapped_column(String)
    content_type: Mapped[Optional[str]] = mapped_column(String)
    season: Mapped[Optional[int]] = mapped_column(Integer)
    episode: Mapped[Optional[int]] = mapped_column(Integer)
    hints: Mapped[Optional[dict]] = mapped_column(JSONB)
    enricher: Mapped[Optional[str]] = mapped_column(String)
    metadata_status: Mapped[Optional[str]] = mapped_column(String)
    metadata_score: Mapped[Optional[float]] = mapped_column(Float)
    matched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    indexed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    usenet: Mapped[Optional["UsenetRelease"]] = relationship(
        back_populates="release", uselist=False
    )
    torrent: Mapped[Optional["TorrentRelease"]] = relationship(
        back_populates="release", uselist=False
    )
    pending_enrichment: Mapped[list["PendingEnrichment"]] = relationship(
        back_populates="release"
    )
    tmdb_titles: Mapped[list["ReleaseTmdbTitle"]] = relationship(
        back_populates="release"
    )
    tpdb_scenes: Mapped[list["ReleaseTpdbScene"]] = relationship(
        back_populates="release"
    )
    usenet_files: Mapped[list["UsenetFile"]] = relationship(
        back_populates="release"
    )
    torrent_files: Mapped[list["TorrentFile"]] = relationship(
        back_populates="release"
    )


class UsenetRelease(Base):
    __tablename__ = "usenet_releases"

    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("releases.id", ondelete="CASCADE"), primary_key=True
    )
    groups: Mapped[Optional[str]] = mapped_column(Text)
    poster: Mapped[Optional[str]] = mapped_column(Text)
    nzb_xml: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    release: Mapped["Release"] = relationship(back_populates="usenet")


class TorrentRelease(Base):
    __tablename__ = "torrent_releases"

    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("releases.id", ondelete="CASCADE"), primary_key=True
    )
    info_hash: Mapped[Optional[str]] = mapped_column(String(40))
    magnet_uri: Mapped[Optional[str]] = mapped_column(Text)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)
    seeders: Mapped[Optional[int]] = mapped_column(Integer)
    leechers: Mapped[Optional[int]] = mapped_column(Integer)

    release: Mapped["Release"] = relationship(back_populates="torrent")


class PendingEnrichment(Base):
    __tablename__ = "pending_enrichment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("releases.id", ondelete="CASCADE"), nullable=False
    )
    enricher: Mapped[str] = mapped_column(String, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    next_attempt: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    release: Mapped["Release"] = relationship(back_populates="pending_enrichment")


class TmdbMetadata(Base):
    __tablename__ = "tmdb_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tmdb_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    imdb_id: Mapped[Optional[str]] = mapped_column(String)
    tvdb_id: Mapped[Optional[int]] = mapped_column(Integer)
    external_ids: Mapped[Optional[dict]] = mapped_column(JSONB)
    tmdb_type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text)
    original_title: Mapped[Optional[str]] = mapped_column(Text)
    overview: Mapped[Optional[str]] = mapped_column(Text)
    release_year: Mapped[Optional[int]] = mapped_column(Integer)
    rating: Mapped[Optional[float]] = mapped_column(Float)
    genres: Mapped[Optional[dict]] = mapped_column(JSONB)
    poster_path: Mapped[Optional[str]] = mapped_column(Text)
    backdrop_path: Mapped[Optional[str]] = mapped_column(Text)
    extra: Mapped[Optional[dict]] = mapped_column(JSONB)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    releases: Mapped[list["ReleaseTmdbTitle"]] = relationship(back_populates="tmdb_metadata")
    cast: Mapped[list["TmdbMetadataCast"]] = relationship(back_populates="tmdb_metadata")


class ReleaseTmdbTitle(Base):
    __tablename__ = "release_tmdb_titles"

    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("releases.id", ondelete="CASCADE"), primary_key=True
    )
    tmdb_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tmdb_metadata.tmdb_id", ondelete="CASCADE"), primary_key=True
    )

    release: Mapped["Release"] = relationship(back_populates="tmdb_titles")
    tmdb_metadata: Mapped["TmdbMetadata"] = relationship(back_populates="releases")


class TmdbPerson(Base):
    __tablename__ = "tmdb_people"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tmdb_person_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    profile_path: Mapped[Optional[str]] = mapped_column(Text)
    popularity: Mapped[Optional[float]] = mapped_column(Float)
    imdb_id: Mapped[Optional[str]] = mapped_column(String)
    extra: Mapped[Optional[dict]] = mapped_column(JSONB)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    cast_entries: Mapped[list["TmdbMetadataCast"]] = relationship(back_populates="person")


class TmdbMetadataCast(Base):
    __tablename__ = "tmdb_metadata_cast"

    tmdb_metadata_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tmdb_metadata.id", ondelete="CASCADE"), primary_key=True
    )
    tmdb_person_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tmdb_people.tmdb_person_id", ondelete="CASCADE"), primary_key=True
    )
    character: Mapped[Optional[str]] = mapped_column(Text)
    cast_order: Mapped[Optional[int]] = mapped_column(Integer)

    tmdb_metadata: Mapped["TmdbMetadata"] = relationship(back_populates="cast")
    person: Mapped["TmdbPerson"] = relationship(back_populates="cast_entries")


class TpdbNetwork(Base):
    __tablename__ = "tpdb_networks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(Text)
    slug: Mapped[Optional[str]] = mapped_column(String)

    sites: Mapped[list["TpdbSite"]] = relationship(back_populates="network")


class TpdbSite(Base):
    __tablename__ = "tpdb_sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(Text)
    network_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tpdb_networks.id", ondelete="SET NULL")
    )
    slug: Mapped[Optional[str]] = mapped_column(String)
    logo_url: Mapped[Optional[str]] = mapped_column(Text)

    network: Mapped[Optional["TpdbNetwork"]] = relationship(back_populates="sites")
    scenes: Mapped[list["TpdbScene"]] = relationship(back_populates="site")


class TpdbScene(Base):
    __tablename__ = "tpdb_scenes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tpdb_type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text)
    description: Mapped[Optional[str]] = mapped_column(Text)
    date: Mapped[Optional[date]] = mapped_column(Date)
    duration_secs: Mapped[Optional[int]] = mapped_column(Integer)
    site_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("tpdb_sites.id", ondelete="SET NULL")
    )
    performers: Mapped[Optional[dict]] = mapped_column(JSONB)
    tags: Mapped[Optional[dict]] = mapped_column(JSONB)
    poster_url: Mapped[Optional[str]] = mapped_column(Text)
    background_url: Mapped[Optional[str]] = mapped_column(Text)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    site: Mapped[Optional["TpdbSite"]] = relationship(back_populates="scenes")
    releases: Mapped[list["ReleaseTpdbScene"]] = relationship(back_populates="scene")


class ReleaseTpdbScene(Base):
    __tablename__ = "release_tpdb_scenes"

    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("releases.id", ondelete="CASCADE"), primary_key=True
    )
    scene_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tpdb_scenes.id", ondelete="CASCADE"), primary_key=True
    )

    release: Mapped["Release"] = relationship(back_populates="tpdb_scenes")
    scene: Mapped["TpdbScene"] = relationship(back_populates="releases")


class UsenetFile(Base):
    __tablename__ = "usenet_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("releases.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_index: Mapped[int] = mapped_column(Integer, nullable=False)
    segment_ids: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("release_id", "filename", name="uq_usenet_files_release_filename"),
    )

    release: Mapped["Release"] = relationship(back_populates="usenet_files")


class TorrentFile(Base):
    __tablename__ = "torrent_files"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    release_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("releases.id", ondelete="CASCADE"), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_index: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )

    __table_args__ = (
        UniqueConstraint("release_id", "file_index", name="uq_torrent_files_release_index"),
    )

    release: Mapped["Release"] = relationship(back_populates="torrent_files")


class TpdbPerformer(Base):
    __tablename__ = "tpdb_performers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(Text)
    gender: Mapped[Optional[str]] = mapped_column(String)
    birthday: Mapped[Optional[date]] = mapped_column(Date)
    height_cm: Mapped[Optional[int]] = mapped_column(Integer)
    rating: Mapped[Optional[float]] = mapped_column(Float)
    poster_url: Mapped[Optional[str]] = mapped_column(Text)
    extra: Mapped[Optional[dict]] = mapped_column(JSONB)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
