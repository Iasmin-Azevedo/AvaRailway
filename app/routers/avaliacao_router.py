from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.schemas.avaliacao_schema import SubmissaoProva, ResultadoProva
from app.services.avaliacao_service import AvaliacaoService

router = APIRouter()
service = AvaliacaoService()

# Simulação de pegar ID do usuário logado (depois implementar auth real aqui)
def get_current_user_id():
    return 1 

@router.post("/submeter", response_model=ResultadoProva)
async def enviar_prova(dados: SubmissaoProva, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    # Em um cenário real, converteriamos user_id para aluno_id aqui
    return await service.processar_prova(db, user_id, dados)