import logging
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.media_urls import h5p_content_root, user_upload_root
from app.core.database import SessionLocal, engine, get_db
from app.core.dependencies import get_current_user_optional, require_admin_redirect, require_role_redirect
from app.core.logging_config import configure_logging
from app.core.security import limiter
from app.models.base import Base
from app.models.user import UserRole, Usuario
from app.services.dashboard_service import DashboardService

from app.routers import (
    admin_pages_router,
    admin_router,
    aluno_router,
    auth_router,
    avaliacao_router,
    chat_router,
    dashboard_router,
    h5p_router,
    ia_router,
    live_support_router,
)
from app.models import (
    aluno,
    avaliacao,
    chat_feedback,
    chat_memory,
    chat_message,
    chat_session,
    gestao,
    h5p,
    interacao_ia,
    live_support,
    moodle_gestao,
    relacoes,
    resposta,
    saeb,
    professor_h5p,
    support_ticket,
    user,
)

configure_logging()
logger = logging.getLogger("ava_mj_backend")

app = FastAPI(title="AVA MJ Enterprise")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "templates" / "static")), name="static")

_h5p_dir = h5p_content_root()
_h5p_dir.mkdir(parents=True, exist_ok=True)
app.mount("/h5p", StaticFiles(directory=str(_h5p_dir)), name="h5p_content")

