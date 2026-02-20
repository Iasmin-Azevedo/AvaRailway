from sqlalchemy.orm import Session
from app.models.avaliacao import Avaliacao, Questao
from app.models.resposta import RespostaAluno

class AvaliacaoRepository:
    def get_avaliacao(self, db: Session, avaliacao_id: int):
        return db.query(Avaliacao).filter(Avaliacao.id == avaliacao_id).first()

    def salvar_resposta(self, db: Session, aluno_id: int, avaliacao_id: int, questao_id: int, marcada: str, correta: bool):
        resposta = RespostaAluno(
            aluno_id=aluno_id,
            avaliacao_id=avaliacao_id,
            questao_id=questao_id,
            resposta_marcada=marcada,
            acertou=correta
        )
        db.add(resposta)
        db.commit()
        return resposta