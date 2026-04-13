"""Medalhas com tipos, envios do professor e mural do aluno.

Revision ID: 007
Revises: 006
Create Date: 2026-04-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, name: str) -> bool:
    insp = inspect(conn)
    return name in insp.get_table_names()


def upgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, "medalha_tipos"):
        op.create_table(
            "medalha_tipos",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("nome", sa.String(length=120), nullable=False),
            sa.Column("slug", sa.String(length=120), nullable=False),
            sa.Column("icone", sa.String(length=80), nullable=False, server_default="fa-solid fa-medal"),
            sa.Column("cor", sa.String(length=30), nullable=False, server_default="warning"),
            sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("ordem", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug", name="uq_medalha_tipos_slug"),
        )
        op.create_index("ix_medalha_tipos_ativo", "medalha_tipos", ["ativo"], unique=False)
        op.create_index("ix_medalha_tipos_ordem", "medalha_tipos", ["ordem"], unique=False)

    if not _table_exists(conn, "professor_medalha_envios"):
        op.create_table(
            "professor_medalha_envios",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("professor_usuario_id", sa.Integer(), nullable=False),
            sa.Column("turma_id", sa.Integer(), nullable=True),
            sa.Column("medalha_tipo_id", sa.Integer(), nullable=False),
            sa.Column("mensagem", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["professor_usuario_id"], ["usuarios.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["turma_id"], ["turmas.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["medalha_tipo_id"], ["medalha_tipos.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_prof_med_env_professor",
            "professor_medalha_envios",
            ["professor_usuario_id"],
            unique=False,
        )
        op.create_index(
            "ix_prof_med_env_turma",
            "professor_medalha_envios",
            ["turma_id"],
            unique=False,
        )
        op.create_index(
            "ix_prof_med_env_tipo",
            "professor_medalha_envios",
            ["medalha_tipo_id"],
            unique=False,
        )
        op.create_index(
            "ix_prof_med_env_created_at",
            "professor_medalha_envios",
            ["created_at"],
            unique=False,
        )

    if not _table_exists(conn, "aluno_medalhas"):
        op.create_table(
            "aluno_medalhas",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("aluno_id", sa.Integer(), nullable=False),
            sa.Column("envio_id", sa.Integer(), nullable=False),
            sa.Column("medalha_tipo_id", sa.Integer(), nullable=False),
            sa.Column("concedida_em", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["aluno_id"], ["alunos.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["envio_id"], ["professor_medalha_envios.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["medalha_tipo_id"], ["medalha_tipos.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("aluno_id", "envio_id", name="uq_aluno_medalha_aluno_envio"),
        )
        op.create_index("ix_aluno_medalhas_aluno", "aluno_medalhas", ["aluno_id"], unique=False)
        op.create_index("ix_aluno_medalhas_envio", "aluno_medalhas", ["envio_id"], unique=False)
        op.create_index("ix_aluno_medalhas_tipo", "aluno_medalhas", ["medalha_tipo_id"], unique=False)
        op.create_index("ix_aluno_medalhas_concedida", "aluno_medalhas", ["concedida_em"], unique=False)


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "aluno_medalhas"):
        op.drop_table("aluno_medalhas")
    if _table_exists(conn, "professor_medalha_envios"):
        op.drop_table("professor_medalha_envios")
    if _table_exists(conn, "medalha_tipos"):
        op.drop_table("medalha_tipos")