_upload_dir = user_upload_root()
_upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(_upload_dir)), name="user_uploads")

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def _wants_html_response(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    path = request.url.path or ""
    if path.startswith("/api/") or path.startswith("/auth/") and path.endswith("/refresh"):
        return False
    if "text/html" in accept:
        return True
    if "application/json" in accept and "text/html" not in accept:
        return False
    return True


def _detail_as_text(detail) -> str:
    if detail is None:
        return ""
    if isinstance(detail, str):
        return detail
    try:
        import json

        return json.dumps(detail, ensure_ascii=False)[:4000]
    except Exception:
        return str(detail)[:4000]


def _error_html(
    request: Request,
    *,
    status_code: int,
    title: str,
    message: str,
    detail: str | None = None,
):
    ctx = {
        "request": request,
        "status_code": status_code,
        "title": title,
        "message": message,
        "detail": detail if settings.APP_DEBUG else None,
    }
    return templates.TemplateResponse(
        request,
        "errors/error_page.html",
        ctx,
        status_code=status_code,
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    logger.error(f"Erro critico de banco de dados: {str(exc)}")
    if _wants_html_response(request):
        return _error_html(
            request,
            status_code=500,
            title="Erro no banco de dados",
            message="Não foi possível processar a solicitação. Tente novamente em instantes.",
            detail=str(exc),
        )
    return JSONResponse(
        status_code=500,
        content={
            "status_code": 500,
            "mensagem_amigavel": "Nao foi possivel processar a solicitacao.",
            "detalhe_tecnico": "Falha interna de banco de dados.",
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    if _wants_html_response(request):
        return _error_html(
            request,
            status_code=422,
            title="Dados inválidos",
            message="Alguns campos do formulário estão incorretos ou incompletos.",
            detail=_detail_as_text(exc.errors()),
        )
    return JSONResponse(
        status_code=422,
        content={
            "status_code": 422,
            "mensagem_amigavel": "Existem campos invalidos na solicitacao.",
            "detalhe_tecnico": exc.errors(),
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail_text = _detail_as_text(exc.detail)
    titles = {
        401: "Não autenticado",
        403: "Acesso negado",
        404: "Não encontrado",
        422: "Dados inválidos",
        500: "Erro interno",
    }
    title = titles.get(exc.status_code, "Erro")
    if _wants_html_response(request):
        return _error_html(
            request,
            status_code=exc.status_code,
            title=title,
            message=detail_text or title,
            detail=detail_text if settings.APP_DEBUG else None,
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status_code": exc.status_code,
            "mensagem_amigavel": detail_text,
            "detalhe_tecnico": detail_text,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Erro inesperado na aplicacao", exc_info=exc)
    if _wants_html_response(request):
        return _error_html(
            request,
            status_code=500,
            title="Erro inesperado",
            message="Ocorreu um problema ao processar sua solicitação. Nossa equipe foi notificada.",
            detail=str(exc),
        )
    return JSONResponse(
        status_code=500,
        content={
            "status_code": 500,
            "mensagem_amigavel": "Nao foi possivel processar a solicitacao.",
            "detalhe_tecnico": "Erro interno nao tratado.",
        },
    )


def seed_default_users() -> None:
    from app.repositories.user_repository import UserRepository
    from app.schemas.user_schema import UserCreate

    defaults = [
        {"nome": "Admin AVA MJ", "email": "admin@avajmj.com", "role": UserRole.ADMIN},
        {"nome": "Professor AVA MJ", "email": "professor@avamj.com", "role": UserRole.PROFESSOR},
        {"nome": "Aluno AVA MJ", "email": "aluno@avamj.com", "role": UserRole.ALUNO},
        {"nome": "Gestor AVA MJ", "email": "gestor@avamj.com", "role": UserRole.GESTOR},
        {"nome": "Coordenador AVA MJ", "email": "coordenador@avamj.com", "role": UserRole.COORDENADOR},
    ]

    db = SessionLocal()
    try:
        repo = UserRepository()
        for d in defaults:
            existing = repo.get_by_email(db, d["email"])
            if existing:
                repo.update(
                    db,
                    id=existing.id,
                    nome=d["nome"],
                    email=d["email"],
                    senha="123456",
                    role=d["role"],
                    ativo=True,
                )
            else:
                repo.create(
                    db,
                    UserCreate(
                        nome=d["nome"],
                        email=d["email"],
                        senha="123456",
                        role=d["role"],
                    ),
                )
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    try:
        _ensure_runtime_schema()
        Base.metadata.create_all(bind=engine)
        seed_default_users()
        logger.info("Banco sincronizado e seed executado.")
    except Exception as exc:
        logger.error(f"Erro no startup: {exc}")


def _ensure_runtime_schema() -> None:
    """
    Ajustes incrementais simples sem migração formal (ambiente atual).
    """
    insp = inspect(engine)
    try:
        cols = {c["name"] for c in insp.get_columns("usuarios")}
    except Exception:
        cols = set()
    if "permite_cadastro_trilha_geral" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN permite_cadastro_trilha_geral BOOLEAN DEFAULT 0"))
    if "avatar_url" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN avatar_url VARCHAR(500)"))
    if "moodle_user_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN moodle_user_id VARCHAR(32)"))


app.include_router(auth_router.router, prefix="/auth", tags=["Auth"])
app.include_router(aluno_router.router, prefix="/alunos", tags=["Alunos"])
app.include_router(aluno_router.page_router, tags=["Aluno"])
app.include_router(dashboard_router.router, prefix="/api", tags=["Dashboard"])
app.include_router(avaliacao_router.router, prefix="/provas", tags=["Avaliacao"])
app.include_router(ia_router.router, prefix="/ia", tags=["Inteligencia Artificial"])
app.include_router(admin_router.router, prefix="/api/admin", tags=["Admin"])
app.include_router(admin_pages_router.router, prefix="/admin", tags=["Admin Pages"])
app.include_router(h5p_router.router, prefix="/api/h5p", tags=["H5P"])
app.include_router(chat_router.router)
app.include_router(live_support_router.router)
app.include_router(live_support_router.page_router)


@app.get("/login")
def login_page(request: Request):
    next_url = (request.query_params.get("next") or "").strip()
    return templates.TemplateResponse(
        request,
        "auth/login.html",
        {"request": request, "next_url": next_url},
    )


@app.get("/erro/{code:int}")
def erro_demo(request: Request, code: int):
    """Páginas de erro estáticas para teste e links diretos."""
    titles = {403: "Acesso negado", 404: "Página não encontrada", 500: "Erro interno"}
    msgs = {
        403: "Você não tem permissão para ver este conteúdo.",
        404: "O endereço não existe ou foi removido.",
        500: "Ocorreu uma falha no servidor.",
    }
    if code not in titles:
        code = 404
    return _error_html(
        request,
        status_code=code,
        title=titles.get(code, "Erro"),
        message=msgs.get(code, "Erro."),
        detail=None,
    )


@app.get("/cadastro")
def cadastro_page(request: Request, db: Session = Depends(get_db)):
    from app.repositories.gestao_repository import EscolaRepository, TurmaRepository

    try:
        turmas = TurmaRepository().listar(db)
        escolas = EscolaRepository().listar(db, ativo_only=True)
    except Exception:
        turmas = []
        escolas = []
    return templates.TemplateResponse(
        request,
        "auth/cadastro.html",
        {"request": request, "turmas": turmas or [], "escolas": escolas or []},
    )


def _professor_turmas_list(db: Session, professor_user_id: int):
    from app.models.gestao import Turma
    from app.models.relacoes import ProfessorTurma

    relacoes = (
        db.query(ProfessorTurma)
        .join(Turma, ProfessorTurma.turma_id == Turma.id)
        .filter(ProfessorTurma.professor_id == professor_user_id)
        .all()
    )
    return [rel.turma for rel in relacoes]


def _resolve_professor_turma_selection(
    professor_turmas: list, raw: str | None
) -> tuple[int | None, bool]:
    """
    Retorna (turma_id em modo único, turma_all).
    Em modo "todas as turmas", turma_id é None.
    """
    ids = {t.id for t in professor_turmas}
    if raw == "all" and professor_turmas:
        return None, True
    if raw and raw.isdigit() and int(raw) in ids:
        return int(raw), False
    if professor_turmas:
        return professor_turmas[0].id, False
    return None, False


def _professor_turma_query_suffix(has_turmas: bool, turma_all: bool, selected_turma_id: int | None) -> str:
    if not has_turmas:
        return ""
    if turma_all:
        return "?turma_id=all"
    if selected_turma_id is not None:
        return f"?turma_id={selected_turma_id}"
    return ""


def _professor_nav_context(db: Session, professor_user_id: int, request: Request) -> dict:
    professor_turmas = _professor_turmas_list(db, professor_user_id)
    selected_turma_id, turma_all = _resolve_professor_turma_selection(
        professor_turmas, request.query_params.get("turma_id")
    )
    return {
        "professor_turmas": professor_turmas,
        "selected_turma_id": selected_turma_id,
        "turma_all": turma_all,
        "turma_query_suffix": _professor_turma_query_suffix(
            bool(professor_turmas), turma_all, selected_turma_id
        ),
    }


_MAX_AVATAR_BYTES = 2 * 1024 * 1024


async def _save_user_avatar_upload(user_id: int, upload_file) -> str | None:
    from app.core.media_urls import user_upload_root

    if not upload_file or not getattr(upload_file, "filename", ""):
        return None
    body = await upload_file.read()
    if len(body) > _MAX_AVATAR_BYTES:
        return None
    ext = None
    if body.startswith(b"\xff\xd8\xff"):
        ext = "jpg"
    elif body.startswith(b"\x89PNG\r\n\x1a\n"):
        ext = "png"
    elif len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        ext = "webp"
    else:
        return None
    av = user_upload_root() / "avatars"
    av.mkdir(parents=True, exist_ok=True)
    path = av / f"{user_id}.{ext}"
    path.write_bytes(body)
    # Evita cache do browser quando o ficheiro reutiliza o mesmo path (ex.: troca de foto mantendo .jpg).
    return f"/media/avatars/{user_id}.{ext}?v={int(time.time())}"


def _perfil_form_response(
    request: Request,
    user: Usuario,
    home_url: str,
    *,
    template_name: str = "shared/perfil_form.html",
    extra: dict | None = None,
):
    ctx = {
        "request": request,
        "current_user": user,
        "home_url": home_url,
        "avatar_src": (getattr(user, "avatar_url", None) or "").strip(),
    }
    if extra:
        ctx.update(extra)
    return templates.TemplateResponse(request, template_name, ctx)


async def _perfil_salvar(request: Request, db: Session, user: Usuario, redirect_path: str):
    # current_user vem de outro Depends(get_db): sem reabrir na sessão desta rota, o commit não persiste.
    db_user = db.get(Usuario, user.id)
    if not db_user:
        return RedirectResponse(url="/login", status_code=303)
    form = await request.form()
    nome = (form.get("nome") or "").strip()
    if nome:
        db_user.nome = nome
    foto = form.get("avatar")
    new_url = await _save_user_avatar_upload(db_user.id, foto)
    if new_url:
        db_user.avatar_url = new_url
    db.commit()
    return RedirectResponse(url=f"{redirect_path}?ok=1", status_code=303)


def _parse_aluno_ids_from_form(form) -> set[int]:
    out: set[int] = set()
    for x in form.getlist("aluno_ids"):
        try:
            out.add(int(str(x).strip()))
        except (TypeError, ValueError):
            continue
    return out


def _alunos_destino_options(db: Session, professor_user_id: int) -> list[dict]:
    from app.models.aluno import Aluno
    from app.models.user import Usuario

    turma_ids = _professor_allowed_turma_ids(db, professor_user_id)
    if not turma_ids:
        return []
    rows = (
        db.query(Aluno.id, Aluno.turma_id, Aluno.ano_escolar, Usuario.nome, Usuario.avatar_url)
        .join(Usuario, Usuario.id == Aluno.usuario_id)
        .filter(Aluno.turma_id.in_(turma_ids))
        .order_by(Usuario.nome)
        .all()
    )
    out = []
    for aluno_id, turma_id, ano, nome, avatar in rows:
        label = (nome or "").strip() or f"Aluno #{aluno_id}"
        partes = label.split()
        if len(partes) >= 2:
            ini = (partes[0][0] + partes[-1][0]).upper()
        elif len(partes) == 1 and len(partes[0]) >= 2:
            ini = partes[0][:2].upper()
        else:
            ini = "AL"
        out.append(
            {
                "id": aluno_id,
                "turma_id": turma_id,
                "nome": label,
                "ano_escolar": ano,
                "avatar_url": (avatar or "").strip(),
                "iniciais": ini,
            }
        )
    return out


def _sync_professor_atividade_alvos(
    db: Session, atividade_id: int, turma_id: int, aluno_ids: set[int]
) -> None:
    from app.models.aluno import Aluno
    from app.models.professor_h5p import ProfessorAtividadeH5PAluno

    db.query(ProfessorAtividadeH5PAluno).filter(
        ProfessorAtividadeH5PAluno.atividade_id == atividade_id
    ).delete(synchronize_session=False)
    if not aluno_ids:
        return
    valid = {
        r[0]
        for r in db.query(Aluno.id).filter(Aluno.turma_id == turma_id, Aluno.id.in_(aluno_ids)).all()
    }
    for aid in valid:
        db.add(ProfessorAtividadeH5PAluno(atividade_id=atividade_id, aluno_id=aid))


@app.get("/professor")
def professor_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    from app.services.live_support_service import LiveSupportService
    from app.services.descriptor_performance_service import DescriptorPerformanceService

    stats = DashboardService().get_professor_stats(db)
    professor_turmas = _professor_turmas_list(db, current_user.id)
    selected_turma_id, turma_all = _resolve_professor_turma_selection(
        professor_turmas, request.query_params.get("turma_id")
    )
    turma_ids_prof = [t.id for t in professor_turmas]
    turma_query_suffix = _professor_turma_query_suffix(
        bool(professor_turmas), turma_all, selected_turma_id
    )
    live_support = LiveSupportService(db)

    dsvc = DescriptorPerformanceService()
    if turma_all:
        aluno_ids = dsvc.aluno_ids_for_turmas(db, turma_ids_prof)
        descritores_rows = dsvc.aggregates_for_alunos(db, aluno_ids) if aluno_ids else []
        radar_alunos = dsvc.radar_alunos_turmas(db, turma_ids_prof)
        chat_duvidas = dsvc.top_chat_questions_for_turmas(db, turma_ids_prof, limit=8)
    else:
        aluno_ids = dsvc.aluno_ids_for_turma(db, selected_turma_id)
        descritores_rows = dsvc.aggregates_for_alunos(db, aluno_ids) if aluno_ids else []
        radar_alunos = dsvc.radar_alunos_turma(db, selected_turma_id)
        chat_duvidas = dsvc.top_chat_questions_for_turma(db, selected_turma_id, limit=8)
    pior = descritores_rows[0] if descritores_rows else None
    ia_alerta_ativo = bool(pior and pior["taxa_pct"] < 50 and pior["alunos_elegiveis"] > 0)

    from app.services import moodle_assignment_service as moodle_assign_svc

    moodle_cursos: list[dict] = []
    moodle_aviso: str | None = None
    moodle_cursos = moodle_assign_svc.list_assignments_for_professor(db, current_user.id)
    if moodle_assign_svc.catalog_never_synced(db):
        moodle_aviso = (
            "O catálogo de cursos Moodle ainda não foi sincronizado. "
            "Peça ao gestor para aceder a «Cursos Moodle (capacitação)» e sincronizar."
        )
    elif not moodle_cursos:
        moodle_aviso = "Nenhum curso de formação foi atribuído pelo gestor."

    return templates.TemplateResponse(
        request,
        "professor/dashboard.html",
        {
            "request": request,
            "stats": stats,
            "current_user": current_user,
            "professor_turmas": professor_turmas,
            "selected_turma_id": selected_turma_id,
            "turma_all": turma_all,
            "turma_query_suffix": turma_query_suffix,
            "upcoming_live_classes": live_support.list_live_classes_for_professor(current_user),
            "teacher_help_requests": live_support.list_teacher_help_requests(current_user),
            "descritores_rows": descritores_rows,
            "descritores_preview": descritores_rows[:5],
            "radar_alunos": radar_alunos[:12],
            "chat_duvidas": chat_duvidas,
            "ia_alerta_ativo": ia_alerta_ativo,
            "ia_alerta_descritor": pior,
            "moodle_cursos": moodle_cursos,
            "moodle_aviso": moodle_aviso,
            "MOODLE_URL": settings.MOODLE_URL.rstrip("/"),
        },
    )


@app.get("/professor/desempenho-descritores")
def professor_desempenho_descritores(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    from app.services.descriptor_performance_service import DescriptorPerformanceService

    professor_turmas = _professor_turmas_list(db, current_user.id)
    selected_turma_id, turma_all = _resolve_professor_turma_selection(
        professor_turmas, request.query_params.get("turma_id")
    )
    turma_ids_prof = [t.id for t in professor_turmas]
    turma_query_suffix = _professor_turma_query_suffix(
        bool(professor_turmas), turma_all, selected_turma_id
    )
    dsvc = DescriptorPerformanceService()
    if turma_all:
        aluno_ids = dsvc.aluno_ids_for_turmas(db, turma_ids_prof)
    else:
        aluno_ids = dsvc.aluno_ids_for_turma(db, selected_turma_id)
    rows = dsvc.aggregates_for_alunos(db, aluno_ids) if aluno_ids else []
    return templates.TemplateResponse(
        request,
        "professor/desempenho_descritores.html",
        {
            "request": request,
            "current_user": current_user,
            "professor_turmas": professor_turmas,
            "selected_turma_id": selected_turma_id,
            "turma_all": turma_all,
            "turma_query_suffix": turma_query_suffix,
            "descritores_rows": rows,
        },
    )


@app.get("/professor/radar-alunos")
def professor_radar_alunos(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    from app.services.descriptor_performance_service import DescriptorPerformanceService

    professor_turmas = _professor_turmas_list(db, current_user.id)
    selected_turma_id, turma_all = _resolve_professor_turma_selection(
        professor_turmas, request.query_params.get("turma_id")
    )
    turma_ids_prof = [t.id for t in professor_turmas]
    turma_query_suffix = _professor_turma_query_suffix(
        bool(professor_turmas), turma_all, selected_turma_id
    )
    dsvc = DescriptorPerformanceService()
    if turma_all:
        radar_alunos = dsvc.radar_alunos_turmas(db, turma_ids_prof)
    else:
        radar_alunos = dsvc.radar_alunos_turma(db, selected_turma_id)
    return templates.TemplateResponse(
        request,
        "professor/radar_alunos.html",
        {
            "request": request,
            "current_user": current_user,
            "professor_turmas": professor_turmas,
            "selected_turma_id": selected_turma_id,
            "turma_all": turma_all,
            "turma_query_suffix": turma_query_suffix,
            "radar_alunos": radar_alunos,
        },
    )


@app.get("/professor/chat-duvidas")
def professor_chat_duvidas(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    from app.services.descriptor_performance_service import DescriptorPerformanceService

    professor_turmas = _professor_turmas_list(db, current_user.id)
    selected_turma_id, turma_all = _resolve_professor_turma_selection(
        professor_turmas, request.query_params.get("turma_id")
    )
    turma_ids_prof = [t.id for t in professor_turmas]
    turma_query_suffix = _professor_turma_query_suffix(
        bool(professor_turmas), turma_all, selected_turma_id
    )
    dsvc = DescriptorPerformanceService()
    if turma_all:
        chat_duvidas = dsvc.top_chat_questions_for_turmas(db, turma_ids_prof, limit=30)
    else:
        chat_duvidas = dsvc.top_chat_questions_for_turma(db, selected_turma_id, limit=30)
    return templates.TemplateResponse(
        request,
        "professor/chat_duvidas.html",
        {
            "request": request,
            "current_user": current_user,
            "professor_turmas": professor_turmas,
            "selected_turma_id": selected_turma_id,
            "turma_all": turma_all,
            "turma_query_suffix": turma_query_suffix,
            "chat_duvidas": chat_duvidas,
        },
    )


def _professor_relatorio_turma_ids(
    db: Session, professor_user_id: int, turma_id_param: str | None
) -> list[int]:
    from fastapi import HTTPException

    allowed = sorted(_professor_allowed_turma_ids(db, professor_user_id))
    if not allowed:
        raise HTTPException(status_code=403, detail="Nenhuma turma vinculada ao professor")
    raw = (turma_id_param or "").strip()
    if raw in ("", "all"):
        return allowed
    try:
        tid = int(raw)
    except ValueError:
        return allowed
    if tid not in allowed:
        raise HTTPException(status_code=403, detail="Turma não permitida")
    return [tid]


def _professor_relatorio_dataset(
    db: Session,
    current_user: Usuario,
    tipo: str,
    target_turma_ids: list[int],
) -> tuple[str, list[str], list[list], str]:
    """Título, cabeçalhos, linhas (valores como str), stem do arquivo CSV."""
    from sqlalchemy import func

    from app.models.aluno import Aluno
    from app.models.gestao import Turma
    from app.models.h5p import AtividadeH5P, ProgressoH5P
    from app.models.professor_h5p import ProfessorAtividadeH5P, ProfessorProgressoH5P
    from app.models.user import Usuario
    from app.services.descriptor_performance_service import DescriptorPerformanceService

    dsvc = DescriptorPerformanceService()

    if tipo == "descritores_turma":
        aluno_ids = dsvc.aluno_ids_for_turmas(db, target_turma_ids)
        headers = [
            "codigo",
            "descricao",
            "taxa_conclusao_pct",
            "alunos_com_conclusao",
            "alunos_elegiveis",
            "score_medio",
        ]
        rows: list[list] = []
        for r in dsvc.aggregates_for_alunos(db, aluno_ids):
            rows.append(
                [
                    r["codigo"],
                    r["descricao"],
                    r["taxa_pct"],
                    r["alunos_com_conclusao"],
                    r["alunos_elegiveis"],
                    r["score_medio"] if r["score_medio"] is not None else "",
                ]
            )
        return "Desempenho por descritor SAEB", headers, rows, "professor_descritores_turma"

    if tipo == "alunos_progresso":
        headers = [
            "aluno_id",
            "nome",
            "turma",
            "atividades_h5p_trilha_concluidas",
            "total_atividades_h5p_trilha_ativas",
        ]
        total_atividades = (
            db.query(func.count(AtividadeH5P.id)).filter(AtividadeH5P.ativo == True).scalar() or 0
        )
        qrows = (
            db.query(Aluno, Usuario.nome, Turma.nome)
            .join(Usuario, Aluno.usuario_id == Usuario.id)
            .join(Turma, Aluno.turma_id == Turma.id)
            .filter(Aluno.turma_id.in_(target_turma_ids))
            .order_by(Turma.nome, Usuario.nome)
            .all()
        )
        rows = []
        for aluno, nome, turma_nome in qrows:
            concl = (
                db.query(func.count(ProgressoH5P.id))
                .filter(ProgressoH5P.aluno_id == aluno.id, ProgressoH5P.concluido == True)
                .scalar()
                or 0
            )
            rows.append([aluno.id, nome or "", turma_nome or "", int(concl), int(total_atividades)])
        return "Progresso dos alunos (trilha H5P)", headers, rows, "professor_alunos_progresso_trilha"

    if tipo == "atividades_professor_turma":
        headers = ["atividade_id", "titulo", "turma", "tipo", "ativo", "conclusoes"]
        q = (
            db.query(ProfessorAtividadeH5P, Turma.nome)
            .join(Turma, Turma.id == ProfessorAtividadeH5P.turma_id)
            .filter(ProfessorAtividadeH5P.professor_id == current_user.id)
            .filter(ProfessorAtividadeH5P.turma_id.in_(target_turma_ids))
            .order_by(ProfessorAtividadeH5P.created_at.desc())
        )
        rows = []
        for act, turma_nome in q.all():
            n_done = (
                db.query(func.count(ProfessorProgressoH5P.id))
                .filter(
                    ProfessorProgressoH5P.atividade_id == act.id,
                    ProfessorProgressoH5P.concluido == True,
                )
                .scalar()
                or 0
            )
            rows.append(
                [
                    act.id,
                    act.titulo,
                    turma_nome or "",
                    act.tipo,
                    "sim" if act.ativo else "nao",
                    int(n_done),
                ]
            )
        return "Atividades personalizadas do professor", headers, rows, "professor_atividades_personalizadas"

    from fastapi import HTTPException

    raise HTTPException(status_code=400, detail="Tipo de relatório inválido")


@app.get("/professor/relatorios")
def professor_relatorios_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    professor_turmas = _professor_turmas_list(db, current_user.id)
    selected_turma_id, turma_all = _resolve_professor_turma_selection(
        professor_turmas, request.query_params.get("turma_id")
    )
    turma_query_suffix = _professor_turma_query_suffix(
        bool(professor_turmas), turma_all, selected_turma_id
    )
    imprimir_raw = (request.query_params.get("imprimir") or "").strip().lower()
    modo_impressao = imprimir_raw in ("1", "true", "sim", "yes")
    tipo = (request.query_params.get("tipo") or "").strip()
    print_ctx: dict | None = None
    if modo_impressao:
        print_ctx = _professor_relatorio_print_context(db, current_user, request, tipo)
        if print_ctx is None:
            return RedirectResponse(
                url=_professor_relatorios_list_href(
                    bool(professor_turmas), turma_all, selected_turma_id
                ),
                status_code=303,
            )
    tpl_ctx: dict = {
        "request": request,
        "current_user": current_user,
        "professor_turmas": professor_turmas,
        "selected_turma_id": selected_turma_id,
        "turma_all": turma_all,
        "turma_query_suffix": turma_query_suffix,
        "modo_impressao": bool(print_ctx),
    }
    if print_ctx:
        tpl_ctx.update(print_ctx)
    return templates.TemplateResponse(request, "professor/relatorios.html", tpl_ctx)


_RELATORIO_PRINT_LABELS: dict[str, list[str]] = {
    "descritores_turma": [
        "Código",
        "Descrição",
        "Taxa conclusão %",
        "Alunos c/ conclusão",
        "Alunos elegíveis",
        "Score médio",
    ],
    "alunos_progresso": [
        "ID aluno",
        "Nome",
        "Turma",
        "Concluídas (trilha)",
        "Total atividades ativas",
    ],
    "atividades_professor_turma": [
        "ID",
        "Título",
        "Turma",
        "Tipo",
        "Ativa",
        "Conclusões",
    ],
}

_PROFESSOR_RELATORIO_TIPOS_IMPRESSAO = frozenset(
    {"descritores_turma", "alunos_progresso", "atividades_professor_turma"}
)


def _professor_relatorios_list_href(has_turmas: bool, turma_all: bool, selected_turma_id: int | None) -> str:
    suf = _professor_turma_query_suffix(has_turmas, turma_all, selected_turma_id)
    return f"/professor/relatorios{suf}" if suf else "/professor/relatorios"


def _professor_relatorio_print_context(
    db: Session,
    current_user: Usuario,
    request: Request,
    tipo: str,
) -> dict | None:
    if tipo not in _PROFESSOR_RELATORIO_TIPOS_IMPRESSAO:
        return None
    from datetime import datetime

    from app.models.gestao import Turma

    professor_turmas = _professor_turmas_list(db, current_user.id)
    selected_turma_id, turma_all = _resolve_professor_turma_selection(
        professor_turmas, request.query_params.get("turma_id")
    )
    has_turmas = bool(professor_turmas)
    back_href = _professor_relatorios_list_href(has_turmas, turma_all, selected_turma_id)

    q_turma = request.query_params.get("turma_id")
    target_turma_ids = _professor_relatorio_turma_ids(db, current_user.id, q_turma)
    titulo_doc, headers, rows, _ = _professor_relatorio_dataset(
        db, current_user, tipo, target_turma_ids
    )
    column_labels = _RELATORIO_PRINT_LABELS.get(tipo, headers)
    if len(target_turma_ids) > 1:
        escopo = "Todas as turmas vinculadas a você"
    else:
        t = db.query(Turma).filter(Turma.id == target_turma_ids[0]).first()
        escopo = f"Turma: {t.nome}" if t else "Turma selecionada"
    return {
        "report_title": titulo_doc,
        "report_subtitle": escopo,
        "column_labels": column_labels,
        "rows": rows,
        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "back_href": back_href,
        "report_author_label": "Professor(a)",
        "report_author_name": (current_user.nome or "").strip(),
        "report_kicker": "AVA MJ — Relatório",
    }


@app.get("/professor/relatorios/export.csv")
def professor_relatorios_export(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
    tipo: str = "descritores_turma",
    turma_id: str | None = None,
):
    import csv
    import io

    from fastapi.responses import StreamingResponse

    q_turma = turma_id if turma_id is not None else request.query_params.get("turma_id")
    target_turma_ids = _professor_relatorio_turma_ids(db, current_user.id, q_turma)
    _, headers, rows, stem = _professor_relatorio_dataset(db, current_user, tipo, target_turma_ids)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    data = "\ufeff" + output.getvalue()
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'},
    )


@app.get("/professor/relatorios/imprimir")
def professor_relatorios_imprimir(
    request: Request,
    tipo: str = "descritores_turma",
    turma_id: str | None = None,
):
    """Redireciona para a mesma URL de relatórios com modo impressão (legado / links externos)."""
    from urllib.parse import urlencode

    q: dict[str, str] = {"imprimir": "1", "tipo": tipo}
    tid = turma_id if turma_id is not None else request.query_params.get("turma_id")
    if tid is not None and str(tid).strip() != "":
        q["turma_id"] = str(tid).strip()
    return RedirectResponse(url=f"/professor/relatorios?{urlencode(q)}", status_code=302)


def _gestor_relatorio_imprimir_bundle(
    db: Session, escola_ids: list[int], tipo: str
) -> tuple[str, str, list[str], list[list]]:
    from app.models.aluno import Aluno
    from app.models.gestao import Escola, Turma
    from app.models.user import Usuario

    from app.services.descriptor_performance_service import DescriptorPerformanceService

    dsvc = DescriptorPerformanceService()
    scope_ids = escola_ids if escola_ids else None
    aluno_ids = dsvc.aluno_ids_for_escolas(db, scope_ids) if scope_ids else dsvc.aluno_ids_all(db)

    if tipo == "progresso_escolas":
        title = "Progresso por escola"
        subtitle = (
            "Escolas vinculadas ao seu perfil de gestor"
            if escola_ids
            else "Visão consolidada da rede (todas as escolas ativas)"
        )
        cols = ["ID", "Escola", "Alunos", "Engajamento %", "Média ativ. concluídas"]
        rows = [
            [
                r["escola_id"],
                r["escola_nome"],
                r["n_alunos"],
                r["engajamento_pct"],
                r["media_concluidas"],
            ]
            for r in dsvc.escolas_engajamento(db, scope_ids)
        ]
        return title, subtitle, cols, rows
    if tipo == "descritores":
        title = "Desempenho por descritor SAEB"
        subtitle = "Alunos no escopo do gestor"
        cols = ["Código", "Descrição", "Taxa conclusão %", "Alunos c/ conclusão", "Alunos elegíveis", "Score médio"]
        rows = []
        for r in dsvc.aggregates_for_alunos(db, aluno_ids):
            rows.append(
                [
                    r["codigo"],
                    r["descricao"],
                    r["taxa_pct"],
                    r["alunos_com_conclusao"],
                    r["alunos_elegiveis"],
                    r["score_medio"] if r["score_medio"] is not None else "",
                ]
            )
        return title, subtitle, cols, rows
    if tipo == "risco_alunos":
        title = "Alunos em risco"
        subtitle = "Alunos com nível de risco diferente de baixo"
        cols = ["ID aluno", "Nome", "Turma", "Escola", "Nível risco", "Ano"]
        q = (
            db.query(Aluno, Usuario.nome, Turma.nome, Escola.nome)
            .join(Usuario, Aluno.usuario_id == Usuario.id)
            .outerjoin(Turma, Aluno.turma_id == Turma.id)
            .outerjoin(Escola, Turma.escola_id == Escola.id)
        )
        if scope_ids:
            q = q.filter(Turma.escola_id.in_(scope_ids))
        rows = []
        for aluno, nome, turma_nome, escola_nome in q.all():
            if (aluno.nivel_risco or "").upper() != "BAIXO":
                rows.append(
                    [
                        aluno.id,
                        nome or "",
                        turma_nome or "",
                        escola_nome or "",
                        aluno.nivel_risco or "",
                        aluno.ano_escolar or "",
                    ]
                )
        return title, subtitle, cols, rows
    raise HTTPException(400, "Tipo de relatório inválido")


def _coordenador_relatorio_imprimir_bundle(
    db: Session, escola_id: int, tipo: str
) -> tuple[str, str, list[str], list[list]]:
    if tipo == "monitoramento_turmas":
        title = "Monitoramento por turma"
        subtitle = "Adesão à trilha H5P e proficiência média"
        cols = ["Turma", "Professor", "Adesão %", "Proficiência média", "Status"]
        rows = [
            [r["turma"], r["professor"], r["adesao_pct"], r["proficiencia"], r["status"]]
            for r in _coordenador_turmas_monitoramento(db, escola_id)
        ]
        return title, subtitle, cols, rows
    if tipo == "risco_turmas":
        title = "Mapa de risco por turma"
        subtitle = "Alunos com risco pedagógico diferente de baixo"
        cols = ["Turma", "Alunos em risco", "% da turma"]
        rows = [[r["turma"], r["qtd_risco"], r["pct"]] for r in _coordenador_riscos_por_turma(db, escola_id)]
        return title, subtitle, cols, rows
    raise HTTPException(400, "Tipo de relatório inválido")


_GESTOR_REL_TIPOS_IMPRESSAO = frozenset({"progresso_escolas", "descritores", "risco_alunos"})
_COORD_REL_TIPOS_IMPRESSAO = frozenset({"monitoramento_turmas", "risco_turmas"})


def _gestor_relatorio_print_context(db: Session, current_user: Usuario, tipo: str) -> dict | None:
    if tipo not in _GESTOR_REL_TIPOS_IMPRESSAO:
        return None
    from datetime import datetime

    escola_ids = _gestor_escola_ids(db, current_user.id)
    titulo, escopo, cols, rows = _gestor_relatorio_imprimir_bundle(db, escola_ids, tipo)
    return {
        "report_title": titulo,
        "report_subtitle": escopo,
        "column_labels": cols,
        "rows": rows,
        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "back_href": "/gestor/relatorios",
        "report_author_label": "Gestor(a)",
        "report_author_name": (current_user.nome or "").strip(),
        "report_kicker": "AVA MJ — Relatório estratégico",
    }


def _coordenador_relatorio_print_context(db: Session, current_user: Usuario, tipo: str) -> dict | None:
    if tipo not in _COORD_REL_TIPOS_IMPRESSAO:
        return None
    from datetime import datetime

    from app.models.gestao import Escola
    from app.models.relacoes import CoordenadorEscola

    rel = (
        db.query(CoordenadorEscola)
        .join(Escola, CoordenadorEscola.escola_id == Escola.id)
        .filter(CoordenadorEscola.coordenador_id == current_user.id)
        .first()
    )
    if not rel or not rel.escola_id:
        return None
    escola = db.query(Escola).filter(Escola.id == rel.escola_id).first()
    titulo, _, cols, rows = _coordenador_relatorio_imprimir_bundle(db, rel.escola_id, tipo)
    escopo = f"Escola: {escola.nome}" if escola else "Escola vinculada"
    return {
        "report_title": titulo,
        "report_subtitle": escopo,
        "column_labels": cols,
        "rows": rows,
        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "back_href": "/coordenador/relatorios",
        "report_author_label": "Coordenador(a)",
        "report_author_name": (current_user.nome or "").strip(),
        "report_kicker": "AVA MJ — Relatório de coordenação",
    }


def _professor_allowed_turma_ids(db: Session, professor_user_id: int) -> set[int]:
    from app.models.relacoes import ProfessorTurma

    rows = db.query(ProfessorTurma.turma_id).filter(ProfessorTurma.professor_id == professor_user_id).all()
    return {r[0] for r in rows}


@app.get("/professor/atividades")
def professor_atividades_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from sqlalchemy import func

    from app.models.professor_h5p import ProfessorAtividadeH5P, ProfessorAtividadeH5PAluno
    from app.models.gestao import Turma
    from app.models.h5p import AtividadeH5P
    from app.models.gestao import Trilha

    pairs = (
        db.query(ProfessorAtividadeH5P, Turma.nome)
        .join(Turma, Turma.id == ProfessorAtividadeH5P.turma_id)
        .filter(ProfessorAtividadeH5P.professor_id == current_user.id)
        .order_by(ProfessorAtividadeH5P.created_at.desc())
        .all()
    )
    act_ids = [a.id for a, _ in pairs]
    dest_counts: dict[int, int] = {}
    if act_ids:
        for aid, cnt in (
            db.query(
                ProfessorAtividadeH5PAluno.atividade_id,
                func.count(ProfessorAtividadeH5PAluno.id),
            )
            .filter(ProfessorAtividadeH5PAluno.atividade_id.in_(act_ids))
            .group_by(ProfessorAtividadeH5PAluno.atividade_id)
            .all()
        ):
            dest_counts[aid] = int(cnt)
    atividades = [(a, tn, dest_counts.get(a.id, 0)) for a, tn in pairs]
    atividades_trilha_geral = []
    if bool(getattr(current_user, "permite_cadastro_trilha_geral", False)):
        professor_turmas = _professor_turmas_list(db, current_user.id)
        anos_permitidos = sorted({t.ano_escolar for t in professor_turmas if t.ano_escolar is not None})
        if anos_permitidos:
            atividades_trilha_geral = (
                db.query(AtividadeH5P, Trilha.nome)
                .join(Trilha, Trilha.id == AtividadeH5P.trilha_id)
                .filter(
                    AtividadeH5P.ativo,
                    Trilha.ano_escolar.in_(anos_permitidos),
                )
                .order_by(AtividadeH5P.created_at.desc())
                .all()
            )
    nav = _professor_nav_context(db, current_user.id, request)
    return templates.TemplateResponse(
        request,
        "professor/atividades_h5p_list.html",
        {
            **nav,
            "request": request,
            "current_user": current_user,
            "atividades": atividades,
            "atividades_trilha_geral": atividades_trilha_geral,
            "permite_trilha_geral": bool(getattr(current_user, "permite_cadastro_trilha_geral", False)),
        },
    )


@app.get("/professor/atividades/nova")
def professor_atividades_nova(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from app.repositories.gestao_repository import TrilhaRepository
    from app.repositories.saeb_repository import DescritorRepository

    turmas = _professor_turmas_list(db, current_user.id)
    anos = sorted({t.ano_escolar for t in turmas if t.ano_escolar is not None})
    trilhas = []
    for ano in anos:
        trilhas.extend(TrilhaRepository().listar(db, ano_escolar=ano))
    descritores = DescritorRepository().listar(db)
    alunos_destino = _alunos_destino_options(db, current_user.id)
    nav = _professor_nav_context(db, current_user.id, request)
    return templates.TemplateResponse(
        request,
        "professor/atividade_h5p_form.html",
        {
            **nav,
            "request": request,
            "current_user": current_user,
            "turmas": turmas,
            "trilhas": trilhas,
            "descritores": descritores,
            "alunos_destino": alunos_destino,
            "permite_trilha_geral": bool(getattr(current_user, "permite_cadastro_trilha_geral", False)),
        },
    )


@app.post("/professor/atividades/nova")
async def professor_atividades_criar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from app.models.professor_h5p import ProfessorAtividadeH5P
    from app.schemas.h5p_schema import AtividadeH5PCreate
    from app.repositories.h5p_repository import AtividadeH5PRepository
    from app.repositories.gestao_repository import TrilhaRepository
    from app.services.h5p_upload_service import save_h5p_upload

    form = await request.form()
    titulo = (form.get("titulo") or "").strip()
    tipo = (form.get("tipo") or "outro").strip()
    turma_id_raw = form.get("turma_id")
    descritor_id_raw = form.get("descritor_id")
    trilha_id_raw = form.get("trilha_id")
    destino_tipo = (form.get("destino_tipo") or "turma_toda").strip()
    arquivo_h5p = form.get("arquivo_h5p")

    if destino_tipo == "trilha":
        if not bool(getattr(current_user, "permite_cadastro_trilha_geral", False)):
            return RedirectResponse(url="/professor/atividades/nova?erro=sem_trilha_geral", status_code=303)
        modo = "trilha_geral"
    else:
        modo = "personalizada_turma"
        if destino_tipo not in ("turma_toda", "alunos"):
            destino_tipo = "turma_toda"

    if not titulo or not arquivo_h5p:
        return RedirectResponse(url="/professor/atividades/nova?erro=campos", status_code=303)

    allowed_turmas = _professor_allowed_turma_ids(db, current_user.id)
    try:
        turma_id = int(str(turma_id_raw))
    except Exception:
        turma_id = None
    if turma_id not in allowed_turmas:
        return RedirectResponse(url="/professor/atividades/nova?erro=turma_invalida", status_code=303)

    desc_id = int(str(descritor_id_raw)) if descritor_id_raw and str(descritor_id_raw).strip() else None
    trilha_id = int(str(trilha_id_raw)) if trilha_id_raw and str(trilha_id_raw).strip() else None
    rel_path = save_h5p_upload(db, arquivo_h5p, titulo, trilha_id=trilha_id if modo == "trilha_geral" else None, turma_id=turma_id)

    if modo == "trilha_geral":
        if not bool(getattr(current_user, "permite_cadastro_trilha_geral", False)) or not trilha_id:
            return RedirectResponse(url="/professor/atividades/nova?erro=trilha_invalida", status_code=303)
        trilha = TrilhaRepository().get(db, trilha_id)
        turma = next((t for t in _professor_turmas_list(db, current_user.id) if t.id == turma_id), None)
        if not trilha or not turma:
            return RedirectResponse(url="/professor/atividades/nova?erro=trilha_invalida", status_code=303)
        if trilha.ano_escolar and turma.ano_escolar and trilha.ano_escolar != turma.ano_escolar:
            return RedirectResponse(url="/professor/atividades/nova?erro=ano_invalido", status_code=303)
        AtividadeH5PRepository().create(
            db,
            AtividadeH5PCreate(
                titulo=titulo,
                tipo=tipo,
                path_ou_json=rel_path,
                trilha_id=trilha_id,
                descritor_id=desc_id,
                ordem=0,
                ativo=True,
            ),
        )
        return RedirectResponse(url="/professor/atividades?ok=trilha", status_code=303)

    aluno_set = _parse_aluno_ids_from_form(form)
    if destino_tipo == "alunos" and not aluno_set:
        return RedirectResponse(url="/professor/atividades/nova?erro=alunos_obrigatorio", status_code=303)
    if destino_tipo == "turma_toda":
        aluno_set = set()

    obj = ProfessorAtividadeH5P(
        professor_id=current_user.id,
        turma_id=turma_id,
        titulo=titulo,
        tipo=tipo,
        path_ou_json=rel_path,
        descritor_id=desc_id,
        ativo=True,
    )
    db.add(obj)
    db.flush()
    _sync_professor_atividade_alvos(db, obj.id, turma_id, aluno_set)
    db.commit()
    return RedirectResponse(url="/professor/atividades?ok=criado", status_code=303)


@app.post("/professor/atividades/{id}/deletar")
def professor_atividades_deletar(
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from app.models.professor_h5p import ProfessorAtividadeH5P, ProfessorProgressoH5P
    from app.routers.admin_pages_router import _resolve_h5p_storage_target
    import shutil

    obj = (
        db.query(ProfessorAtividadeH5P)
        .filter(ProfessorAtividadeH5P.id == id, ProfessorAtividadeH5P.professor_id == current_user.id)
        .first()
    )
    if obj:
        target = _resolve_h5p_storage_target(obj.path_ou_json or "")
        if target and target.exists():
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
        db.query(ProfessorProgressoH5P).filter(ProfessorProgressoH5P.atividade_id == obj.id).delete()
        db.delete(obj)
        db.commit()
    return RedirectResponse(url="/professor/atividades", status_code=303)


@app.get("/professor/atividades/{id}/editar")
def professor_atividade_editar_form(
    id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from app.models.aluno import Aluno
    from app.models.professor_h5p import ProfessorAtividadeH5P
    from app.models.user import Usuario
    from app.repositories.saeb_repository import DescritorRepository

    atividade = (
        db.query(ProfessorAtividadeH5P)
        .filter(ProfessorAtividadeH5P.id == id, ProfessorAtividadeH5P.professor_id == current_user.id)
        .first()
    )
    if not atividade:
        return RedirectResponse(url="/professor/atividades?erro=nao_encontrada", status_code=303)
    descritores = DescritorRepository().listar(db)
    alunos_rows = (
        db.query(Aluno, Usuario.nome, Usuario.avatar_url)
        .join(Usuario, Aluno.usuario_id == Usuario.id)
        .filter(Aluno.turma_id == atividade.turma_id)
        .order_by(Usuario.nome)
        .all()
    )
    alunos_turma = []
    for a, n, av in alunos_rows:
        label = (n or "").strip() or f"Aluno #{a.id}"
        partes = label.split()
        if len(partes) >= 2:
            ini = (partes[0][0] + partes[-1][0]).upper()
        elif len(partes) == 1 and len(partes[0]) >= 2:
            ini = partes[0][:2].upper()
        else:
            ini = "AL"
        alunos_turma.append(
            {
                "id": a.id,
                "nome": label,
                "ano_escolar": a.ano_escolar,
                "avatar_url": (av or "").strip(),
                "iniciais": ini,
            }
        )
    selected_aluno_ids = [x.aluno_id for x in (atividade.alvos_alunos or [])]
    nav = _professor_nav_context(db, current_user.id, request)
    destino_edicao_default = "alunos_especificos" if selected_aluno_ids else "turma_toda"
    return templates.TemplateResponse(
        request,
        "professor/atividade_h5p_edit_form.html",
        {
            **nav,
            "request": request,
            "current_user": current_user,
            "atividade": atividade,
            "descritores": descritores,
            "alunos_turma": alunos_turma,
            "selected_aluno_ids": selected_aluno_ids,
            "destino_edicao_default": destino_edicao_default,
            "scope": "turma",
        },
    )


@app.post("/professor/atividades/{id}/editar")
async def professor_atividade_editar(
    id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from app.models.professor_h5p import ProfessorAtividadeH5P
    from app.routers.admin_pages_router import _resolve_h5p_storage_target
    from app.services.h5p_upload_service import save_h5p_upload
    import shutil

    atividade = (
        db.query(ProfessorAtividadeH5P)
        .filter(ProfessorAtividadeH5P.id == id, ProfessorAtividadeH5P.professor_id == current_user.id)
        .first()
    )
    if not atividade:
        return RedirectResponse(url="/professor/atividades?erro=nao_encontrada", status_code=303)

    form = await request.form()
    atividade.titulo = (form.get("titulo") or atividade.titulo).strip() or atividade.titulo
    atividade.tipo = (form.get("tipo") or atividade.tipo).strip() or atividade.tipo
    desc_raw = form.get("descritor_id")
    atividade.descritor_id = int(str(desc_raw)) if desc_raw and str(desc_raw).strip() else None
    atividade.ativo = (form.get("ativo") or "").lower() == "true"
    arquivo_h5p = form.get("arquivo_h5p")
    if arquivo_h5p and getattr(arquivo_h5p, "filename", ""):
        old_target = _resolve_h5p_storage_target(atividade.path_ou_json or "")
        atividade.path_ou_json = save_h5p_upload(db, arquivo_h5p, atividade.titulo, turma_id=atividade.turma_id)
        if old_target and old_target.exists():
            if old_target.is_dir():
                shutil.rmtree(old_target, ignore_errors=True)
            else:
                old_target.unlink(missing_ok=True)
    destino_edicao = (form.get("destino_edicao") or "turma_toda").strip()
    aluno_set = _parse_aluno_ids_from_form(form)
    if destino_edicao == "alunos_especificos":
        if not aluno_set:
            return RedirectResponse(
                url=f"/professor/atividades/{id}/editar?erro=alunos_obrigatorio", status_code=303
            )
    else:
        aluno_set = set()
    _sync_professor_atividade_alvos(db, atividade.id, atividade.turma_id, aluno_set)
    db.commit()
    return RedirectResponse(url="/professor/atividades?ok=editado", status_code=303)


@app.get("/professor/atividades/trilha-geral/{id}/editar")
def professor_atividade_trilha_editar_form(
    id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    if not bool(getattr(current_user, "permite_cadastro_trilha_geral", False)):
        return RedirectResponse(url="/professor/atividades?erro=sem_permissao", status_code=303)
    from app.models.h5p import AtividadeH5P
    from app.models.gestao import Trilha
    from app.repositories.gestao_repository import TrilhaRepository
    from app.repositories.saeb_repository import DescritorRepository

    atividade = db.query(AtividadeH5P).filter(AtividadeH5P.id == id).first()
    if not atividade or not atividade.trilha_id:
        return RedirectResponse(url="/professor/atividades?erro=nao_encontrada", status_code=303)

    professor_turmas = _professor_turmas_list(db, current_user.id)
    anos_permitidos = {t.ano_escolar for t in professor_turmas if t.ano_escolar is not None}
    trilha = db.query(Trilha).filter(Trilha.id == atividade.trilha_id).first()
    if not trilha or trilha.ano_escolar not in anos_permitidos:
        return RedirectResponse(url="/professor/atividades?erro=sem_permissao", status_code=303)

    trilhas = []
    for ano in sorted(anos_permitidos):
        trilhas.extend(TrilhaRepository().listar(db, ano_escolar=ano))
    descritores = DescritorRepository().listar(db)
    nav = _professor_nav_context(db, current_user.id, request)
    return templates.TemplateResponse(
        request,
        "professor/atividade_h5p_edit_form.html",
        {
            **nav,
            "request": request,
            "current_user": current_user,
            "atividade": atividade,
            "descritores": descritores,
            "trilhas": trilhas,
            "scope": "trilha_geral",
        },
    )


@app.post("/professor/atividades/trilha-geral/{id}/editar")
async def professor_atividade_trilha_editar(
    id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    if not bool(getattr(current_user, "permite_cadastro_trilha_geral", False)):
        return RedirectResponse(url="/professor/atividades?erro=sem_permissao", status_code=303)
    from app.models.h5p import AtividadeH5P
    from app.models.gestao import Trilha
    from app.routers.admin_pages_router import _resolve_h5p_storage_target
    from app.services.h5p_upload_service import save_h5p_upload
    import shutil

    atividade = db.query(AtividadeH5P).filter(AtividadeH5P.id == id).first()
    if not atividade or not atividade.trilha_id:
        return RedirectResponse(url="/professor/atividades?erro=nao_encontrada", status_code=303)

    professor_turmas = _professor_turmas_list(db, current_user.id)
    anos_permitidos = {t.ano_escolar for t in professor_turmas if t.ano_escolar is not None}
    trilha_atual = db.query(Trilha).filter(Trilha.id == atividade.trilha_id).first()
    if not trilha_atual or trilha_atual.ano_escolar not in anos_permitidos:
        return RedirectResponse(url="/professor/atividades?erro=sem_permissao", status_code=303)

    form = await request.form()
    atividade.titulo = (form.get("titulo") or atividade.titulo).strip() or atividade.titulo
    atividade.tipo = (form.get("tipo") or atividade.tipo).strip() or atividade.tipo
    desc_raw = form.get("descritor_id")
    atividade.descritor_id = int(str(desc_raw)) if desc_raw and str(desc_raw).strip() else None
    atividade.ativo = (form.get("ativo") or "").lower() == "true"
    trilha_raw = form.get("trilha_id")
    if trilha_raw and str(trilha_raw).strip():
        nova_trilha_id = int(str(trilha_raw))
        nova_trilha = db.query(Trilha).filter(Trilha.id == nova_trilha_id).first()
        if nova_trilha and nova_trilha.ano_escolar in anos_permitidos:
            atividade.trilha_id = nova_trilha_id
    arquivo_h5p = form.get("arquivo_h5p")
    if arquivo_h5p and getattr(arquivo_h5p, "filename", ""):
        old_target = _resolve_h5p_storage_target(atividade.path_ou_json or "")
        atividade.path_ou_json = save_h5p_upload(db, arquivo_h5p, atividade.titulo, trilha_id=atividade.trilha_id)
        if old_target and old_target.exists():
            if old_target.is_dir():
                shutil.rmtree(old_target, ignore_errors=True)
            else:
                old_target.unlink(missing_ok=True)
    db.commit()
    return RedirectResponse(url="/professor/atividades?ok=editado", status_code=303)


@app.post("/professor/atividades/trilha-geral/{id}/deletar")
def professor_atividade_trilha_deletar(
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    if not bool(getattr(current_user, "permite_cadastro_trilha_geral", False)):
        return RedirectResponse(url="/professor/atividades?erro=sem_permissao", status_code=303)
    from app.models.h5p import AtividadeH5P
    from app.models.gestao import Trilha
    from app.routers.admin_pages_router import _remove_atividade_h5p_com_arquivos

    atividade = db.query(AtividadeH5P).filter(AtividadeH5P.id == id).first()
    if not atividade or not atividade.trilha_id:
        return RedirectResponse(url="/professor/atividades?erro=nao_encontrada", status_code=303)
    trilha = db.query(Trilha).filter(Trilha.id == atividade.trilha_id).first()
    professor_turmas = _professor_turmas_list(db, current_user.id)
    anos_permitidos = {t.ano_escolar for t in professor_turmas if t.ano_escolar is not None}
    if not trilha or trilha.ano_escolar not in anos_permitidos:
        return RedirectResponse(url="/professor/atividades?erro=sem_permissao", status_code=303)
    _remove_atividade_h5p_com_arquivos(db, id)
    return RedirectResponse(url="/professor/atividades?ok=deletado", status_code=303)


@app.get("/professor/descritores")
def professor_descritores_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from app.repositories.saeb_repository import DescritorRepository

    descritores = DescritorRepository().listar(db)
    nav = _professor_nav_context(db, current_user.id, request)
    return templates.TemplateResponse(
        request,
        "professor/descritores_list.html",
        {**nav, "request": request, "current_user": current_user, "descritores": descritores},
    )


@app.get("/professor/descritores/novo")
def professor_descritores_novo(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    nav = _professor_nav_context(db, current_user.id, request)
    return templates.TemplateResponse(
        request,
        "professor/descritor_form.html",
        {**nav, "request": request, "current_user": current_user, "descritor": None},
    )


@app.get("/professor/descritores/{id}/editar")
def professor_descritores_editar(
    id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from app.repositories.saeb_repository import DescritorRepository

    descritor = DescritorRepository().get(db, id)
    if not descritor:
        return RedirectResponse(url="/professor/descritores", status_code=302)
    nav = _professor_nav_context(db, current_user.id, request)
    return templates.TemplateResponse(
        request,
        "professor/descritor_form.html",
        {**nav, "request": request, "current_user": current_user, "descritor": descritor},
    )


@app.post("/professor/descritores/novo")
async def professor_descritores_criar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from app.repositories.saeb_repository import DescritorRepository

    form = await request.form()
    codigo = (form.get("codigo") or "").strip()
    descricao = (form.get("descricao") or "").strip()
    disciplina = (form.get("disciplina") or "LP").strip().upper()
    if codigo and descricao and disciplina in {"LP", "MAT"}:
        DescritorRepository().create(db, codigo, descricao, disciplina)
    return RedirectResponse(url="/professor/descritores", status_code=303)


@app.post("/professor/descritores/{id}/editar")
async def professor_descritores_atualizar(
    id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from app.repositories.saeb_repository import DescritorRepository

    form = await request.form()
    codigo = (form.get("codigo") or "").strip()
    descricao = (form.get("descricao") or "").strip()
    disciplina = (form.get("disciplina") or "LP").strip().upper()
    if codigo and descricao and disciplina in {"LP", "MAT"}:
        DescritorRepository().update(db, id, codigo=codigo, descricao=descricao, disciplina=disciplina)
    return RedirectResponse(url="/professor/descritores", status_code=303)


@app.get("/professor/perfil")
def professor_perfil_get(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    nav = _professor_nav_context(db, current_user.id, request)
    return _perfil_form_response(
        request,
        current_user,
        "/professor",
        template_name="professor/perfil_form.html",
        extra=nav,
    )


@app.post("/professor/perfil")
async def professor_perfil_post(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    return await _perfil_salvar(request, db, current_user, "/professor/perfil")


@app.get("/aluno/perfil")
def aluno_perfil_get(request: Request):
    return RedirectResponse(url="/aluno/configuracoes", status_code=302)


@app.post("/aluno/perfil")
async def aluno_perfil_post(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.ALUNO)),
):
    return await _perfil_salvar(request, db, current_user, "/aluno/configuracoes")


@app.get("/gestor/perfil")
def gestor_perfil_get(
    request: Request,
    current_user: Usuario = Depends(require_role_redirect(UserRole.GESTOR)),
):
    return _perfil_form_response(
        request,
        current_user,
        "/gestor",
        template_name="gestor/perfil_form.html",
    )


@app.post("/gestor/perfil")
async def gestor_perfil_post(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.GESTOR)),
):
    return await _perfil_salvar(request, db, current_user, "/gestor/perfil")


@app.get("/coordenador/perfil")
def coordenador_perfil_get(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.COORDENADOR)),
):
    return _perfil_form_response(
        request,
        current_user,
        "/coordenador",
        template_name="coordenador/perfil_form.html",
        extra=_coordenador_layout_context(db, current_user),
    )


@app.post("/coordenador/perfil")
async def coordenador_perfil_post(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.COORDENADOR)),
):
    return await _perfil_salvar(request, db, current_user, "/coordenador/perfil")


@app.get("/admin/perfil")
def admin_perfil_get(
    request: Request,
    current_user: Usuario = Depends(require_admin_redirect),
):
    return _perfil_form_response(request, current_user, "/admin")


@app.post("/admin/perfil")
async def admin_perfil_post(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    return await _perfil_salvar(request, db, current_user, "/admin/perfil")


def _gestor_escola_ids(db: Session, gestor_user_id: int) -> list[int]:
    """IDs das escolas vinculadas ao gestor. Lista vazia = não há vínculo; usar todas as escolas."""
    from app.models.relacoes import GestorEscola

    rows = db.query(GestorEscola.escola_id).filter(GestorEscola.gestor_id == gestor_user_id).all()
    return [r[0] for r in rows]


@app.get("/gestor")
def gestor_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.GESTOR)),
):
    from app.services.descriptor_performance_service import DescriptorPerformanceService

    stats = DashboardService().get_gestor_stats(db)
    escola_ids = _gestor_escola_ids(db, current_user.id)
    dsvc = DescriptorPerformanceService()
    if escola_ids:
        aluno_ids = dsvc.aluno_ids_for_escolas(db, escola_ids)
        escolas_tbl = dsvc.escolas_engajamento(db, escola_ids)
    else:
        aluno_ids = dsvc.aluno_ids_all(db)
        escolas_tbl = dsvc.escolas_engajamento(db, None)
    return templates.TemplateResponse(
        request,
        "gestor/dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "stats": stats,
            "escolas_engajamento": escolas_tbl,
            "descritores_resumo": dsvc.aggregates_for_alunos(db, aluno_ids)[:6],
        },
    )


@app.get("/gestor/proficiencia")
def gestor_proficiencia(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.GESTOR)),
):
    from app.services.descriptor_performance_service import DescriptorPerformanceService

    escola_ids = _gestor_escola_ids(db, current_user.id)
    dsvc = DescriptorPerformanceService()
    rows = dsvc.escolas_engajamento(db, escola_ids if escola_ids else None)
    return templates.TemplateResponse(
        request,
        "gestor/proficiencia.html",
        {"request": request, "current_user": current_user, "escolas_rows": rows},
    )


@app.get("/gestor/alertas")
def gestor_alertas(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.GESTOR)),
):
    from app.services.descriptor_performance_service import DescriptorPerformanceService

    escola_ids = _gestor_escola_ids(db, current_user.id)
    dsvc = DescriptorPerformanceService()
    rows = dsvc.escolas_engajamento(db, escola_ids if escola_ids else None)
    alertas = [r for r in rows if r["engajamento_pct"] < 40 and r["n_alunos"] > 0]
    return templates.TemplateResponse(
        request,
        "gestor/alertas.html",
        {"request": request, "current_user": current_user, "alertas": alertas},
    )


@app.get("/gestor/moodle/cursos")
def gestor_moodle_cursos_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.GESTOR)),
):
    from app.services import moodle_assignment_service as moodle_assign_svc

    escola_ids = _gestor_escola_ids(db, current_user.id)
    prof_ids = moodle_assign_svc.professor_usuario_ids_in_scope(db, escola_ids)
    if prof_ids:
        professores = (
            db.query(Usuario).filter(Usuario.id.in_(prof_ids)).order_by(Usuario.nome).all()
        )
    else:
        professores = []
    catalog = moodle_assign_svc.list_courses_catalog(db)
    assignments = moodle_assign_svc.list_assignments_for_gestor_view(db, escola_ids)
    qp = request.query_params
    return templates.TemplateResponse(
        request,
        "gestor/moodle_cursos.html",
        {
            "request": request,
            "current_user": current_user,
            "professores": professores,
            "moodle_catalog": catalog,
            "moodle_assignments": assignments,
            "flash_ok": (qp.get("ok") or "").strip(),
            "flash_err": (qp.get("err") or "").strip(),
            "MOODLE_URL": settings.MOODLE_URL.rstrip("/"),
            "moodle_auto_enrol": settings.MOODLE_AUTO_ENROL_ON_ASSIGN,
        },
    )


@app.post("/gestor/moodle/cursos/sync")
async def gestor_moodle_cursos_sync(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.GESTOR)),
):
    from urllib.parse import quote

    from app.services import moodle_assignment_service as moodle_assign_svc

    _ = request  # form POST sem campos
    n, err = moodle_assign_svc.sync_catalog_from_moodle(db)
    if err:
        return RedirectResponse(
            url=f"/gestor/moodle/cursos?err={quote(err)}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/gestor/moodle/cursos?ok=sync_{n}",
        status_code=303,
    )


