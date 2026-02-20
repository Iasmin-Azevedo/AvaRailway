from sqlalchemy.orm import Session
from app.models.aluno import Aluno, PontuacaoGamificacao

class AlunoRepository:
    def create(self, db: Session, user_id: int, turma_id: int, ano: int):
        db_aluno = Aluno(usuario_id=user_id, turma_id=turma_id, ano_escolar=ano)
        db.add(db_aluno)
        db.commit()
        db.refresh(db_aluno)
        
        # Cria gamificação zerada
        gamificacao = PontuacaoGamificacao(aluno_id=db_aluno.id)
        db.add(gamificacao)
        db.commit()
        return db_aluno