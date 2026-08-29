"""add immersive learning domain tables

Revision ID: 6a1b2c3d4e5f
Revises: 5e7f8a9b0c12
Create Date: 2026-08-29

Immersive Learning / Media Learning Engine (EPIC-ML-01): MediaAsset, Transcript,
TranscriptSegment, LearningUnit (+ occurrence edges), MediaSession, and a short-
retention media_telemetry_events plane (NOT learning_events).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6a1b2c3d4e5f"
down_revision: Union[str, Sequence[str], None] = "5e7f8a9b0c12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _jsonb_default() -> sa.TextClause:
    return sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("owner_student_id", sa.UUID(), nullable=False),
        sa.Column("media_type", sa.String(length=16), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("storage_ref", sa.String(length=500), nullable=True),
        sa.Column("external_ref", sa.String(length=500), nullable=True),
        sa.Column(
            "content_provenance",
            sa.String(length=32),
            server_default="USER_UPLOADED",
            nullable=False,
        ),
        sa.Column(
            "processing_state",
            sa.String(length=32),
            server_default="READY",
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=_jsonb_default(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["owner_student_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_media_assets_owner_student_id", "media_assets", ["owner_student_id"]
    )

    op.create_table(
        "transcripts",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("media_id", sa.UUID(), nullable=False),
        sa.Column(
            "role", sa.String(length=16), server_default="PRIMARY", nullable=False
        ),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("model_version", sa.String(length=120), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "provenance",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=_jsonb_default(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["media_id"], ["media_assets.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transcripts_media_id", "transcripts", ["media_id"])

    op.create_table(
        "transcript_segments",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("transcript_id", sa.UUID(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=True),
        sa.Column("speaker", sa.String(length=120), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.CheckConstraint("start_ms >= 0", name="ck_transcript_segments_start_ms"),
        sa.CheckConstraint(
            "end_ms > start_ms", name="ck_transcript_segments_end_ms"
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id"], ["transcripts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "transcript_id",
            "order_index",
            name="uq_transcript_segments_transcript_order",
        ),
    )
    op.create_index(
        "ix_transcript_segments_transcript_id",
        "transcript_segments",
        ["transcript_id"],
    )

    op.create_table(
        "learning_units",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("stable_key", sa.String(length=200), nullable=False),
        sa.Column("display_text", sa.String(length=500), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=_jsonb_default(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "stable_key", name="uq_learning_units_kind_key"),
    )

    op.create_table(
        "learning_unit_occurrences",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("learning_unit_id", sa.UUID(), nullable=False),
        sa.Column("media_id", sa.UUID(), nullable=False),
        sa.Column("segment_id", sa.UUID(), nullable=False),
        sa.Column("surface_form", sa.String(length=500), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=_jsonb_default(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["learning_unit_id"], ["learning_units.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["media_id"], ["media_assets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"], ["transcript_segments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        # MVP: one occurrence edge per LU×segment; surface_form is descriptive.
        sa.UniqueConstraint(
            "learning_unit_id",
            "segment_id",
            name="uq_learning_unit_occurrences_lu_segment",
        ),
    )
    op.create_index(
        "ix_learning_unit_occurrences_media_id",
        "learning_unit_occurrences",
        ["media_id"],
    )
    op.create_index(
        "ix_learning_unit_occurrences_learning_unit_id",
        "learning_unit_occurrences",
        ["learning_unit_id"],
    )
    op.create_index(
        "ix_learning_unit_occurrences_segment_id",
        "learning_unit_occurrences",
        ["segment_id"],
    )

    op.create_table(
        "media_sessions",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("media_id", sa.UUID(), nullable=False),
        sa.Column(
            "playhead_ms", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("current_segment_id", sa.UUID(), nullable=True),
        sa.Column(
            "scaffold_level", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "state", sa.String(length=32), server_default="ACTIVE", nullable=False
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=_jsonb_default(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["media_id"], ["media_assets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["current_segment_id"],
            ["transcript_segments.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_media_sessions_student_id", "media_sessions", ["student_id"])
    op.create_index("ix_media_sessions_media_id", "media_sessions", ["media_id"])

    op.create_table(
        "media_telemetry_events",
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("media_id", sa.UUID(), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=_jsonb_default(),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_media_telemetry_events_student_occurred",
        "media_telemetry_events",
        ["student_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_media_telemetry_events_student_occurred",
        table_name="media_telemetry_events",
    )
    op.drop_table("media_telemetry_events")

    op.drop_index("ix_media_sessions_media_id", table_name="media_sessions")
    op.drop_index("ix_media_sessions_student_id", table_name="media_sessions")
    op.drop_table("media_sessions")

    op.drop_index(
        "ix_learning_unit_occurrences_segment_id",
        table_name="learning_unit_occurrences",
    )
    op.drop_index(
        "ix_learning_unit_occurrences_learning_unit_id",
        table_name="learning_unit_occurrences",
    )
    op.drop_index(
        "ix_learning_unit_occurrences_media_id",
        table_name="learning_unit_occurrences",
    )
    op.drop_table("learning_unit_occurrences")

    op.drop_table("learning_units")

    op.drop_index(
        "ix_transcript_segments_transcript_id", table_name="transcript_segments"
    )
    op.drop_table("transcript_segments")

    op.drop_index("ix_transcripts_media_id", table_name="transcripts")
    op.drop_table("transcripts")

    op.drop_index("ix_media_assets_owner_student_id", table_name="media_assets")
    op.drop_table("media_assets")