@app.post("/gestor/moodle/cursos/atribuir")
async def gestor_moodle_cursos_atribuir(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.GESTOR)),
):
    from urllib.parse import quote

    from app.services import moodle_assignment_service as moodle_assign_svc

    form = await request.form()
    try:
        pid = int(form.get("professor_usuario_id") or 0)
        cid = int(form.get("moodle_course_id") or 0)
    except (TypeError, ValueError):
        return RedirectResponse(
            url="/gestor/moodle/cursos?err=" + quote("Dados inválidos."),
            status_code=303,
        )
    obs = (form.get("observacao") or "").strip() or None
    ok, msg = moodle_assign_svc.create_assignment(
        db,
        gestor=current_user,
        professor_usuario_id=pid,
        moodle_course_id=cid,
        observacao=obs,
    )
    if not ok:
        return RedirectResponse(
            url=f"/gestor/moodle/cursos?err={quote(msg)}",
            status_code=303,
        )
    return RedirectResponse(url="/gestor/moodle/cursos?ok=atribuido", status_code=303)


@app.post("/gestor/moodle/cursos/revogar/{assignment_id}")
async def gestor_moodle_cursos_revogar(
    assignment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.GESTOR)),
):
    from urllib.parse import quote

    from app.services import moodle_assignment_service as moodle_assign_svc

    _ = request
    ok, msg = moodle_assign_svc.revoke_assignment(
        db, gestor=current_user, assignment_id=assignment_id
    )
    if not ok:
        return RedirectResponse(
            url=f"/gestor/moodle/cursos?err={quote(msg)}",
            status_code=303,
        )
    return RedirectResponse(url="/gestor/moodle/cursos?ok=revogado", status_code=303)


