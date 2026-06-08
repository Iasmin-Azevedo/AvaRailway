"""Adequações integradas da licitação.

Revision ID: 011
Revises: 010
Create Date: 2026-05-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "011"
down_revision: Union[str, None] = "010"
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

    if _table_exists(conn, "usuarios"):
        with op.batch_alter_table("usuarios") as batch_op:
            if not _column_exists(conn, "usuarios", "funcao_docente"):
                batch_op.add_column(sa.Column("funcao_docente", sa.String(length=40), nullable=True))
            if not _column_exists(conn, "usuarios", "escopo_administrativo"):
                batch_op.add_column(sa.Column("escopo_administrativo", sa.String(length=40), nullable=True))

    if _table_exists(conn, "auditoria_logs"):
        with op.batch_alter_table("auditoria_logs") as batch_op:
            if not _column_exists(conn, "auditoria_logs", "categoria"):
                batch_op.add_column(sa.Column("categoria", sa.String(length=50), nullable=True))
            if not _column_exists(conn, "auditoria_logs", "entidade"):
                batch_op.add_column(sa.Column("entidade", sa.String(length=80), nullable=True))
            if not _column_exists(conn, "auditoria_logs", "entidade_id"):
                batch_op.add_column(sa.Column("entidade_id", sa.Integer(), nullable=True))

    if _table_exists(conn, "avaliacoes"):
        with op.batch_alter_table("avaliacoes") as batch_op:
            if not _column_exists(conn, "avaliacoes", "codigo"):
                batch_op.add_column(sa.Column("codigo", sa.String(length=40), nullable=True))
            if not _column_exists(conn, "avaliacoes", "tipo"):
                batch_op.add_column(sa.Column("tipo", sa.String(length=30), nullable=False, server_default="objetiva"))
            if not _column_exists(conn, "avaliacoes", "status"):
                batch_op.add_column(sa.Column("status", sa.String(length=30), nullable=False, server_default="rascunho"))
            if not _column_exists(conn, "avaliacoes", "ano_letivo"):
                batch_op.add_column(sa.Column("ano_letivo", sa.String(length=20), nullable=True))
            if not _column_exists(conn, "avaliacoes", "escopo"):
                batch_op.add_column(sa.Column("escopo", sa.String(length=40), nullable=True))

    if _table_exists(conn, "questoes_prova"):
        with op.batch_alter_table("questoes_prova") as batch_op:
            if not _column_exists(conn, "questoes_prova", "codigo"):
                batch_op.add_column(sa.Column("codigo", sa.String(length=40), nullable=True))
            if not _column_exists(conn, "questoes_prova", "numero"):
                batch_op.add_column(sa.Column("numero", sa.Integer(), nullable=True))
            if not _column_exists(conn, "questoes_prova", "disciplina"):
                batch_op.add_column(sa.Column("disciplina", sa.String(length=50), nullable=True))
            if not _column_exists(conn, "questoes_prova", "peso"):
                batch_op.add_column(sa.Column("peso", sa.Float(), nullable=True, server_default="1"))
            if not _column_exists(conn, "questoes_prova", "ativa"):
                batch_op.add_column(sa.Column("ativa", sa.Boolean(), nullable=False, server_default=sa.text("1")))

    if _table_exists(conn, "respostas_alunos"):
        with op.batch_alter_table("respostas_alunos") as batch_op:
            if not _column_exists(conn, "respostas_alunos", "lote_importacao_id"):
                batch_op.add_column(sa.Column("lote_importacao_id", sa.Integer(), nullable=True))
            if not _column_exists(conn, "respostas_alunos", "pontuacao"):
                batch_op.add_column(sa.Column("pontuacao", sa.Float(), nullable=True))
            if not _column_exists(conn, "respostas_alunos", "processado_em"):
                batch_op.add_column(sa.Column("processado_em", sa.DateTime(), nullable=True))

    if not _table_exists(conn, "lotes_importacao_gabarito"):
        op.create_table(
            "lotes_importacao_gabarito",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("avaliacao_id", sa.Integer(), sa.ForeignKey("avaliacoes.id"), nullable=False),
            sa.Column("arquivo_nome", sa.String(length=255), nullable=False),
            sa.Column("linhas_processadas", sa.Integer(), nullable=True),
            sa.Column("linhas_com_erro", sa.Integer(), nullable=True),
            sa.Column("resumo_processamento", sa.Text(), nullable=True),
            sa.Column("criado_por_usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if not _table_exists(conn, "ciclos_avaliacao_semestral"):
        op.create_table(
            "ciclos_avaliacao_semestral",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("titulo", sa.String(length=160), nullable=False),
            sa.Column("ano_letivo", sa.String(length=20), nullable=False),
            sa.Column("semestre", sa.String(length=20), nullable=False),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="planejado"),
            sa.Column("data_inicio", sa.DateTime(), nullable=True),
            sa.Column("data_fim", sa.DateTime(), nullable=True),
            sa.Column("criado_por_usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if not _table_exists(conn, "instrumentos_avaliacao_institucional"):
        op.create_table(
            "instrumentos_avaliacao_institucional",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("ciclo_id", sa.Integer(), sa.ForeignKey("ciclos_avaliacao_semestral.id"), nullable=True),
            sa.Column("nome", sa.String(length=160), nullable=False),
            sa.Column("descricao", sa.Text(), nullable=True),
            sa.Column("perfil_avaliado", sa.String(length=40), nullable=False),
            sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if not _table_exists(conn, "criterios_avaliacao_institucional"):
        op.create_table(
            "criterios_avaliacao_institucional",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("instrumento_id", sa.Integer(), sa.ForeignKey("instrumentos_avaliacao_institucional.id"), nullable=False),
            sa.Column("titulo", sa.String(length=160), nullable=False),
            sa.Column("descricao", sa.Text(), nullable=True),
            sa.Column("peso", sa.Float(), nullable=False, server_default="1"),
            sa.Column("ordem", sa.Integer(), nullable=False, server_default="0"),
        )

    if not _table_exists(conn, "aplicacoes_avaliacao_institucional"):
        op.create_table(
            "aplicacoes_avaliacao_institucional",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("ciclo_id", sa.Integer(), sa.ForeignKey("ciclos_avaliacao_semestral.id"), nullable=False),
            sa.Column("instrumento_id", sa.Integer(), sa.ForeignKey("instrumentos_avaliacao_institucional.id"), nullable=False),
            sa.Column("escola_id", sa.Integer(), sa.ForeignKey("escolas.id"), nullable=True),
            sa.Column("avaliado_usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
            sa.Column("respondente_usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=True),
            sa.Column("status", sa.String(length=30), nullable=False, server_default="aberta"),
            sa.Column("nota_final", sa.Float(), nullable=True),
            sa.Column("devolutiva_resumo", sa.Text(), nullable=True),
            sa.Column("observacoes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    if not _table_exists(conn, "respostas_avaliacao_institucional"):
        op.create_table(
            "respostas_avaliacao_institucional",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("aplicacao_id", sa.Integer(), sa.ForeignKey("aplicacoes_avaliacao_institucional.id"), nullable=False),
            sa.Column("criterio_id", sa.Integer(), sa.ForeignKey("criterios_avaliacao_institucional.id"), nullable=False),
            sa.Column("nota", sa.Float(), nullable=False),
            sa.Column("comentario", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if not _table_exists(conn, "programas_formacao_bncc"):
        op.create_table(
            "programas_formacao_bncc",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("nome", sa.String(length=180), nullable=False),
            sa.Column("descricao", sa.Text(), nullable=True),
            sa.Column("tema", sa.String(length=180), nullable=False, server_default="BNCC Computacao"),
            sa.Column("carga_horaria_total", sa.Integer(), nullable=False, server_default="80"),
            sa.Column("carga_horaria_presencial", sa.Integer(), nullable=False, server_default="40"),
            sa.Column("carga_horaria_remota", sa.Integer(), nullable=False, server_default="40"),
            sa.Column("publico_alvo", sa.String(length=255), nullable=True),
            sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if not _table_exists(conn, "programas_formacao_recursos"):
        op.create_table(
            "programas_formacao_recursos",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("programa_id", sa.Integer(), sa.ForeignKey("programas_formacao_bncc.id"), nullable=False),
            sa.Column("tipo_recurso", sa.String(length=40), nullable=False),
            sa.Column("trilha_id", sa.Integer(), sa.ForeignKey("trilhas.id"), nullable=True),
            sa.Column("moodle_course_id", sa.Integer(), nullable=True),
            sa.Column("titulo", sa.String(length=180), nullable=False),
            sa.Column("descricao", sa.Text(), nullable=True),
        )

    if not _table_exists(conn, "turmas_formacao_bncc"):
        op.create_table(
            "turmas_formacao_bncc",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("programa_id", sa.Integer(), sa.ForeignKey("programas_formacao_bncc.id"), nullable=False),
            sa.Column("nome", sa.String(length=160), nullable=False),
            sa.Column("escola_id", sa.Integer(), sa.ForeignKey("escolas.id"), nullable=True),
            sa.Column("limite_participantes", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("data_inicio", sa.DateTime(), nullable=True),
            sa.Column("data_fim", sa.DateTime(), nullable=True),
            sa.Column("observacoes", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if not _table_exists(conn, "participantes_turma_formacao_bncc"):
        op.create_table(
            "participantes_turma_formacao_bncc",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("turma_id", sa.Integer(), sa.ForeignKey("turmas_formacao_bncc.id"), nullable=False),
            sa.Column("usuario_id", sa.Integer(), sa.ForeignKey("usuarios.id"), nullable=False),
            sa.Column("papel_participante", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False, server_default="inscrito"),
            sa.Column("carga_horaria_remota_realizada", sa.Float(), nullable=False, server_default="0"),
            sa.Column("carga_horaria_presencial_realizada", sa.Float(), nullable=False, server_default="0"),
            sa.Column("devolutiva", sa.Text(), nullable=True),
            sa.Column("certificado_emitido", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    if not _table_exists(conn, "encontros_presenciais_formacao_bncc"):
        op.create_table(
            "encontros_presenciais_formacao_bncc",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("turma_id", sa.Integer(), sa.ForeignKey("turmas_formacao_bncc.id"), nullable=False),
            sa.Column("titulo", sa.String(length=180), nullable=False),
            sa.Column("data_encontro", sa.DateTime(), nullable=False),
            sa.Column("carga_horaria", sa.Float(), nullable=False, server_default="4"),
            sa.Column("local", sa.String(length=255), nullable=True),
            sa.Column("descricao", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()
    for table_name in [
        "encontros_presenciais_formacao_bncc",
        "participantes_turma_formacao_bncc",
        "turmas_formacao_bncc",
        "programas_formacao_recursos",
        "programas_formacao_bncc",
        "respostas_avaliacao_institucional",
        "aplicacoes_avaliacao_institucional",
        "criterios_avaliacao_institucional",
        "instrumentos_avaliacao_institucional",
        "ciclos_avaliacao_semestral",
        "lotes_importacao_gabarito",
    ]:
        if _table_exists(conn, table_name):
            op.drop_table(table_name)
