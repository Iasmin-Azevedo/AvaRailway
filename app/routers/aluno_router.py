from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.config import settings
from app.models.user import UserRole
from app.schemas.user_schema import UserCreate, UserResponse
from app.repositories.user_repository import UserRepository
from app.repositories.aluno_repository import AlunoRepository

router = APIRouter()
page_router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
user_repo = UserRepository()
aluno_repo = AlunoRepository()


def _get_aluno_nome(request: Request, db: Session) -> str:
    aluno_nome = "Aluno"
    token = request.cookies.get("access_token")
    if token:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            email = payload.get("sub")
            if email:
                user = user_repo.get_by_email(db, email)
                if user and user.nome:
                    aluno_nome = user.nome
        except JWTError:
            pass
    return aluno_nome


@page_router.get("/aluno")
def aluno_home(request: Request, db: Session = Depends(get_db)):
    """Tela inicial do aluno (dashboard)."""
    from app.models.aluno import Aluno
    from app.services.dashboard_service import DashboardService
    aluno_nome = _get_aluno_nome(request, db)
    aluno_id = None
    aluno_ano = None
    token = request.cookies.get("access_token")
    if token:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            email = payload.get("sub")
            if email:
                user = user_repo.get_by_email(db, email)
                if user:
                    aluno = db.query(Aluno).filter(Aluno.usuario_id == user.id).first()
                    if aluno:
                        aluno_id = aluno.id
                        aluno_ano = aluno.ano_escolar
        except JWTError:
            pass
    stats = DashboardService().get_aluno_stats(db, aluno_id) if aluno_id else {}

    preview_trilha = None
    preview_curso_nome = None
    preview_atividades_total = 0
    from app.repositories.gestao_repository import TrilhaRepository
    from app.repositories.h5p_repository import AtividadeH5PRepository

    trilhas_prev = TrilhaRepository().listar(db)
    if trilhas_prev:
        preview_trilha = trilhas_prev[0]
        preview_curso_nome = (
            preview_trilha.curso.nome
            if getattr(preview_trilha, "curso", None)
            else preview_trilha.nome
        )
        preview_atividades_total = len(
            AtividadeH5PRepository().listar(
                db, trilha_id=preview_trilha.id, ativo_only=True
            )
        )

    return templates.TemplateResponse(
        "aluno/dashboard.html",
        {
            "request": request,
            "aluno_nome": aluno_nome,
            "aluno_ano": aluno_ano,
            "stats": stats,
            "preview_trilha": preview_trilha,
            "preview_curso_nome": preview_curso_nome,
            "preview_atividades_total": preview_atividades_total,
        },
    )



@page_router.get("/aluno/missao1")
def aluno_missao_1(request: Request, db: Session = Depends(get_db)):
    aluno_nome = _get_aluno_nome(request, db)
    return templates.TemplateResponse(
        "aluno/missao1_desafios.html",
        {"request": request, "aluno_nome": aluno_nome},
    )


@page_router.get("/aluno/trilhas")
def aluno_trilhas(request: Request, db: Session = Depends(get_db)):
    """Lista trilhas e atividades H5P para o aluno."""
    from app.models.aluno import Aluno
    from app.models.saeb import Descritor
    from app.repositories.gestao_repository import TrilhaRepository
    from app.repositories.h5p_repository import AtividadeH5PRepository

    aluno_nome = _get_aluno_nome(request, db)
    aluno_ano = None
    token = request.cookies.get("access_token")
    if token:
        try:
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
            )
            email = payload.get("sub")
            if email:
                user = user_repo.get_by_email(db, email)
                if user:
                    aluno = db.query(Aluno).filter(Aluno.usuario_id == user.id).first()
                    if aluno:
                        aluno_ano = aluno.ano_escolar
        except JWTError:
            pass

    trilhas = TrilhaRepository().listar(db)
    atividades_por_trilha = {}
    desc_ids = set()
    for t in trilhas:
        acts = AtividadeH5PRepository().listar(
            db, trilha_id=t.id, ativo_only=True
        )
        atividades_por_trilha[t.id] = acts
        for a in acts:
            if a.descritor_id:
                desc_ids.add(a.descritor_id)

    descritores_por_id = {}
    if desc_ids:
        for d in db.query(Descritor).filter(Descritor.id.in_(desc_ids)).all():
            descritores_por_id[d.id] = d

    descritores_por_trilha = {}
    tipos_por_trilha = {}
    for t in trilhas:
        acts = atividades_por_trilha[t.id]
        tipos_por_trilha[t.id] = sorted({a.tipo for a in acts})
        seen_d = set()
        lista_d = []
        for a in acts:
            if a.descritor_id and a.descritor_id in descritores_por_id:
                d = descritores_por_id[a.descritor_id]
                if d.id not in seen_d:
                    seen_d.add(d.id)
                    lista_d.append(d)
        descritores_por_trilha[t.id] = lista_d

    return templates.TemplateResponse(
        "aluno/trilhas.html",
        {
            "request": request,
            "aluno_nome": aluno_nome,
            "aluno_ano": aluno_ano,
            "trilhas": trilhas,
            "atividades_por_trilha": atividades_por_trilha,
            "descritores_por_trilha": descritores_por_trilha,
            "tipos_por_trilha": tipos_por_trilha,
        },
    )


