"""Live classes and teacher help requests.

Revision ID: 004
Revises: 003
Create Date: 2026-04-07 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, name: str) -> bool:
    insp = inspect(conn)
    return name in insp.get_table_names()


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "aulas_ao_vivo"):
        op.create_table(
            "aulas_ao_vivo",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("professor_id", sa.Integer(), nullable=False),
            sa.Column("turma_id", sa.Integer(), nullable=False),
            sa.Column("disciplina", sa.String(length=50), nullable=False),
            sa.Column("titulo", sa.String(length=150), nullable=False),
            sa.Column("descricao", sa.Text(), nullable=True),
            sa.Column("meeting_provider", sa.String(length=30), nullable=False),
            sa.Column("room_name", sa.String(length=150), nullable=False),
            sa.Column("meeting_url", sa.String(length=500), nullable=False),
            sa.Column("scheduled_at", sa.DateTime(), nullable=False),
            sa.Column("duration_minutes", sa.Integer(), nullable=False),
            sa.Column("ativa", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["professor_id"], ["usuarios.id"]),
            sa.ForeignKeyConstraint(["turma_id"], ["turmas.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_aulas_ao_vivo_id"), "aulas_ao_vivo", ["id"], unique=False)
        op.create_index(op.f("ix_aulas_ao_vivo_professor_id"), "aulas_ao_vivo", ["professor_id"], unique=False)
        op.create_index(op.f("ix_aulas_ao_vivo_turma_id"), "aulas_ao_vivo", ["turma_id"], unique=False)
        op.create_index(op.f("ix_aulas_ao_vivo_scheduled_at"), "aulas_ao_vivo", ["scheduled_at"], unique=False)
        op.create_index(op.f("ix_aulas_ao_vivo_room_name"), "aulas_ao_vivo", ["room_name"], unique=False)

    if not _table_exists(conn, "solicitacoes_professor"):
        op.create_table(
            "solicitacoes_professor",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("requester_user_id", sa.Integer(), nullable=False),
            sa.Column("professor_id", sa.Integer(), nullable=True),
            sa.Column("turma_id", sa.Integer(), nullable=True),
            sa.Column("disciplina", sa.String(length=50), nullable=False),
            sa.Column("assunto", sa.String(length=255), nullable=False),
            sa.Column("requester_role", sa.String(length=30), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("origem", sa.String(length=30), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("responded_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["professor_id"], ["usuarios.id"]),
            sa.ForeignKeyConstraint(["requester_user_id"], ["usuarios.id"]),
            sa.ForeignKeyConstraint(["turma_id"], ["turmas.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_solicitacoes_professor_id"), "solicitacoes_professor", ["id"], unique=False)
        op.create_index(op.f("ix_solicitacoes_professor_requester_user_id"), "solicitacoes_professor", ["requester_user_id"], unique=False)
        op.create_index(op.f("ix_solicitacoes_professor_professor_id"), "solicitacoes_professor", ["professor_id"], unique=False)
        op.create_index(op.f("ix_solicitacoes_professor_turma_id"), "solicitacoes_professor", ["turma_id"], unique=False)
        op.create_index(op.f("ix_solicitacoes_professor_status"), "solicitacoes_professor", ["status"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "solicitacoes_professor"):
        op.drop_table("solicitacoes_professor")
    if _table_exists(conn, "aulas_ao_vivo"):
        op.drop_table("aulas_ao_vivo")