@app.get("/moodle/course-image/{moodle_course_id}")
def moodle_course_image_proxy(
    moodle_course_id: int,
    db: Session = Depends(get_db),
):
    from app.models.moodle_gestao import MoodleCourseCatalog
    from app.services.moodle_ws_service import MoodleWsService

    course = (
        db.query(MoodleCourseCatalog)
        .filter(MoodleCourseCatalog.moodle_course_id == moodle_course_id)
        .one_or_none()
    )
    if not course or not (course.image_url or "").strip():
        raise HTTPException(status_code=404, detail="Imagem do curso não encontrada")
    try:
        data, content_type = MoodleWsService().fetch_file_content(course.image_url)
    except Exception as exc:
        logger.warning("Falha ao carregar imagem Moodle course=%s: %s", moodle_course_id, exc)
        raise HTTPException(status_code=502, detail="Falha ao carregar imagem do Moodle")
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=900"},
    )


@app.get("/gestor/relatorios")
def gestor_relatorios_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.GESTOR)),
):
    imprimir_raw = (request.query_params.get("imprimir") or "").strip().lower()
    modo_impressao = imprimir_raw in ("1", "true", "sim", "yes")
    tipo = (request.query_params.get("tipo") or "").strip()
    print_ctx: dict | None = None
    if modo_impressao:
        print_ctx = _gestor_relatorio_print_context(db, current_user, tipo)
        if print_ctx is None:
            return RedirectResponse(url="/gestor/relatorios", status_code=303)
    tpl_ctx: dict = {
        "request": request,
        "current_user": current_user,
        "modo_impressao": bool(print_ctx),
    }
    if print_ctx:
        tpl_ctx.update(print_ctx)
    return templates.TemplateResponse(request, "gestor/relatorios.html", tpl_ctx)


