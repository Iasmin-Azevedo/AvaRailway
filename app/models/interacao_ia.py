from sqlalchemy import Column, Integer, Text, ForeignKey, DateTime
from datetime import datetime
from app.models.base import Base

class InteracaoIA(Base):
    __tablename__ = "interacoes_ia"
    id = Column(Integer, primary_key=True)
    aluno_id = Column(Integer, ForeignKey("alunos.id"))
    pergunta = Column(Text)
    resposta_ia = Column(Text)
    contexto = Column(Text) # Ex: "Dúvida sobre Equação de 2 grau"
    data = Column(DateTime, default=datetime.utcnow)