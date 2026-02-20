from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.resposta import RespostaAluno

class AnalyticsService:
    def get_desempenho_turma(self, db: Session, turma_id: int):
        # Calcula média de acertos da turma
        # (Lógica simplificada para exemplo)
        total_respostas = db.query(RespostaAluno).count()
        total_acertos = db.query(RespostaAluno).filter(RespostaAluno.acertou == True).count()
        
        if total_respostas == 0:
            return {"media": 0}
            
        return {
            "media_global": (total_acertos / total_respostas) * 100,
            "status": "Em processamento"
        }