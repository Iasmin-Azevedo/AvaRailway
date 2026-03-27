from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()


class TutorChatRequest(BaseModel):
    pergunta: str = Field(min_length=1, max_length=500)


@router.post("/chat")
def conversar_com_tutor(payload: TutorChatRequest):
    return {
        "resposta": (
            "Eu sou o Tutor IA do AVA MJ. "
            f"Recebi sua pergunta: {payload.pergunta}"
        )
    }
