from sqlalchemy import Column, Integer, String, ForeignKey, Text
from app.models.base import Base

class Descritor(Base):
    __tablename__ = "saeb_descritores"
    id = Column(Integer, primary_key=True)
    codigo = Column(String(10), unique=True)
    descricao = Column(String(255))
    disciplina = Column(String(50))

class Questao(Base):
    __tablename__ = "questoes"
    id = Column(Integer, primary_key=True)
    descritor_id = Column(Integer, ForeignKey("saeb_descritores.id"))
    enunciado = Column(Text)