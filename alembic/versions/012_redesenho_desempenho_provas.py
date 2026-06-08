"""Redesenho da avaliacao institucional por desempenho.

Revision ID: 012
Revises: 011
Create Date: 2026-05-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, name: str) -> bool:
    return name in inspect(conn).get_table_names()


def _column_exists(conn, table_name: str, column_name: str) -> bool:
    if not _table_exists(conn, table_name):
        return False
    return any(col["name"] == column_name for col in inspect(conn).get_columns(table_name))


def upgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, "avaliacoes"):
        with op.batch_alter_table("avaliacoes") as batch_op:
            if not _column_exists(conn, "avaliacoes", "curso_id"):
                batch_op.add_column(sa.Column("curso_id", sa.Integer(), nullable=True))
            if not _column_exists(conn, "avaliacoes", "ano_escolar"):
                batch_op.add_column(sa.Column("ano_escolar", sa.Integer(), nullable=True))
            if not _column_exists(conn, "avaliacoes", "criado_por_usuario_id"):
                batch_op.add_column(sa.Column("criado_por_usuario_id", sa.Integer(), nullable=True))

    if not _table_exists(conn, "banco_questoes"):
        op.create_table(
            "banco_questoes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("codigo_referencia", sa.String(length=40), nullable=True),
            sa.Column("autor_usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("curso_id", sa.Integer(), sa.ForeignKey("cursos.id"), nullable=True),
            sa.Column("ano_escolar", sa.Integer(), nullable=True),
            sa.Column("descritor_id", sa.Integer(), sa.ForeignKey("saeb_descritores.id"), nullable=True),
            sa.Column("origem", sa.String(length=40), nullable=False, server_default="manual"),
            sa.Column("enunciado", sa.Text(), nullable=False),
            sa.Column("alternativa_a", sa.String(length=200), nullable=False),
            sa.Column("alternativa_b", sa.String(length=200), nullable=False),
            sa.Column("alternativa_c", sa.String(length=200), nullable=False),
            sa.Column("alternativa_d", sa.String(length=200), nullable=False),
            sa.Column("gabarito", sa.String(length=1), nullable=False),
            sa.Column("habilidade_saeb", sa.String(length=10), nullable=True),
            sa.Column("observacoes", sa.Text(), nullable=True),
            sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if _table_exists(conn, "questoes_prova"):
        with op.batch_alter_table("questoes_prova") as batch_op:
            if not _column_exists(conn, "questoes_prova", "banco_questao_id"):
                batch_op.add_column(sa.Column("banco_questao_id", sa.Integer(), nullable=True))
            if not _column_exists(conn, "questoes_prova", "curso_id"):
                batch_op.add_column(sa.Column("curso_id", sa.Integer(), nullable=True))
            if not _column_exists(conn, "questoes_prova", "ano_escolar"):
                batch_op.add_column(sa.Column("ano_escolar", sa.Integer(), nullable=True))
            if not _column_exists(conn, "questoes_prova", "descritor_id"):
                batch_op.add_column(sa.Column("descritor_id", sa.Integer(), nullable=True))
            if not _column_exists(conn, "questoes_prova", "origem"):
                batch_op.add_column(sa.Column("origem", sa.String(length=40), nullable=True))

    if not _table_exists(conn, "aplicacoes_prova"):
        op.create_table(
            "aplicacoes_prova",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("avaliacao_id", sa.Integer(), sa.ForeignKey("avaliacoes.id"), nullable=False),
            sa.Column("titulo", sa.String(length=160), nullable=True),
            sa.Column("escopo", sa.String(length=40), nullable=False, server_default="turma"),
            sa.Column("ano_letivo", sa.String(length=20), nullable=True),
            sa.Column("periodo_referencia", sa.String(length=40), nullable=True),
            sa.Column("turma_id", sa.Integer(), sa.ForeignKey("turmas.id"), nullable=True),
            sa.Column("escola_id", sa.Integer(), sa.ForeignKey("escolas.id"), nullable=True),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="planejada"),
            sa.Column("data_aplicacao", sa.DateTime(), nullable=True),
            sa.Column("observacoes", sa.Text(), nullable=True),
            sa.Column("criado_por_usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if not _table_exists(conn, "participacoes_aplicacao_prova"):
        op.create_table(
            "participacoes_aplicacao_prova",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("aplicacao_id", sa.Integer(), sa.ForeignKey("aplicacoes_prova.id"), nullable=False),
            sa.Column("aluno_id", sa.Integer(), sa.ForeignKey("alunos.id"), nullable=False),
            sa.Column("turma_id_snapshot", sa.Integer(), sa.ForeignKey("turmas.id"), nullable=True),
            sa.Column("escola_id_snapshot", sa.Integer(), sa.ForeignKey("escolas.id"), nullable=True),
            sa.Column("presente", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("total_questoes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_acertos", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("nota", sa.Float(), nullable=True),
            sa.Column("processado_em", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("aplicacao_id", "aluno_id", name="uq_participacao_aplicacao_aluno"),
        )

    if _table_exists(conn, "respostas_alunos"):
        with op.batch_alter_table("respostas_alunos") as batch_op:
            if not _column_exists(conn, "respostas_alunos", "aplicacao_id"):
                batch_op.add_column(sa.Column("aplicacao_id", sa.Integer(), nullable=True))
            if not _column_exists(conn, "respostas_alunos", "participacao_id"):
                batch_op.add_column(sa.Column("participacao_id", sa.Integer(), nullable=True))

    if _table_exists(conn, "lotes_importacao_gabarito"):
        with op.batch_alter_table("lotes_importacao_gabarito") as batch_op:
            if not _column_exists(conn, "lotes_importacao_gabarito", "aplicacao_id"):
                batch_op.add_column(sa.Column("aplicacao_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, "participacoes_aplicacao_prova"):
        op.drop_table("participacoes_aplicacao_prova")
    if _table_exists(conn, "aplicacoes_prova"):
        op.drop_table("aplicacoes_prova")
    if _table_exists(conn, "banco_questoes"):
        op.drop_table("banco_questoes")
