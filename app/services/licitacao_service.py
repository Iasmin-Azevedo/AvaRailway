from __future__ import annotations

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.aluno import Aluno
from app.models.avaliacao import AplicacaoProva, Avaliacao, BancoQuestao
from app.models.formacao import ParticipanteTurmaFormacaoBNCC, ProgramaFormacaoBNCC, TurmaFormacaoBNCC
from app.models.gestao import Escola, Turma
from app.models.h5p import AtividadeH5P, ProgressoH5P
from app.models.relacoes import ProfessorTurma
from app.models.user import AdminScope, AuditLog, TeacherRole, UserRole, Usuario
from app.services.avaliacao_service import AvaliacaoService
from app.services.descriptor_performance_service import DescriptorPerformanceService


class LicitacaoService:
    def __init__(self) -> None:
        self.avaliacao_service = AvaliacaoService()

    def get_sme_dashboard(self, db: Session) -> dict:
        programas_ativos = db.query(ProgramaFormacaoBNCC).filter(ProgramaFormacaoBNCC.ativo.is_(True)).count()
        turmas_formacao = db.query(TurmaFormacaoBNCC).count()
        participantes_formacao = db.query(ParticipanteTurmaFormacaoBNCC).count()
        avaliacoes_objetivas = db.query(Avaliacao).filter(
            or_(Avaliacao.tipo.is_(None), Avaliacao.tipo == "objetiva")
        ).count()
        banco_questoes = db.query(BancoQuestao).filter(BancoQuestao.ativo.is_(True)).count()
        aplicacoes_prova = db.query(AplicacaoProva).count()
        total_logs = db.query(AuditLog).count()
        consolidado = self.avaliacao_service.consolidado_desempenho(db)
        pdt_count = (
            db.query(Usuario)
            .filter(
                Usuario.role == UserRole.PROFESSOR,
                Usuario.funcao_docente == TeacherRole.PDT,
                Usuario.ativo.is_(True),
            )
            .count()
        )
        secretaria_count = (
            db.query(Usuario)
            .filter(
                Usuario.role == UserRole.ADMIN,
                Usuario.escopo_administrativo == AdminScope.SECRETARIA_SME,
                Usuario.ativo.is_(True),
            )
            .count()
        )
        return {
            "n_escolas": db.query(Escola).filter(Escola.ativo.is_(True)).count(),
            "n_turmas": db.query(Turma).count(),
            "avaliacoes_objetivas": avaliacoes_objetivas,
            "banco_questoes": banco_questoes,
            "aplicacoes_institucionais": aplicacoes_prova,
            "programas_ativos": programas_ativos,
            "turmas_formacao": turmas_formacao,
            "participantes_formacao": participantes_formacao,
            "participacao_pct": consolidado.get("participacao_pct", 0),
            "nota_rede": consolidado.get("nota_geral", 0),
            "pdt_count": pdt_count,
            "secretaria_count": secretaria_count,
            "total_logs": total_logs,
            "backups_status": "Planejado em rotina operacional",
        }

    def conformidade_snapshot(self, db: Session) -> dict:
        total_logs = db.query(AuditLog).count()
        logins = db.query(AuditLog).filter(AuditLog.acao == "login_sucesso").count()
        return {
            "lgpd": "Acesso por perfil, cookies HttpOnly, auditoria e segregação de escopo por papel.",
            "hospedagem": "Configuração orientada para nuvem com DATABASE_URL, CORS e arquivos H5P/avatars desacoplados.",
            "backup": "Processo de backup e restauração documentado para operação da SME.",
            "auditoria_total": total_logs,
            "logins_sucesso": logins,
            "database_url_masked": "configurado" if settings.DATABASE_URL else "não configurado",
            "cookie_secure": settings.COOKIE_SECURE,
            "origens_permitidas": settings.ALLOWED_ORIGINS,
        }

    def relatorio_sme_rows(self, db: Session, tipo: str) -> tuple[list[str], list[list]]:
        if tipo == "sme_completo":
            headers, rows, _, _ = self.relatorio_sme_completo(db)
            return headers, rows
        if tipo == "avaliacao_institucional":
            rows = self.avaliacao_service.consolidado_desempenho(db)["aplicacoes"]
            return (
                ["aplicacao_id", "prova", "escopo", "escola", "turma", "participantes", "participacao_pct", "nota_media", "status"],
                [
                    [
                        r["aplicacao_id"],
                        r["prova"],
                        r["escopo"],
                        r["escola"],
                        r["turma"],
                        r["participantes"],
                        r["participacao_pct"],
                        r["nota_media"],
                        r["status"],
                    ]
                    for r in rows
                ],
            )
        if tipo == "avaliacao_larga_escala":
            resumo = self.avaliacao_service.resumo_avaliacao_objetiva(db)
            rows = resumo.get("por_turma") or []
            return (
                ["turma", "respostas", "acertos", "nota_media"],
                [
                    [
                        row.get("turma", "Sem turma"),
                        row.get("respostas", row.get("total_respostas", 0)),
                        row.get("acertos", row.get("total_acertos", 0)),
                        row.get("nota_media", row.get("nota", 0)),
                    ]
                    for row in rows
                ],
            )
        if tipo == "avaliacao_por_escola":
            resumo = self.avaliacao_service.resumo_avaliacao_objetiva(db)
            rows = resumo.get("por_escola") or []
            return (
                ["escola", "respostas", "acertos", "nota_media"],
                [
                    [
                        row.get("escola", "Sem escola"),
                        row.get("respostas", row.get("total_respostas", 0)),
                        row.get("acertos", row.get("total_acertos", 0)),
                        row.get("nota_media", row.get("nota", 0)),
                    ]
                    for row in rows
                ],
            )
        if tipo == "avaliacao_semestral":
            from app.services.avaliacao_institucional_service import AvaliacaoInstitucionalService

            return AvaliacaoInstitucionalService().export_csv_rows(db)
        if tipo == "formacao_bncc":
            rows = (
                db.query(
                    ProgramaFormacaoBNCC.nome,
                    TurmaFormacaoBNCC.nome,
                    func.count(ParticipanteTurmaFormacaoBNCC.id),
                )
                .join(TurmaFormacaoBNCC, TurmaFormacaoBNCC.programa_id == ProgramaFormacaoBNCC.id)
                .outerjoin(
                    ParticipanteTurmaFormacaoBNCC,
                    ParticipanteTurmaFormacaoBNCC.turma_id == TurmaFormacaoBNCC.id,
                )
                .group_by(ProgramaFormacaoBNCC.nome, TurmaFormacaoBNCC.nome)
                .order_by(ProgramaFormacaoBNCC.nome.asc(), TurmaFormacaoBNCC.nome.asc())
                .all()
            )
            return (
                ["programa", "turma", "participantes"],
                [[programa, turma, participantes] for programa, turma, participantes in rows],
            )
        raise ValueError("Tipo de relatório SME inválido.")

    def relatorio_sme_completo(self, db: Session) -> tuple[list[str], list[list], list[dict], dict[int, list[dict]]]:
        dsvc = DescriptorPerformanceService()
        resumo = self.avaliacao_service.resumo_avaliacao_objetiva(db)
        nota_por_escola = {
            (row.get("escola") or "").strip().lower(): row.get("nota_media", 0)
            for row in (resumo.get("por_escola") or [])
        }
        nota_por_turma = {
            (row.get("turma") or "").strip().lower(): row.get("nota_media", 0)
            for row in (resumo.get("por_turma") or [])
        }
        escolas = db.query(Escola).filter(Escola.ativo.is_(True)).order_by(Escola.nome.asc()).all()
        engajamento_escolas = {
            int(item["escola_id"]): item for item in dsvc.escolas_engajamento(db, [e.id for e in escolas] if escolas else [])
        }
        cards_escola: list[dict] = []
        turmas_por_escola: dict[int, list[dict]] = {}
        for escola in escolas:
            alunos_ids = dsvc.aluno_ids_for_escolas(db, [escola.id])
            eng = engajamento_escolas.get(escola.id, {})
            cards_escola.append(
                {
                    "escola_id": escola.id,
                    "escola": escola.nome,
                    "qtd_alunos": len(alunos_ids),
                    "engajamento": eng.get("engajamento_pct", 0),
                    "nota_media_provas": nota_por_escola.get((escola.nome or "").strip().lower(), 0),
                }
            )
            turmas = (
                db.query(Turma)
                .filter(Turma.escola_id == escola.id)
                .order_by(Turma.ano_escolar.asc(), Turma.nome.asc())
                .all()
            )
            linhas_turma: list[dict] = []
            for turma in turmas:
                qtd_prof = (
                    db.query(func.count(func.distinct(ProfessorTurma.professor_id)))
                    .filter(ProfessorTurma.turma_id == turma.id)
                    .scalar()
                    or 0
                )
                qtd_alunos = db.query(func.count(Aluno.id)).filter(Aluno.turma_id == turma.id).scalar() or 0
                if qtd_alunos:
                    concluidas = (
                        db.query(func.count(ProgressoH5P.id))
                        .join(Aluno, Aluno.id == ProgressoH5P.aluno_id)
                        .filter(Aluno.turma_id == turma.id, ProgressoH5P.concluido.is_(True))
                        .scalar()
                        or 0
                    )
                    total_atividades = db.query(func.count(AtividadeH5P.id)).filter(AtividadeH5P.ativo.is_(True)).scalar() or 0
                    media_concluidas = (concluidas / max(qtd_alunos, 1)) if qtd_alunos else 0
                    denom = max(total_atividades, 1)
                    eng_turma = round(min(100.0, (media_concluidas / denom) * 100), 1)
                else:
                    eng_turma = 0.0
                nome_turma = turma.nome or f"Turma #{turma.id}"
                linhas_turma.append(
                    {
                        "turma": nome_turma,
                        "qtd_professores": int(qtd_prof),
                        "qtd_alunos": int(qtd_alunos),
                        "engajamento": eng_turma,
                        "nota_media_provas": nota_por_turma.get(nome_turma.strip().lower(), 0),
                    }
                )
            turmas_por_escola[escola.id] = linhas_turma

        headers = ["tipo", "escola", "turma", "qtd_professores", "qtd_alunos", "engajamento", "nota_media_provas"]
        rows: list[list] = []
        for escola in cards_escola:
            rows.append(
                [
                    "resumo_escola",
                    escola["escola"],
                    "",
                    "",
                    escola["qtd_alunos"],
                    escola["engajamento"],
                    escola["nota_media_provas"],
                ]
            )
            for turma in turmas_por_escola.get(escola["escola_id"], []):
                rows.append(
                    [
                        "detalhe_turma",
                        escola["escola"],
                        turma["turma"],
                        turma["qtd_professores"],
                        turma["qtd_alunos"],
                        turma["engajamento"],
                        turma["nota_media_provas"],
                    ]
                )
        return headers, rows, cards_escola, turmas_por_escola