@app.get("/gestor/relatorios/imprimir")
def gestor_relatorios_imprimir(request: Request, tipo: str = "progresso_escolas"):
    """Redireciona para a mesma URL de relatórios com modo impressão (legado / links externos)."""
    from urllib.parse import urlencode

    return RedirectResponse(
        url=f"/gestor/relatorios?{urlencode({'imprimir': '1', 'tipo': tipo})}",
        status_code=302,
    )


@app.get("/gestor/relatorios/export.csv")
def gestor_relatorios_export(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.GESTOR)),
    tipo: str = "progresso_escolas",
):
    import csv
    import io

    from fastapi.responses import StreamingResponse

    from app.services.descriptor_performance_service import DescriptorPerformanceService

    escola_ids = _gestor_escola_ids(db, current_user.id)
    dsvc = DescriptorPerformanceService()
    aluno_ids = (
        dsvc.aluno_ids_for_escolas(db, escola_ids) if escola_ids else dsvc.aluno_ids_all(db)
    )

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)

    if tipo == "progresso_escolas":
        writer.writerow(["escola_id", "escola_nome", "n_alunos", "engajamento_pct", "media_concluidas_atividades"])
        for r in dsvc.escolas_engajamento(db, escola_ids if escola_ids else None):
            writer.writerow(
                [
                    r["escola_id"],
                    r["escola_nome"],
                    r["n_alunos"],
                    r["engajamento_pct"],
                    r["media_concluidas"],
                ]
            )
        filename = "relatorio_progresso_escolas.csv"
    elif tipo == "descritores":
        writer.writerow(
            ["codigo", "descricao", "taxa_conclusao_pct", "alunos_com_conclusao", "alunos_elegiveis", "score_medio"]
        )
        for r in dsvc.aggregates_for_alunos(db, aluno_ids):
            writer.writerow(
                [
                    r["codigo"],
                    r["descricao"],
                    r["taxa_pct"],
                    r["alunos_com_conclusao"],
                    r["alunos_elegiveis"],
                    r["score_medio"] if r["score_medio"] is not None else "",
                ]
            )
        filename = "relatorio_descritores.csv"
    elif tipo == "risco_alunos":
        from app.models.aluno import Aluno
        from app.models.gestao import Escola, Turma
        from app.models.user import Usuario

        writer.writerow(["aluno_id", "nome", "turma", "escola", "nivel_risco", "ano_escolar"])
        q = (
            db.query(Aluno, Usuario.nome, Turma.nome, Escola.nome)
            .join(Usuario, Aluno.usuario_id == Usuario.id)
            .outerjoin(Turma, Aluno.turma_id == Turma.id)
            .outerjoin(Escola, Turma.escola_id == Escola.id)
        )
        if escola_ids:
            q = q.filter(Turma.escola_id.in_(escola_ids))
        for aluno, nome, turma_nome, escola_nome in q.all():
            if (aluno.nivel_risco or "").upper() != "BAIXO":
                writer.writerow(
                    [
                        aluno.id,
                        nome or "",
                        turma_nome or "",
                        escola_nome or "",
                        aluno.nivel_risco or "",
                        aluno.ano_escolar or "",
                    ]
                )
        filename = "relatorio_alunos_risco.csv"
    else:
        from fastapi import HTTPException

        raise HTTPException(400, "Tipo de relatório inválido")

    data = "\ufeff" + output.getvalue()
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/coordenador/relatorios/imprimir")
def coordenador_relatorios_imprimir(request: Request, tipo: str = "monitoramento_turmas"):
    """Redireciona para a mesma URL de relatórios com modo impressão (legado / links externos)."""
    from urllib.parse import urlencode

    return RedirectResponse(
        url=f"/coordenador/relatorios?{urlencode({'imprimir': '1', 'tipo': tipo})}",
        status_code=302,
    )


