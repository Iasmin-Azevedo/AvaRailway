from pydantic import BaseModel
from typing import List, Optional

class ResponderQuestao(BaseModel):
    questao_id: int
    alternativa_escolhida: str  # "A", "B", "C", "D" ou "E"

class SubmissaoProva(BaseModel):
    avaliacao_id: int
    aplicacao_id: Optional[int] = None
    respostas: List[ResponderQuestao]

class ResultadoProva(BaseModel):
    total_questoes: int
    acertos: int
    nota: float
    mensagem_ia: Optional[str] = None