@page_router.get("/aluno/atividade/{id}")
def aluno_atividade(request: Request, id: int, db: Session = Depends(get_db)):
    """Página do player H5P para a atividade."""
    from app.repositories.h5p_repository import AtividadeH5PRepository
    aluno_nome = _get_aluno_nome(request, db)
    atividade = AtividadeH5PRepository().get(db, id)
    if not atividade or not atividade.ativo:
        return RedirectResponse(url="/aluno/trilhas", status_code=302)

    # Renderiza uma prévia visual por tipo (quiz, drag-drop, vídeo, etc.)
    tipo_para_template = {
        "quiz": "aluno/atividade_h5p_quiz.html",
        "drag-drop": "aluno/atividade_h5p_drag_drop.html",
        "video": "aluno/atividade_h5p_video.html",
        "flashcards": "aluno/atividade_h5p_flashcards.html",
        "presentation": "aluno/atividade_h5p_presentation.html",
    }
    template_path = tipo_para_template.get(atividade.tipo, "aluno/atividade_h5p_outro.html")

    return templates.TemplateResponse(
        template_path,
        {
            "request": request,
            "aluno_nome": aluno_nome,
            "atividade": atividade,
            "content_url": f"/api/h5p/content/{id}/content.json",
        },
    )


@page_router.post("/aluno")
async def criar_aluno_web(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    user = UserCreate(
        nome=form.get("nome"),
        email=form.get("email"),
        senha=form.get("senha"),
        role=UserRole.ALUNO,
    )
    turma_id = form.get("turma_id")
    ano = form.get("ano")

    if not turma_id or not ano:
        raise HTTPException(status_code=422, detail="turma_id e ano sao obrigatorios")

    novo_user = user_repo.create(db, user)
    aluno_repo.create(db, novo_user.id, int(turma_id), int(ano))
    return RedirectResponse(url="/aluno", status_code=303)


@router.post("/cadastro", response_model=UserResponse)
async def criar_aluno(
    request: Request,
    turma_id: int | None = None,
    ano: int | None = None,
    db: Session = Depends(get_db),
):
    content_type = request.headers.get("content-type", "")
    accepts_html = "text/html" in request.headers.get("accept", "")

    if "application/json" in content_type:
        payload = await request.json()
        user = UserCreate(
            nome=payload.get("nome"),
            email=payload.get("email"),
            senha=payload.get("senha"),
            role=payload.get("role", "aluno"),
        )
        turma_id = turma_id if turma_id is not None else payload.get("turma_id")
        ano = ano if ano is not None else payload.get("ano")
    else:
        form = await request.form()
        user = UserCreate(
            nome=form.get("nome"),
            email=form.get("email"),
            senha=form.get("senha"),
            role="aluno",
        )
        turma_id = turma_id if turma_id is not None else form.get("turma_id")
        ano = ano if ano is not None else form.get("ano")

    if turma_id is None or ano is None:
        raise HTTPException(status_code=422, detail="turma_id e ano sao obrigatorios")

    novo_user = user_repo.create(db, user)
    aluno_repo.create(db, novo_user.id, int(turma_id), int(ano))

    if accepts_html:
        return RedirectResponse(url="/aluno", status_code=303)
    return novo_user