@app.get("/admin")
def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    from app.models.support_ticket import SupportTicket

    tickets_abertos = (
        db.query(SupportTicket)
        .filter(SupportTicket.status == "aberto")
        .order_by(SupportTicket.updated_at.desc())
        .limit(5)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "request": request,
            "tickets_abertos": tickets_abertos,
            "tickets_abertos_total": len(tickets_abertos),
        },
    )


def _coordenador_layout_context(db: Session, coord_user: Usuario) -> dict:
    from app.models.gestao import Escola
    from app.models.relacoes import CoordenadorEscola

    rel = (
        db.query(CoordenadorEscola)
        .join(Escola, CoordenadorEscola.escola_id == Escola.id)
        .filter(CoordenadorEscola.coordenador_id == coord_user.id)
        .first()
    )
    escola = rel.escola if rel else None
    nome = (coord_user.nome or "").strip()
    partes = nome.split()
    if len(partes) >= 2:
        avatar_iniciais = (partes[0][0] + partes[-1][0]).upper()
    elif len(partes) == 1 and len(partes[0]) >= 2:
        avatar_iniciais = partes[0][:2].upper()
    else:
        avatar_iniciais = "CO"
    return {"escola": escola, "avatar_iniciais": avatar_iniciais}


@app.get("/coordenador")
def coordenador_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.COORDENADOR)),
):
    from app.services.descriptor_performance_service import DescriptorPerformanceService

    layout = _coordenador_layout_context(db, current_user)
    escola = layout["escola"]
    stats = DashboardService().get_coordenador_stats(db, escola.id if escola else None)
    dsvc = DescriptorPerformanceService()
    aluno_ids_escola = dsvc.aluno_ids_for_escolas(db, [escola.id]) if escola else []
    descritores_escola = dsvc.aggregates_for_alunos(db, aluno_ids_escola) if aluno_ids_escola else []
    lacunas_cards = []
    for row in descritores_escola[:2]:
        lacunas_cards.append(
            {
                "titulo": f"{row.get('codigo') or 'Descritor'} — {(row.get('descricao') or '')[:48]}",
                "pct": max(0, min(100, float(row.get("taxa_pct") or 0))),
                "descricao": f"Score médio: {row.get('score_medio') if row.get('score_medio') is not None else '—'} · {row.get('alunos_com_conclusao', 0)}/{row.get('alunos_elegiveis', 0)} alunos com conclusão.",
            }
        )

    disc_raw = (request.query_params.get("disciplina") or "geral").strip().lower()
    if disc_raw not in ("geral", "lp", "mat"):
        disc_raw = "geral"

    return templates.TemplateResponse(
        request,
        "coordenador/dashboard.html",
        {
            "request": request,
            "stats": stats,
            "current_user": current_user,
            **layout,
            "disciplina_monitor": disc_raw,
            "turmas_monitoramento": _coordenador_turmas_monitoramento(
                db, escola.id if escola else None, disciplina_key=disc_raw
            ),
            "riscos_por_turma": _coordenador_riscos_por_turma(db, escola.id if escola else None),
            "lacunas_cards": lacunas_cards,
        },
    )


