from fastapi import APIRouter
from app.services.ia_service import IAService

router = APIRouter()
ia_service = IAService()

@router.post("/chat")
def conversar_com_tutor(pergunta: str):
    # Endpoint simples para chat
    return {"resposta": "Eu sou o Tutor IA. Ainda estou aprendendo, mas sua pergunta foi: " + pergunta}