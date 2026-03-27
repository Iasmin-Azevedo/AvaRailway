"""Chatbot module tables.

Revision ID: 003
Revises: 002
Create Date: 2026-03-27 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, name: str) -> bool:
    insp = inspect(conn)
    return name in insp.get_table_names()


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "chat_sessions"):
        op.create_table(
            "chat_sessions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("perfil", sa.String(length=30), nullable=False),
            sa.Column("titulo", sa.String(length=150), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["usuarios.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_chat_sessions_user_id"), "chat_sessions", ["user_id"], unique=False)
        op.create_index(op.f("ix_chat_sessions_perfil"), "chat_sessions", ["perfil"], unique=False)
        op.create_index(op.f("ix_chat_sessions_status"), "chat_sessions", ["status"], unique=False)

    if not _table_exists(conn, "chat_messages"):
        op.create_table(
            "chat_messages",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("sender", sa.String(length=20), nullable=False),
            sa.Column("message_text", sa.Text(), nullable=False),
            sa.Column("message_type", sa.String(length=40), nullable=False),
            sa.Column("context_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_chat_messages_session_id"), "chat_messages", ["session_id"], unique=False)

    if not _table_exists(conn, "chat_memories"):
        op.create_table(
            "chat_memories",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("summary_text", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_chat_memories_session_id"), "chat_memories", ["session_id"], unique=False)

    if not _table_exists(conn, "chat_feedbacks"):
        op.create_table(
            "chat_feedbacks",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("message_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("rating", sa.String(length=20), nullable=False),
            sa.Column("comment", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"]),
            sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["usuarios.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_chat_feedbacks_session_id"), "chat_feedbacks", ["session_id"], unique=False)
        op.create_index(op.f("ix_chat_feedbacks_message_id"), "chat_feedbacks", ["message_id"], unique=False)
        op.create_index(op.f("ix_chat_feedbacks_user_id"), "chat_feedbacks", ["user_id"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "chat_feedbacks"):
        op.drop_table("chat_feedbacks")
    if _table_exists(conn, "chat_memories"):
        op.drop_table("chat_memories")
    if _table_exists(conn, "chat_messages"):
        op.drop_table("chat_messages")
    if _table_exists(conn, "chat_sessions"):
        op.drop_table("chat_sessions")
