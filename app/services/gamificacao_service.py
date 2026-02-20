from sqlalchemy.orm import Session
from app.models.aluno import PontuacaoGamificacao
from app.core.events import event_manager

class GamificacaoService:
    async def processar_xp(self, dados: dict, db: Session):
        aluno_id = dados.get("aluno_id")
        xp_ganho = dados.get("acertos", 0) * 10
        
        gamificacao = db.query(PontuacaoGamificacao).filter_by(aluno_id=aluno_id).first()
        if gamificacao:
            gamificacao.xp_total += xp_ganho
            if gamificacao.xp_total > 1000:
                gamificacao.nivel = "Mestre"
            db.commit()
            print(f"🎮 [Gamification] Aluno {aluno_id} ganhou {xp_ganho} XP!")

# Registra o ouvinte
event_manager.subscribe("AVALIACAO_FINALIZADA", GamificacaoService().processar_xp)