def _coordenador_atividade_ids_por_disciplina(db: Session, disciplina_key: str) -> list[int] | None:
    """None = todas as ativas (visão geral). Lista vazia = nenhuma atividade classificada na disciplina."""
    from sqlalchemy import and_, or_

    from app.models.gestao import Curso, Trilha
    from app.models.h5p import AtividadeH5P
    from app.models.saeb import Descritor

    key = (disciplina_key or "geral").lower()
    if key == "geral":
        return None
    q = (
        db.query(AtividadeH5P.id)
        .outerjoin(Descritor, AtividadeH5P.descritor_id == Descritor.id)
        .outerjoin(Trilha, AtividadeH5P.trilha_id == Trilha.id)
        .outerjoin(Curso, Trilha.curso_id == Curso.id)
        .filter(AtividadeH5P.ativo.is_(True))
    )
    if key == "lp":
        q = q.filter(
            or_(
                func.lower(Descritor.disciplina) == "lp",
                and_(
                    AtividadeH5P.descritor_id.is_(None),
                    Curso.nome.isnot(None),
                    Curso.nome.ilike("%portug%"),
                ),
            )
        )
    elif key == "mat":
        q = q.filter(
            or_(
                func.lower(Descritor.disciplina) == "mat",
                and_(
                    AtividadeH5P.descritor_id.is_(None),
                    Curso.nome.isnot(None),
                    Curso.nome.ilike("%matem%"),
                ),
            )
        )
    else:
        return None
    return [r[0] for r in q.distinct().all()]


