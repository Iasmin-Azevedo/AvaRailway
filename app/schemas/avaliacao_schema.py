from pydantic import BaseModel
from typing import List, Optional

class ResponderQuestao(BaseModel):
    questao_id: int
    alternativa_escolhida: str # "A", "B", "C", "D"

class SubmissaoProva(BaseModel):
    avaliacao_id: int
    respostas: List[ResponderQuestao]

class ResultadoProva(BaseModel):
    total_questoes: int
    acertos: int
    nota: float
    mensagem_ia: Optional[str] = None