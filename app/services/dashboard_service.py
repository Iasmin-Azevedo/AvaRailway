from sqlalchemy.orm import Session

from app.models.gestao import Escola, Turma
from app.models.aluno import Aluno, PontuacaoGamificacao
from app.models.h5p import ProgressoH5P, AtividadeH5P
from app.models.user import Usuario, UserRole
from app.models.resposta import RespostaAluno
from app.core.gamification_rules import get_level_progress as get_level_progress_by_rules


class DashboardService:
    @staticmethod
    def get_level_progress(xp_total: int) -> dict:
        return get_level_progress_by_rules(xp_total)

    def get_gestor_stats(self, db: Session) -> dict:
        n_escolas = db.query(Escola).filter(Escola.ativo == True).count()
        n_turmas = db.query(Turma).count()
        n_alunos = db.query(Aluno).count()
        alunos_risco = db.query(Aluno).filter(Aluno.nivel_risco != "BAIXO").count()
        pct_risco = round((alunos_risco / n_alunos * 100), 1) if n_alunos else 0
        total_respostas = db.query(RespostaAluno).count()
        total_acertos = db.query(RespostaAluno).filter(RespostaAluno.acertou == True).count()
        media_geral = round((total_acertos / total_respostas * 10), 1) if total_respostas else 0
        n_professores = db.query(Usuario).filter(Usuario.role == UserRole.PROFESSOR, Usuario.ativo == True).count()
        return {
            "projecao_ideb": 5.4,
            "alunos_risco_pct": pct_risco,
            "alunos_risco_total": alunos_risco,
            "media_geral": media_geral,
            "n_escolas": n_escolas,
            "n_turmas": n_turmas,
            "n_alunos": n_alunos,
            "n_professores": n_professores,
            "uso_ia_pct": 89,
        }

    def get_coordenador_stats(self, db: Session, escola_id: int | None = None) -> dict:
        q_turmas = db.query(Turma)
        q_alunos = db.query(Aluno)
        if escola_id:
            q_turmas = q_turmas.filter(Turma.escola_id == escola_id)
            q_alunos = q_alunos.join(Turma, Aluno.turma_id == Turma.id).filter(Turma.escola_id == escola_id)

        n_turmas = q_turmas.count()
        n_alunos = q_alunos.count()
        aluno_ids = [r[0] for r in q_alunos.with_entities(Aluno.id).all()]
        user_ids = [r[0] for r in q_alunos.with_entities(Aluno.usuario_id).all() if r[0]]

        total_atividades = db.query(AtividadeH5P).filter(AtividadeH5P.ativo == True).count()
        concluidas = 0
        if aluno_ids:
            concluidas = (
                db.query(ProgressoH5P)
                .filter(ProgressoH5P.aluno_id.in_(aluno_ids), ProgressoH5P.concluido == True)
                .count()
            )
        adesao_escolar_pct = 0.0
        if n_alunos and total_atividades:
            adesao_escolar_pct = round(min(100.0, (concluidas / (n_alunos * total_atividades)) * 100), 1)

        total_respostas_q = db.query(RespostaAluno)
        total_acertos_q = db.query(RespostaAluno).filter(RespostaAluno.acertou == True)
        if aluno_ids:
            total_respostas_q = total_respostas_q.filter(RespostaAluno.aluno_id.in_(aluno_ids))
            total_acertos_q = total_acertos_q.filter(RespostaAluno.aluno_id.in_(aluno_ids))
        total_respostas = total_respostas_q.count()
        total_acertos = total_acertos_q.count()
        media_proficiencia = round((total_acertos / total_respostas * 210), 1) if total_respostas else 0

        alunos_risco = q_alunos.filter(Aluno.nivel_risco != "BAIXO").count()
        turmas_alerta = 0
        if n_turmas:
            for t in q_turmas.all():
                t_aluno_ids = [r[0] for r in db.query(Aluno.id).filter(Aluno.turma_id == t.id).all()]
                if not t_aluno_ids:
                    continue
                done_t = (
                    db.query(ProgressoH5P)
                    .filter(ProgressoH5P.aluno_id.in_(t_aluno_ids), ProgressoH5P.concluido == True)
                    .count()
                )
                eng = (done_t / (len(t_aluno_ids) * max(1, total_atividades))) * 100 if total_atividades else 0
                if eng < 60:
                    turmas_alerta += 1

        interacoes_chatbot = 0
        if user_ids:
            try:
                from app.models.chat_session import ChatSession
                from app.models.chat_message import ChatMessage

                interacoes_chatbot = (
                    db.query(ChatMessage)
                    .join(ChatSession, ChatMessage.session_id == ChatSession.id)
                    .filter(ChatSession.user_id.in_(user_ids), ChatMessage.sender == "user")
                    .count()
                )
            except Exception:
                interacoes_chatbot = 0

        return {
            "adesao_escolar_pct": adesao_escolar_pct,
            "media_proficiencia": media_proficiencia,
            "turmas_alerta": turmas_alerta,
            "n_turmas": n_turmas,
            "n_alunos": n_alunos,
            "alunos_risco": alunos_risco,
            "interacoes_chatbot": interacoes_chatbot,
            # valores para mini-graficos (0..100)
            "kpi_chart_adesao": max(0, min(100, int(round(adesao_escolar_pct)))),
            "kpi_chart_proficiencia": max(0, min(100, int(round((media_proficiencia / 350) * 100))) if media_proficiencia else 0),
            "kpi_chart_turmas_alerta": max(0, min(100, int(round((turmas_alerta / max(1, n_turmas)) * 100)))),
            "kpi_chart_chat": max(0, min(100, int(round((interacoes_chatbot / max(1, n_alunos * 10)) * 100)))) if n_alunos else 0,
        }

    def get_professor_stats(self, db: Session) -> dict:
        n_turmas = db.query(Turma).count()
        n_alunos = db.query(Aluno).count()
        total_respostas = db.query(RespostaAluno).count()
        total_acertos = db.query(RespostaAluno).filter(RespostaAluno.acertou == True).count()
        proficiencia_pct = round((total_acertos / total_respostas * 100), 0) if total_respostas else 0
        alunos_risco = db.query(Aluno).filter(Aluno.nivel_risco != "BAIXO").count()
        return {
            "proficiencia_turma_pct": proficiencia_pct,
            "engajamento_pct": 82,
            "alunos_risco": alunos_risco,
            "n_turmas": n_turmas,
            "n_alunos": n_alunos,
            "moedas_turma": 12450,
        }

    def get_aluno_stats(self, db: Session, aluno_id: int) -> dict:
        aluno = db.query(Aluno).filter(Aluno.id == aluno_id).first()
        if not aluno:
            base = self.get_level_progress(0)
            return {"xp_total": 0, "progresso_pct": 0, "concluidos_h5p": 0, **base}
        gamificacao = db.query(PontuacaoGamificacao).filter(PontuacaoGamificacao.aluno_id == aluno_id).first()
        xp = gamificacao.xp_total if gamificacao else 0
        level_data = self.get_level_progress(xp)
        concluidos = db.query(ProgressoH5P).filter(
            ProgressoH5P.aluno_id == aluno_id,
            ProgressoH5P.concluido == True,
        ).count()
        return {
            "xp_total": xp,
            "progresso_pct": min(85, concluidos * 10),
            "concluidos_h5p": concluidos,
            **level_data,
        }
