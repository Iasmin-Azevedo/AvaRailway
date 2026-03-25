from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session
from app.core.security import limiter
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.user import Usuario, UserRole
from app.services.dashboard_service import DashboardService

router = APIRouter()

@router.get("/dashboard/gestor")
@limiter.limit("5/minute")
def dashboard_gestor(request: Request, db: Session = Depends(get_db)):
    return DashboardService().get_gestor_stats(db)

@router.get("/dashboard/coordenador")
@limiter.limit("5/minute")
def dashboard_coordenador(request: Request, db: Session = Depends(get_db)):
    return DashboardService().get_coordenador_stats(db)

@router.get("/dashboard/professor")
@limiter.limit("5/minute")
def dashboard_professor(request: Request, db: Session = Depends(get_db)):
    return DashboardService().get_professor_stats(db)

@router.get("/dashboard/aluno")
@limiter.limit("10/minute")
def dashboard_aluno(request: Request, db: Session = Depends(get_db), current_user: Usuario = Depends(get_current_user)):
    from app.models.aluno import Aluno
    aluno = db.query(Aluno).filter(Aluno.usuario_id == current_user.id).first()
    if not aluno:
        return {"xp_total": 0, "nivel": "Novato", "progresso_pct": 0}
    return DashboardService().get_aluno_stats(db, aluno.id)