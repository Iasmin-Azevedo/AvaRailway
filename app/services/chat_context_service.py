from sqlalchemy.orm import Session

from app.models.aluno import Aluno, PontuacaoGamificacao
from app.models.h5p import ProgressoH5P
from app.models.relacoes import ProfessorTurma
from app.models.resposta import RespostaAluno


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
                context["pedagogical"] = {
                    "ano_escolar": aluno.ano_escolar,
                    "nivel_risco": aluno.nivel_risco,
                    "respostas_total": respostas,
                    "acertos_total": acertos,
                    "aproveitamento_pct": round((acertos / respostas) * 100, 1) if respostas else 0,
                    "conteudos_concluidos": concluidos,
                    "xp_total": xp_total,
                }
            context["constraints"].append("Somente dados do proprio aluno podem ser utilizados.")

        elif role_value == "professor":
            turmas = self.db.query(ProfessorTurma).filter(ProfessorTurma.professor_id == getattr(user, "id", None)).all()
            context["institutional"] = {
                "turmas_vinculadas": [item.turma_id for item in turmas],
                "total_turmas": len(turmas),
            }
            context["constraints"].append("Somente turmas vinculadas ao professor podem ser consultadas.")

        elif role_value in {"coordenador", "gestor", "admin"}:
            context["institutional"] = {
                "perfil_institucional": role_value,
                "consulta_consolidada": True,
            }

        if message_type == "general":
            context["constraints"].append("Responder naturalmente, sem inventar dados do sistema.")
        else:
            context["constraints"].append("Quando usar dados do sistema, responder apenas com base no contexto fornecido.")

        return context
