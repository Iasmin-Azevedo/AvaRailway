from sqlalchemy.orm import Session

from app.models.aluno import Aluno, PontuacaoGamificacao
from app.models.avaliacao import Avaliacao
from app.models.gestao import Trilha, Turma
from app.models.h5p import ProgressoH5P
from app.models.relacoes import ProfessorTurma
from app.models.resposta import RespostaAluno
from app.models.saeb import Descritor


class ChatContextService:
    def __init__(self, db: Session):
        self.db = db

    def build_context(self, user: object, message_type: str) -> dict:
        role = getattr(user, "role", "aluno")
        role_value = getattr(role, "value", role)
        context = {
            "user": {
                "id": getattr(user, "id", None),
                "nome": getattr(user, "nome", "Usuario"),
                "perfil": role_value,
            },
            "pedagogical": {},
            "institutional": {},
            "constraints": [],
        }

        if role_value == "aluno":
            aluno = self.db.query(Aluno).filter(Aluno.usuario_id == getattr(user, "id", None)).first()
            acertos = 0
            respostas = 0
            xp_total = 0
            if aluno:
                turma = self.db.query(Turma).filter(Turma.id == aluno.turma_id).first() if aluno.turma_id else None
                respostas = self.db.query(RespostaAluno).filter(RespostaAluno.aluno_id == aluno.id).count()
                acertos = self.db.query(RespostaAluno).filter(
                    RespostaAluno.aluno_id == aluno.id,
                    RespostaAluno.acertou == True,
                ).count()
                gamificacao = self.db.query(PontuacaoGamificacao).filter(PontuacaoGamificacao.aluno_id == aluno.id).first()
                xp_total = gamificacao.xp_total if gamificacao else 0
                concluidos = self.db.query(ProgressoH5P).filter(
                    ProgressoH5P.aluno_id == aluno.id,
                    ProgressoH5P.concluido == True,
                ).count()
                avaliacoes_recentes = (
                    self.db.query(Avaliacao)
                    .order_by(Avaliacao.data_aplicacao.desc())
                    .limit(3)
                    .all()
                )
                trilhas_recomendadas = (
                    self.db.query(Trilha)
                    .filter((Trilha.ano_escolar == aluno.ano_escolar) | (Trilha.ano_escolar.is_(None)))
                    .order_by(Trilha.ordem.asc())
                    .limit(3)
                    .all()
                )
                context["pedagogical"] = {
                    "ano_escolar": aluno.ano_escolar,
                    "turma": turma.nome if turma else None,
                    "nivel_risco": aluno.nivel_risco,
                    "respostas_total": respostas,
                    "acertos_total": acertos,
                    "aproveitamento_pct": round((acertos / respostas) * 100, 1) if respostas else 0,
                    "conteudos_concluidos": concluidos,
                    "xp_total": xp_total,
                    "avaliacoes_recentes": [item.titulo for item in avaliacoes_recentes if item.titulo],
                    "trilhas_sugeridas": [item.nome for item in trilhas_recomendadas if item.nome],
                }
            context["constraints"].append("Somente dados do proprio aluno podem ser utilizados.")

        elif role_value == "professor":
            turmas = self.db.query(ProfessorTurma).filter(ProfessorTurma.professor_id == getattr(user, "id", None)).all()
            descritores_criticos = (
                self.db.query(Descritor)
                .limit(5)
                .all()
            )
            context["institutional"] = {
                "turmas_vinculadas": [item.turma_id for item in turmas],
                "total_turmas": len(turmas),
                "descritores_monitorados": [item.codigo for item in descritores_criticos if item.codigo],
            }
            context["constraints"].append("Somente turmas vinculadas ao professor podem ser consultadas.")

        elif role_value in {"coordenador", "gestor", "admin"}:
            context["institutional"] = {
                "perfil_institucional": role_value,
                "consulta_consolidada": True,
                "total_turmas": self.db.query(Turma).count(),
                "total_descritores": self.db.query(Descritor).count(),
            }

        if message_type == "general":
            context["constraints"].append("Responder naturalmente, sem inventar dados do sistema.")
        else:
            context["constraints"].append("Quando usar dados do sistema, responder apenas com base no contexto fornecido.")
        context["constraints"].append("Se a informacao nao estiver disponivel, admitir isso com clareza e sugerir o proximo passo.")

        return context
