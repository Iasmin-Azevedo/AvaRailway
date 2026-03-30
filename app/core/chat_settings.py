from pydantic import BaseModel, Field


class RetrievedChunk(BaseModel):
    """Representa um trecho recuperado para apoiar a resposta do chatbot."""

    source: str
    title: str
    content: str
    score: float
    metadata: dict = Field(default_factory=dict)
