from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.gestao import Escola, Turma
from app.models.aluno import Aluno, PontuacaoGamificacao
from app.models.h5p import ProgressoH5P
from app.models.user import Usuario, UserRole
from app.models.avaliacao import Avaliacao
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

    def get_coordenador_stats(self, db: Session) -> dict:
        n_escolas = db.query(Escola).filter(Escola.ativo == True).count()
        n_turmas = db.query(Turma).count()
        n_alunos = db.query(Aluno).count()
        total_respostas = db.query(RespostaAluno).count()
        total_acertos = db.query(RespostaAluno).filter(RespostaAluno.acertou == True).count()
        media_proficiencia = round((total_acertos / total_respostas * 210), 1) if total_respostas else 0
        alunos_risco = db.query(Aluno).filter(Aluno.nivel_risco != "BAIXO").count()
        turmas_alerta = 0
        return {
            "adesao_escolar_pct": min(92, 70 + (n_alunos // 10)),
            "media_proficiencia": media_proficiencia,
            "turmas_alerta": turmas_alerta,
            "n_escolas": n_escolas,
            "n_turmas": n_turmas,
            "n_alunos": n_alunos,
            "interacoes_chatbot": 3450,
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