def _coordenador_turmas_monitoramento(
    db: Session, escola_id: int | None, *, disciplina_key: str = "geral"
) -> list[dict]:
    from app.models.gestao import Turma
    from app.models.aluno import Aluno
    from app.models.relacoes import ProfessorTurma
    from app.models.user import Usuario
    from app.models.h5p import ProgressoH5P, AtividadeH5P

    if not escola_id:
        return []
    act_ids = _coordenador_atividade_ids_por_disciplina(db, disciplina_key)
    if act_ids is None:
        total_atividades = db.query(AtividadeH5P).filter(AtividadeH5P.ativo).count()
    else:
        total_atividades = len(act_ids)
    turmas = db.query(Turma).filter(Turma.escola_id == escola_id).order_by(Turma.ano_escolar, Turma.nome).all()
    out = []
    for t in turmas:
        professor_nome = (
            db.query(Usuario.nome)
            .join(ProfessorTurma, ProfessorTurma.professor_id == Usuario.id)
            .filter(ProfessorTurma.turma_id == t.id)
            .limit(1)
            .scalar()
            or "Sem professor"
        )
        aluno_ids = [r[0] for r in db.query(Aluno.id).filter(Aluno.turma_id == t.id).all()]
        adesao = 0.0
        prof_media = 0.0
        status = "Sem dados"
        if aluno_ids and total_atividades:
            done_q = db.query(ProgressoH5P).filter(
                ProgressoH5P.aluno_id.in_(aluno_ids),
                ProgressoH5P.concluido.is_(True),
            )
            avg_q = db.query(func.avg(ProgressoH5P.score)).filter(
                ProgressoH5P.aluno_id.in_(aluno_ids),
                ProgressoH5P.concluido.is_(True),
                ProgressoH5P.score.isnot(None),
            )
            if act_ids is not None:
                done_q = done_q.filter(ProgressoH5P.atividade_id.in_(act_ids))
                avg_q = avg_q.filter(ProgressoH5P.atividade_id.in_(act_ids))
            done = done_q.count()
            adesao = round(min(100.0, (done / (len(aluno_ids) * total_atividades)) * 100), 1)
            avg_score = avg_q.scalar()
            prof_media = round(float(avg_score or 0), 1)
            status = "Crítico" if adesao < 60 else ("Bom" if adesao < 85 else "Adequado")
        elif aluno_ids and total_atividades == 0:
            status = "Sem atividades"
        out.append(
            {
                "turma": f"{t.ano_escolar}º Ano {t.nome}",
                "professor": professor_nome,
                "adesao_pct": adesao,
                "proficiencia": prof_media,
                "status": status,
            }
        )
    return out


def _coordenador_riscos_por_turma(db: Session, escola_id: int | None) -> list[dict]:
    from app.models.gestao import Turma
    from app.models.aluno import Aluno

    if not escola_id:
        return []
    turmas = db.query(Turma).filter(Turma.escola_id == escola_id).all()
    out = []
    for t in turmas:
        total = db.query(Aluno).filter(Aluno.turma_id == t.id).count()
        risco = db.query(Aluno).filter(Aluno.turma_id == t.id, Aluno.nivel_risco != "BAIXO").count()
        if risco <= 0:
            continue
        out.append(
            {
                "turma": f"{t.ano_escolar}º Ano {t.nome}",
                "qtd_risco": risco,
                "pct": round((risco / max(1, total)) * 100, 1),
            }
        )
    out.sort(key=lambda x: x["qtd_risco"], reverse=True)
    return out[:5]


@app.get("/coordenador/relatorios")
def coordenador_relatorios_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.COORDENADOR)),
):
    layout = _coordenador_layout_context(db, current_user)
    imprimir_raw = (request.query_params.get("imprimir") or "").strip().lower()
    modo_impressao = imprimir_raw in ("1", "true", "sim", "yes")
    tipo = (request.query_params.get("tipo") or "").strip()
    print_ctx: dict | None = None
    if modo_impressao:
        print_ctx = _coordenador_relatorio_print_context(db, current_user, tipo)
        if print_ctx is None:
            return RedirectResponse(url="/coordenador/relatorios", status_code=303)
    tpl_ctx: dict = {
        "request": request,
        "current_user": current_user,
        **layout,
        "modo_impressao": bool(print_ctx),
    }
    if print_ctx:
        tpl_ctx.update(print_ctx)
    return templates.TemplateResponse(request, "coordenador/relatorios.html", tpl_ctx)


@app.get("/coordenador/relatorios/export.csv")
def coordenador_relatorios_export(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.COORDENADOR)),
    tipo: str = "monitoramento_turmas",
):
    import csv
    import io
    from fastapi.responses import StreamingResponse
    from app.models.gestao import Escola
    from app.models.relacoes import CoordenadorEscola

    rel = (
        db.query(CoordenadorEscola)
        .join(Escola, CoordenadorEscola.escola_id == Escola.id)
        .filter(CoordenadorEscola.coordenador_id == current_user.id)
        .first()
    )
    escola_id = rel.escola_id if rel else None
    if not escola_id:
        raise HTTPException(400, "Coordenador sem escola vinculada")

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    if tipo == "monitoramento_turmas":
        disc_raw = (request.query_params.get("disciplina") or "geral").strip().lower()
        if disc_raw not in ("geral", "lp", "mat"):
            disc_raw = "geral"
        writer.writerow(["turma", "professor", "adesao_pct", "proficiencia_media", "status"])
        for r in _coordenador_turmas_monitoramento(db, escola_id, disciplina_key=disc_raw):
            writer.writerow([r["turma"], r["professor"], r["adesao_pct"], r["proficiencia"], r["status"]])
        filename = "coordenacao_monitoramento_turmas.csv"
    elif tipo == "risco_turmas":
        writer.writerow(["turma", "alunos_em_risco", "pct_risco"])
        for r in _coordenador_riscos_por_turma(db, escola_id):
            writer.writerow([r["turma"], r["qtd_risco"], r["pct"]])
        filename = "coordenacao_mapa_risco.csv"
    else:
        raise HTTPException(400, "Tipo de relatório inválido")

    data = "\ufeff" + output.getvalue()
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename=\"{filename}\"'},
    )


@app.get("/suporte/chamado")
def suporte_chamado_get(
    request: Request,
    current_user: Usuario | None = Depends(get_current_user_optional),
):
    err = request.query_params.get("erro")
    ok = request.query_params.get("ok")
    email_default = (current_user.email if current_user else "") or ""
    return templates.TemplateResponse(
        request,
        "suporte/chamado.html",
        {
            "request": request,
            "email_default": email_default,
            "erro": err,
            "ok": ok,
        },
    )


@app.post("/suporte/chamado")
async def suporte_chamado_post(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | None = Depends(get_current_user_optional),
):
    from datetime import datetime

    from app.models.support_ticket import SupportTicket, SupportTicketMessage

    form = await request.form()
    email = (form.get("email") or "").strip()
    assunto = (form.get("assunto") or "").strip()
    mensagem = (form.get("mensagem") or "").strip()
    if current_user and getattr(current_user, "email", None):
        email = email or current_user.email
    if not email or not assunto or not mensagem:
        return RedirectResponse(url="/suporte/chamado?erro=campos", status_code=303)
    ticket = SupportTicket(
        usuario_id=current_user.id if current_user else None,
        email=email[:255],
        assunto=assunto[:200],
        status="aberto",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(ticket)
    db.flush()
    db.add(
        SupportTicketMessage(
            ticket_id=ticket.id,
            autor_role="usuario",
            corpo=mensagem[:8000],
            created_at=datetime.utcnow(),
        )
    )
    db.commit()
    return RedirectResponse(url="/suporte/chamado?ok=1", status_code=303)


@app.get("/")
def home(request: Request):
    dados = {
        "status": "online",
        "system": "AVA MJ Backend",
        "features": ["Auth", "Alunos", "Dashboard", "Avaliacoes", "IA", "Chatbot"],
        "optimizations": ["GZip Compression", "Rate Limiting", "DB Error Handling"],
    }
    return templates.TemplateResponse(request, "auth/index.html", {"request": request, **dados})


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {
        "status": "healthy",
        "project": settings.PROJECT_NAME,
        "database": "connected",
        "service": "online",
    }
