from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import Base

class Aluno(Base):
    __tablename__ = "alunos"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    turma_id = Column(Integer)
    ano_escolar = Column(Integer)
    nivel_risco = Column(String(20), default="BAIXO")
    
    usuario = relationship("Usuario", back_populates="aluno_perfil")
    pontuacao = relationship("PontuacaoGamificacao", back_populates="aluno", uselist=False)

class PontuacaoGamificacao(Base):
    __tablename__ = "gamificacao"
    id = Column(Integer, primary_key=True)
    aluno_id = Column(Integer, ForeignKey("alunos.id"))
    xp_total = Column(Integer, default=0)
    nivel = Column(String(50), default="Novato")
    
    aluno = relationship("Aluno", back_populates="pontuacao")