from sqlalchemy.orm import Session
from app.repositories.avaliacao_repository import AvaliacaoRepository
from app.services.ia_service import IAService
from app.services.gamificacao_service import GamificacaoService

class AvaliacaoService:
    def __init__(self):
        self.repo = AvaliacaoRepository()
        self.ia = IAService()
        self.gamificacao = GamificacaoService()

    async def processar_prova(self, db: Session, aluno_id: int, dados):
        avaliacao = self.repo.get_avaliacao(db, dados.avaliacao_id)
        acertos = 0
        total = len(dados.respostas)

        for resp in dados.respostas:
            # Busca a questão no banco para ver o gabarito
            # (Simplificação: assumindo que a questao está na memoria da avaliacao carregada)
            questao = next((q for q in avaliacao.questoes if q.id == resp.questao_id), None)
            
            e_correto = False
            if questao and questao.gabarito == resp.alternativa_escolhida:
                acertos += 1
                e_correto = True
            
            self.repo.salvar_resposta(db, aluno_id, dados.avaliacao_id, resp.questao_id, resp.alternativa_escolhida, e_correto)

        # Chama a IA
        feedback = self.ia.gerar_feedback(acertos, total)
        
        # Chama a Gamificação (Observer)
        await self.gamificacao.processar_xp({"aluno_id": aluno_id, "acertos": acertos}, db)

        return {
            "total_questoes": total,
            "acertos": acertos,
            "nota": (acertos/total)*10,
            "mensagem_ia": feedback
        }