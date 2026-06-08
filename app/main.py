import logging
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import case, func, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.media_urls import h5p_content_root, user_upload_root
from app.core.database import SessionLocal, engine, get_db
from app.core.catalogs import FUNDAMENTAL_SUBJECTS
from app.core.dependencies import get_current_user_optional, require_admin_redirect, require_role_redirect
from app.core.logging_config import configure_logging
from app.core.security import limiter
from app.models.base import Base
from app.models.user import AdminScope, TeacherRole, UserRole, Usuario
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
    licitacao_router,
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
    formacao,
    moodle_gestao,
    relacoes,
    resposta,
    saeb,
    professor_h5p,
    medalhas,
    support_ticket,
    user,
)

configure_logging()
logger = logging.getLogger("ava_mj_backend")

app = FastAPI(title="Mj Connect Edu Enterprise")

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
        {
            "nome": "Admin Mj Connect Edu",
            "email": "admin@avajmj.com",
            "role": UserRole.ADMIN,
            "escopo_administrativo": AdminScope.SECRETARIA_SME,
        },
        {
            "nome": "Professor Mj Connect Edu",
            "email": "professor@avamj.com",
            "role": UserRole.PROFESSOR,
            "funcao_docente": TeacherRole.DOCENTE,
        },
        {"nome": "Aluno Mj Connect Edu", "email": "aluno@avamj.com", "role": UserRole.ALUNO},
        {"nome": "Gestor Mj Connect Edu", "email": "gestor@avamj.com", "role": UserRole.GESTOR},
        {"nome": "Coordenador Mj Connect Edu", "email": "coordenador@avamj.com", "role": UserRole.COORDENADOR},
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
                    funcao_docente=d.get("funcao_docente"),
                    escopo_administrativo=d.get("escopo_administrativo"),
                )
            else:
                repo.create(
                    db,
                    UserCreate(
                        nome=d["nome"],
                        email=d["email"],
                        senha="123456",
                        role=d["role"],
                        funcao_docente=d.get("funcao_docente"),
                        escopo_administrativo=d.get("escopo_administrativo"),
                    ),
                )
    finally:
        db.close()


def seed_default_medal_types() -> None:
    from app.services.medalha_service import MedalhaService

    db = SessionLocal()
    try:
        MedalhaService().ensure_default_tipos(db)
    finally:
        db.close()


def seed_default_courses() -> None:
    from app.models.gestao import Curso

    db = SessionLocal()
    try:
        existentes = {str(nome).strip().lower() for (nome,) in db.query(Curso.nome).all()}
        novos = [Curso(nome=nome) for nome in FUNDAMENTAL_SUBJECTS if nome.strip().lower() not in existentes]
        if novos:
            db.add_all(novos)
            db.commit()
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    try:
        _ensure_runtime_schema()
        Base.metadata.create_all(bind=engine)
        seed_default_courses()
        seed_default_users()
        seed_default_medal_types()
        logger.info("Banco sincronizado e seed executado.")
    except Exception as exc:
        logger.error(f"Erro no startup: {exc}")


def _ensure_runtime_schema() -> None:
    """
    Ajustes incrementais simples sem migração formal (ambiente atual).
    """
    insp = inspect(engine)
    def _columns(table_name: str) -> set[str]:
        try:
            return {c["name"] for c in insp.get_columns(table_name)}
        except Exception:
            return set()
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
    if "funcao_docente" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN funcao_docente VARCHAR(40)"))
    if "escopo_administrativo" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN escopo_administrativo VARCHAR(40)"))

    audit_cols = _columns("auditoria_logs")
    if audit_cols:
        if "categoria" not in audit_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE auditoria_logs ADD COLUMN categoria VARCHAR(50)"))
        if "entidade" not in audit_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE auditoria_logs ADD COLUMN entidade VARCHAR(80)"))
        if "entidade_id" not in audit_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE auditoria_logs ADD COLUMN entidade_id INTEGER"))

    aval_cols = _columns("avaliacoes")
    if aval_cols:
        if "codigo" not in aval_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE avaliacoes ADD COLUMN codigo VARCHAR(40)"))
        if "tipo" not in aval_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE avaliacoes ADD COLUMN tipo VARCHAR(30) DEFAULT 'objetiva'"))
        if "status" not in aval_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE avaliacoes ADD COLUMN status VARCHAR(30) DEFAULT 'rascunho'"))
        if "ano_letivo" not in aval_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE avaliacoes ADD COLUMN ano_letivo VARCHAR(20)"))
        if "escopo" not in aval_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE avaliacoes ADD COLUMN escopo VARCHAR(40)"))
        if "curso_id" not in aval_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE avaliacoes ADD COLUMN curso_id INTEGER"))
        if "ano_escolar" not in aval_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE avaliacoes ADD COLUMN ano_escolar INTEGER"))
        if "criado_por_usuario_id" not in aval_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE avaliacoes ADD COLUMN criado_por_usuario_id INTEGER"))
        if "trilha_id" not in aval_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE avaliacoes ADD COLUMN trilha_id INTEGER"))

    quest_cols = _columns("questoes_prova")
    if quest_cols:
        if "codigo" not in quest_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE questoes_prova ADD COLUMN codigo VARCHAR(40)"))
        if "numero" not in quest_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE questoes_prova ADD COLUMN numero INTEGER"))
        if "disciplina" not in quest_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE questoes_prova ADD COLUMN disciplina VARCHAR(50)"))
        if "peso" not in quest_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE questoes_prova ADD COLUMN peso FLOAT DEFAULT 1"))
        if "ativa" not in quest_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE questoes_prova ADD COLUMN ativa BOOLEAN DEFAULT 1"))
        if "banco_questao_id" not in quest_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE questoes_prova ADD COLUMN banco_questao_id INTEGER"))
        if "curso_id" not in quest_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE questoes_prova ADD COLUMN curso_id INTEGER"))
        if "ano_escolar" not in quest_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE questoes_prova ADD COLUMN ano_escolar INTEGER"))
        if "descritor_id" not in quest_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE questoes_prova ADD COLUMN descritor_id INTEGER"))
        if "origem" not in quest_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE questoes_prova ADD COLUMN origem VARCHAR(40)"))
        if "conteudo" not in quest_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE questoes_prova ADD COLUMN conteudo VARCHAR(180)"))
        if "tipo_questao" not in quest_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE questoes_prova ADD COLUMN tipo_questao VARCHAR(50) DEFAULT 'multipla_escolha'"))
        if "alternativa_e" not in quest_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE questoes_prova ADD COLUMN alternativa_e VARCHAR(200)"))
        if engine.dialect.name == "mysql":
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE questoes_prova MODIFY COLUMN enunciado TEXT"))

    banco_cols = _columns("banco_questoes")
    if banco_cols:
        if "conteudo" not in banco_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE banco_questoes ADD COLUMN conteudo VARCHAR(180)"))
        if "tipo_questao" not in banco_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE banco_questoes ADD COLUMN tipo_questao VARCHAR(50) DEFAULT 'multipla_escolha'"))
        if "alternativa_e" not in banco_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE banco_questoes ADD COLUMN alternativa_e VARCHAR(200)"))
        if engine.dialect.name == "mysql":
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE banco_questoes MODIFY COLUMN enunciado TEXT"))

    trilha_cols = _columns("trilhas")
    if trilha_cols:
        if "semestre" not in trilha_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE trilhas ADD COLUMN semestre VARCHAR(20)"))

    turma_cols = _columns("turmas")
    if turma_cols and "sigla" not in turma_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE turmas ADD COLUMN sigla VARCHAR(20)"))

    descritor_cols = _columns("saeb_descritores")
    if descritor_cols:
        if "ano_escolar" not in descritor_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE saeb_descritores ADD COLUMN ano_escolar INTEGER"))
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE saeb_descritores SET disciplina = 'Língua Portuguesa' "
                    "WHERE disciplina IN ('LP', 'Portugues', 'Português')"
                )
            )
            conn.execute(
                text(
                    "UPDATE saeb_descritores SET disciplina = 'Matemática' "
                    "WHERE disciplina IN ('MAT', 'Matematica')"
                )
            )

    resposta_cols = _columns("respostas_alunos")
    if resposta_cols:
        if "lote_importacao_id" not in resposta_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE respostas_alunos ADD COLUMN lote_importacao_id INTEGER"))
        if "pontuacao" not in resposta_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE respostas_alunos ADD COLUMN pontuacao FLOAT"))
        if "processado_em" not in resposta_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE respostas_alunos ADD COLUMN processado_em DATETIME"))
        if "aplicacao_id" not in resposta_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE respostas_alunos ADD COLUMN aplicacao_id INTEGER"))
        if "participacao_id" not in resposta_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE respostas_alunos ADD COLUMN participacao_id INTEGER"))

    lote_cols = _columns("lotes_importacao_gabarito")
    if lote_cols and "aplicacao_id" not in lote_cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE lotes_importacao_gabarito ADD COLUMN aplicacao_id INTEGER"))


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
app.include_router(licitacao_router.router)


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


def _professor_help_request_turma_ids_filter(turma_all: bool, selected_turma_id: int | None) -> list[int] | None:
    """None = todas as turmas; lista com um id = só pedidos dessa turma (coerente com o selector do professor)."""
    if turma_all:
        return None
    if selected_turma_id is not None:
        return [selected_turma_id]
    return None


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


def _avaliacoes_institucionais_pendentes_usuario(db: Session, usuario: Usuario) -> list[dict]:
    from app.models.avaliacao import (
        AplicacaoAvaliacaoInstitucional,
        InstrumentoAvaliacaoInstitucional,
        PerfilAvaliadoInstitucional,
        StatusAplicacaoInstitucional,
    )
    from app.models.resposta import RespostaAvaliacaoInstitucional
    from sqlalchemy.orm import joinedload

    perfil_alvo = None
    if usuario.role == UserRole.COORDENADOR:
        perfil_alvo = PerfilAvaliadoInstitucional.COORDENADOR
    elif usuario.role == UserRole.PROFESSOR and usuario.funcao_docente == TeacherRole.PDT:
        perfil_alvo = PerfilAvaliadoInstitucional.PDT
    if perfil_alvo is None:
        return []
    rows = (
        db.query(AplicacaoAvaliacaoInstitucional)
        .options(
            joinedload(AplicacaoAvaliacaoInstitucional.instrumento).joinedload(
                InstrumentoAvaliacaoInstitucional.criterios
            ),
            joinedload(AplicacaoAvaliacaoInstitucional.escola),
        )
        .join(
            InstrumentoAvaliacaoInstitucional,
            InstrumentoAvaliacaoInstitucional.id == AplicacaoAvaliacaoInstitucional.instrumento_id,
        )
        .filter(
            AplicacaoAvaliacaoInstitucional.avaliado_usuario_id == usuario.id,
            AplicacaoAvaliacaoInstitucional.status == StatusAplicacaoInstitucional.ABERTA,
            InstrumentoAvaliacaoInstitucional.perfil_avaliado == perfil_alvo,
        )
        .order_by(AplicacaoAvaliacaoInstitucional.created_at.desc())
        .all()
    )
    out: list[dict] = []
    for app_item in rows:
        respostas_count = (
            db.query(func.count(RespostaAvaliacaoInstitucional.id))
            .filter(RespostaAvaliacaoInstitucional.aplicacao_id == app_item.id)
            .scalar()
            or 0
        )
        if respostas_count:
            continue
        out.append(
            {
                "id": app_item.id,
                "instrumento_nome": app_item.instrumento.nome if app_item.instrumento else "Instrumento",
                "escola_nome": app_item.escola.nome if app_item.escola else "—",
                "criterios": sorted(
                    list(app_item.instrumento.criterios if app_item.instrumento else []),
                    key=lambda c: (c.ordem or 0, c.id or 0),
                ),
                "observacoes": (app_item.observacoes or "").strip(),
            }
        )
    return out


@app.get("/professor")
def professor_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    from app.services.live_support_service import LiveSupportService
    from app.services.descriptor_performance_service import DescriptorPerformanceService
    from app.services.medalha_service import MedalhaService

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
        descritores_rows = dsvc.combined_aggregates_for_alunos(db, aluno_ids) if aluno_ids else []
        radar_alunos = dsvc.radar_alunos_turmas(db, turma_ids_prof)
        chat_duvidas = dsvc.top_chat_questions_for_turmas(db, turma_ids_prof, limit=5)
    else:
        aluno_ids = dsvc.aluno_ids_for_turma(db, selected_turma_id)
        descritores_rows = dsvc.combined_aggregates_for_alunos(db, aluno_ids) if aluno_ids else []
        radar_alunos = dsvc.radar_alunos_turma(db, selected_turma_id)
        chat_duvidas = dsvc.top_chat_questions_for_turma(db, selected_turma_id, limit=5)
    pior = descritores_rows[0] if descritores_rows else None
    pior_pct = float((pior or {}).get("engajamento_pct") or 0)
    ia_alerta_ativo = bool(pior and pior_pct < 50)
    medalha_service = MedalhaService()
    medalha_tipos = medalha_service.list_tipos_ativos(db)
    turma_ids_scope = turma_ids_prof if turma_all else ([selected_turma_id] if selected_turma_id else [])
    medalha_alunos = medalha_service.list_alunos_para_turmas(db, turma_ids_scope)
    flash_ok = (request.query_params.get("ok") or "").strip()
    flash_err = (request.query_params.get("err") or "").strip()

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
            "teacher_help_requests": live_support.list_teacher_help_requests(
                current_user,
                limit=25,
                turma_ids=_professor_help_request_turma_ids_filter(turma_all, selected_turma_id),
            ),
            "descritores_rows": descritores_rows,
            "descritores_preview": descritores_rows[:5],
            "radar_alunos": radar_alunos[:12],
            "chat_duvidas": chat_duvidas,
            "ia_alerta_ativo": ia_alerta_ativo,
            "ia_alerta_descritor": pior,
            "moodle_cursos": moodle_cursos,
            "moodle_aviso": moodle_aviso,
            "MOODLE_URL": settings.MOODLE_URL.rstrip("/"),
            "medalha_tipos": medalha_tipos,
            "medalha_alunos": medalha_alunos,
            "flash_ok": flash_ok,
            "flash_err": flash_err,
            "avaliacoes_institucionais_pendentes": _avaliacoes_institucionais_pendentes_usuario(
                db, current_user
            ),
        },
    )


@app.post("/professor/medalhas/enviar")
async def professor_medalhas_enviar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    from urllib.parse import quote

    from app.services.medalha_service import MedalhaService

    professor_turmas = _professor_turmas_list(db, current_user.id)
    selected_turma_id, turma_all = _resolve_professor_turma_selection(
        professor_turmas, request.query_params.get("turma_id")
    )
    turma_ids_prof = [t.id for t in professor_turmas]
    turma_query_suffix = _professor_turma_query_suffix(
        bool(professor_turmas), turma_all, selected_turma_id
    )
    form = await request.form()
    try:
        medalha_tipo_id = int(form.get("medalha_tipo_id") or 0)
    except (TypeError, ValueError):
        medalha_tipo_id = 0
    alvo = (form.get("alvo") or "turma").strip().lower()
    aluno_id_raw = (form.get("aluno_id") or "").strip()
    mensagem = (form.get("mensagem") or "").strip() or None
    aluno_id = int(aluno_id_raw) if aluno_id_raw.isdigit() else None
    if not medalha_tipo_id:
        sep = "&" if turma_query_suffix else "?"
        return RedirectResponse(
            url=f"/professor{turma_query_suffix}{sep}err={quote('Selecione um tipo de medalha.')}",
            status_code=303,
        )
    turma_ids_alvo = turma_ids_prof if turma_all else ([selected_turma_id] if selected_turma_id else [])
    if alvo == "aluno" and not aluno_id:
        sep = "&" if turma_query_suffix else "?"
        return RedirectResponse(
            url=f"/professor{turma_query_suffix}{sep}err={quote('Selecione um aluno para envio individual.')}",
            status_code=303,
        )
    ok, msg, total = MedalhaService().enviar_medalha(
        db,
        professor_usuario_id=current_user.id,
        medalha_tipo_id=medalha_tipo_id,
        turma_ids_alvo=turma_ids_alvo,
        aluno_id=aluno_id if alvo == "aluno" else None,
        mensagem=mensagem,
    )
    sep = "&" if turma_query_suffix else "?"
    if not ok:
        return RedirectResponse(
            url=f"/professor{turma_query_suffix}{sep}err={quote(msg)}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/professor{turma_query_suffix}{sep}ok={quote(f'medalha_{total}')}",
        status_code=303,
    )


@app.get("/professor/dashboard-completo")
def professor_dashboard_completo(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    from app.services.descriptor_performance_service import DescriptorPerformanceService
    from app.services.live_support_service import LiveSupportService
    from app.services.medalha_service import MedalhaService

    professor_turmas = _professor_turmas_list(db, current_user.id)
    selected_turma_id, turma_all = _resolve_professor_turma_selection(
        professor_turmas, request.query_params.get("turma_id")
    )
    turma_ids_prof = [t.id for t in professor_turmas]
    turma_query_suffix = _professor_turma_query_suffix(
        bool(professor_turmas), turma_all, selected_turma_id
    )
    turma_ids_scope = turma_ids_prof if turma_all else ([selected_turma_id] if selected_turma_id else [])
    dsvc = DescriptorPerformanceService()
    if turma_all:
        aluno_ids = dsvc.aluno_ids_for_turmas(db, turma_ids_prof)
        descritores_rows = dsvc.aggregates_for_alunos(db, aluno_ids) if aluno_ids else []
        radar_alunos = dsvc.radar_alunos_turmas(db, turma_ids_prof)
    else:
        aluno_ids = dsvc.aluno_ids_for_turma(db, selected_turma_id)
        descritores_rows = dsvc.aggregates_for_alunos(db, aluno_ids) if aluno_ids else []
        radar_alunos = dsvc.radar_alunos_turma(db, selected_turma_id)
    medalhas = MedalhaService().dashboard_completo_professor(
        db, professor_usuario_id=current_user.id, turma_ids=turma_ids_scope
    )
    stats = DashboardService().get_professor_stats(db)
    live_support = LiveSupportService(db)
    return templates.TemplateResponse(
        request,
        "professor/dashboard_completo.html",
        {
            "request": request,
            "current_user": current_user,
            "professor_turmas": professor_turmas,
            "selected_turma_id": selected_turma_id,
            "turma_all": turma_all,
            "turma_query_suffix": turma_query_suffix,
            "stats": stats,
            "descritores_preview": descritores_rows[:8],
            "radar_alunos": radar_alunos[:20],
            "upcoming_live_classes": live_support.list_live_classes_for_professor(current_user),
            "medalhas": medalhas,
        },
    )


@app.get("/professor/desempenho-descritores")
def professor_desempenho_descritores(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    from app.services.descriptor_performance_service import DescriptorPerformanceService
    from datetime import datetime

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
    rows = dsvc.combined_aggregates_for_alunos(db, aluno_ids) if aluno_ids else []
    imprimir_raw = (request.query_params.get("imprimir") or "").strip().lower()
    modo_impressao = imprimir_raw in ("1", "true", "sim", "yes")
    if modo_impressao:
        table_rows = [
            [
                r.get("codigo", ""),
                r.get("descricao", ""),
                f"{r.get('engajamento_pct')}%" if r.get("engajamento_pct") is not None else "—",
                f"{r.get('desempenho_score_10')}/10" if r.get("desempenho_score_10") is not None else "—",
            ]
            for r in rows
        ]
        back_href = f"/professor/desempenho-descritores{turma_query_suffix}"
        return templates.TemplateResponse(
            request,
            "shared/relatorio_imprimir.html",
            {
                "request": request,
                "report_title": "Desempenho por descritor SAEB",
                "report_subtitle": "Proficiência da turma selecionada no escopo do professor",
                "column_labels": ["Código", "Descrição", "Engajamento", "Média em prova"],
                "rows": table_rows,
                "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "back_href": back_href,
                "report_author_label": "Professor(a)",
                "report_author_name": (current_user.nome or "").strip(),
                "report_kicker": "Mj Connect Edu — Relatório pedagógico",
            },
        )

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


@app.get("/professor/desempenho-descritores/export.csv")
def professor_desempenho_descritores_export_csv(
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
    dsvc = DescriptorPerformanceService()
    if turma_all:
        aluno_ids = dsvc.aluno_ids_for_turmas(db, turma_ids_prof)
    else:
        aluno_ids = dsvc.aluno_ids_for_turma(db, selected_turma_id)
    rows = dsvc.combined_aggregates_for_alunos(db, aluno_ids) if aluno_ids else []

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["codigo", "descricao", "engajamento_pct", "media_em_prova_10"])
    for r in rows:
        writer.writerow(
            [
                r.get("codigo", ""),
                r.get("descricao", ""),
                r.get("engajamento_pct", ""),
                r.get("desempenho_score_10", ""),
            ]
        )
    data = "\ufeff" + output.getvalue()
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="desempenho_descritores_professor.csv"'},
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
    from app.services.live_support_service import LiveSupportService

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
        chat_duvidas = dsvc.top_chat_questions_for_turmas(db, turma_ids_prof, limit=80)
    else:
        chat_duvidas = dsvc.top_chat_questions_for_turma(db, selected_turma_id, limit=80)
    live_support = LiveSupportService(db)
    teacher_help_requests = live_support.list_teacher_help_requests(
        current_user,
        limit=120,
        turma_ids=_professor_help_request_turma_ids_filter(turma_all, selected_turma_id),
    )
    tab = (request.query_params.get("tab") or "perguntas").strip().lower()
    if tab not in ("perguntas", "solicitacoes"):
        tab = "perguntas"
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
            "teacher_help_requests": teacher_help_requests,
            "chat_insights_tab": tab,
        },
    )


@app.post("/professor/chat-duvidas/perguntas/excluir")
async def professor_chat_duvidas_excluir_pergunta(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    from app.models.aluno import Aluno
    from app.models.chat_message import ChatMessage
    from app.models.chat_session import ChatSession

    form = await request.form()
    texto = (form.get("texto") or "").strip()
    turma_raw = (form.get("turma_id") or "").strip().lower()
    tab = (form.get("tab") or "perguntas").strip().lower()
    if tab not in ("perguntas", "solicitacoes"):
        tab = "perguntas"
    if not texto:
        return RedirectResponse(url=f"/professor/chat-duvidas?tab={tab}", status_code=303)

    professor_turmas = _professor_turmas_list(db, current_user.id)
    allowed_turma_ids = {t.id for t in professor_turmas}
    if turma_raw == "all":
        target_turma_ids = list(allowed_turma_ids)
        turma_qs = "all"
    else:
        try:
            target_turma_id = int(turma_raw)
        except Exception:
            target_turma_id = next(iter(allowed_turma_ids), None)
        if target_turma_id not in allowed_turma_ids:
            target_turma_id = next(iter(allowed_turma_ids), None)
        target_turma_ids = [target_turma_id] if target_turma_id else []
        turma_qs = str(target_turma_id) if target_turma_id else "all"

    aluno_user_ids = (
        db.query(Aluno.usuario_id)
        .filter(Aluno.turma_id.in_(target_turma_ids))
        .all()
        if target_turma_ids
        else []
    )
    uid_list = [r[0] for r in aluno_user_ids if r[0]]
    if uid_list:
        session_ids = [r[0] for r in db.query(ChatSession.id).filter(ChatSession.user_id.in_(uid_list)).all()]
        if session_ids:
            db.query(ChatMessage).filter(
                ChatMessage.session_id.in_(session_ids),
                ChatMessage.sender == "user",
                ChatMessage.message_text == texto,
            ).delete(synchronize_session=False)
            db.commit()
    return RedirectResponse(url=f"/professor/chat-duvidas?turma_id={turma_qs}&tab={tab}", status_code=303)


@app.post("/professor/chat-duvidas/solicitacoes/{request_id}/deletar")
def professor_chat_duvidas_excluir_solicitacao(
    request_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.PROFESSOR)),
):
    from app.models.live_support import SolicitacaoProfessor

    turma_raw = (request.query_params.get("turma_id") or "").strip().lower()
    tab = (request.query_params.get("tab") or "solicitacoes").strip().lower()
    if tab not in ("perguntas", "solicitacoes"):
        tab = "solicitacoes"
    professor_turmas = _professor_turmas_list(db, current_user.id)
    allowed_turma_ids = {t.id for t in professor_turmas}
    if turma_raw == "all":
        turma_qs = "all"
        filter_turma_ids = allowed_turma_ids
    else:
        try:
            tid = int(turma_raw)
        except Exception:
            tid = next(iter(allowed_turma_ids), None)
        if tid not in allowed_turma_ids:
            tid = next(iter(allowed_turma_ids), None)
        turma_qs = str(tid) if tid else "all"
        filter_turma_ids = {tid} if tid else allowed_turma_ids

    item = (
        db.query(SolicitacaoProfessor)
        .filter(
            SolicitacaoProfessor.id == request_id,
            SolicitacaoProfessor.professor_id == current_user.id,
        )
        .first()
    )
    if item and (not filter_turma_ids or item.turma_id in filter_turma_ids):
        db.delete(item)
        db.commit()
    return RedirectResponse(url=f"/professor/chat-duvidas?turma_id={turma_qs}&tab={tab}", status_code=303)


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
        "report_kicker": "Mj Connect Edu — Relatório",
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
        cols = [
            "Código",
            "Descrição",
            "Taxa conclusão %",
            "Alunos c/ conclusão",
            "Alunos elegíveis",
            "Score H5P",
            "Nota média provas",
        ]
        rows = []
        for r in dsvc.combined_aggregates_for_alunos(db, aluno_ids):
            rows.append(
                [
                    r["codigo"],
                    r["descricao"],
                    r.get("engajamento_pct", 0),
                    r.get("alunos_h5p_conclusao", 0),
                    r.get("alunos_h5p_elegiveis", 0),
                    r.get("h5p_score_10") if r.get("h5p_score_10") is not None else "",
                    r.get("prova_score_10") if r.get("prova_score_10") is not None else "",
                ]
            )
        return title, subtitle, cols, rows
    if tipo == "risco_alunos":
        title = "Alunos em risco"
        subtitle = "Alunos com nível de risco diferente de baixo"
        cols = ["ID aluno", "Nome", "Turma", "Escola", "Nível risco", "Ano", "Nota média provas"]
        q = (
            db.query(Aluno, Usuario.nome, Turma.nome, Escola.nome)
            .join(Usuario, Aluno.usuario_id == Usuario.id)
            .outerjoin(Turma, Aluno.turma_id == Turma.id)
            .outerjoin(Escola, Turma.escola_id == Escola.id)
        )
        if scope_ids:
            q = q.filter(Turma.escola_id.in_(scope_ids))
        candidatos = q.all()
        notas_por_aluno = dsvc.notas_provas_por_aluno(db, [aluno.id for aluno, *_ in candidatos])
        rows = []
        for aluno, nome, turma_nome, escola_nome in candidatos:
            if (aluno.nivel_risco or "").upper() != "BAIXO":
                rows.append(
                    [
                        aluno.id,
                        nome or "",
                        turma_nome or "",
                        escola_nome or "",
                        aluno.nivel_risco or "",
                        aluno.ano_escolar or "",
                        notas_por_aluno.get(aluno.id, ""),
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
        "report_kicker": "Mj Connect Edu — Relatório estratégico",
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
        "report_kicker": "Mj Connect Edu — Relatório de coordenação",
    }


def _professor_allowed_turma_ids(db: Session, professor_user_id: int) -> set[int]:
    from app.models.relacoes import ProfessorTurma

    rows = db.query(ProfessorTurma.turma_id).filter(ProfessorTurma.professor_id == professor_user_id).all()
    return {r[0] for r in rows}


def _cursos_portugues_matematica(db: Session):
    """Cursos de LP e MAT para o professor escolher a matéria da atividade personalizada."""
    from sqlalchemy import or_

    from app.models.gestao import Curso

    return (
        db.query(Curso)
        .filter(or_(Curso.nome.ilike("%portug%"), Curso.nome.ilike("%matem%")))
        .order_by(Curso.nome.asc())
        .all()
    )


def _parse_curso_materia_personalizada(db: Session, raw) -> tuple[int | None, str | None]:
    """Valida curso_id do formulário para atividade de turma. Devolve (id, None) ou (None, código_erro)."""
    rows = _cursos_portugues_matematica(db)
    allowed = {c.id for c in rows}
    try:
        cid = int(str(raw or "").strip())
    except Exception:
        cid = 0
    if not cid or cid not in allowed:
        return None, "materia_invalida"
    return cid, None


@app.get("/professor/atividades")
def professor_atividades_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(require_role_redirect(UserRole.PROFESSOR)),
    materia_id: str | None = None,
    ano: str | None = None,
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from sqlalchemy import func

    from sqlalchemy.orm import joinedload

    from app.models.professor_h5p import ProfessorAtividadeH5P, ProfessorAtividadeH5PAluno
    from app.models.gestao import Curso, Turma
    from app.models.h5p import AtividadeH5P
    from app.models.gestao import Trilha

    try:
        selected_materia_id = int(str(materia_id or "").strip()) if materia_id is not None else None
    except Exception:
        selected_materia_id = None
    try:
        selected_ano = int(str(ano or "").strip()) if ano is not None else None
    except Exception:
        selected_ano = None

    pairs_query = (
        db.query(ProfessorAtividadeH5P, Turma.nome, Turma.ano_escolar)
        .join(Turma, Turma.id == ProfessorAtividadeH5P.turma_id)
        .options(joinedload(ProfessorAtividadeH5P.curso))
        .filter(ProfessorAtividadeH5P.professor_id == current_user.id)
    )
    if selected_materia_id is not None:
        pairs_query = pairs_query.filter(ProfessorAtividadeH5P.curso_id == selected_materia_id)
    if selected_ano is not None:
        pairs_query = pairs_query.filter(Turma.ano_escolar == selected_ano)
    pairs = pairs_query.order_by(ProfessorAtividadeH5P.created_at.desc()).all()
    act_ids = [a.id for a, _, _ in pairs]
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
    atividades = [(a, tn, tano, dest_counts.get(a.id, 0)) for a, tn, tano in pairs]
    atividades_trilha_geral = []
    professor_turmas = _professor_turmas_list(db, current_user.id)
    anos_permitidos = sorted({t.ano_escolar for t in professor_turmas if t.ano_escolar is not None})
    cursos_materia = _cursos_portugues_matematica(db)
    if bool(getattr(current_user, "permite_cadastro_trilha_geral", False)):
        if anos_permitidos:
            trilha_query = (
                db.query(AtividadeH5P, Trilha.nome, Trilha.ano_escolar, Curso.nome)
                .join(Trilha, Trilha.id == AtividadeH5P.trilha_id)
                .join(Curso, Curso.id == Trilha.curso_id)
                .filter(
                    AtividadeH5P.ativo,
                    Trilha.ano_escolar.in_(anos_permitidos),
                )
            )
            if selected_materia_id is not None:
                trilha_query = trilha_query.filter(Trilha.curso_id == selected_materia_id)
            if selected_ano is not None:
                trilha_query = trilha_query.filter(Trilha.ano_escolar == selected_ano)
            atividades_trilha_geral = trilha_query.order_by(AtividadeH5P.created_at.desc()).all()
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
            "filtro_materias": cursos_materia,
            "filtro_anos": anos_permitidos,
            "selected_materia_id": selected_materia_id,
            "selected_ano": selected_ano,
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
    cursos_materia = _cursos_portugues_matematica(db)
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
            "cursos_materia": cursos_materia,
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

    curso_id, err_curso = _parse_curso_materia_personalizada(db, form.get("curso_id"))
    if err_curso:
        return RedirectResponse(url=f"/professor/atividades/nova?erro={err_curso}", status_code=303)

    obj = ProfessorAtividadeH5P(
        professor_id=current_user.id,
        turma_id=turma_id,
        curso_id=curso_id,
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
    cursos_materia = _cursos_portugues_matematica(db)
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
            "cursos_materia": cursos_materia,
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
    curso_id, err_curso = _parse_curso_materia_personalizada(db, form.get("curso_id"))
    if err_curso:
        return RedirectResponse(url=f"/professor/atividades/{id}/editar?erro={err_curso}", status_code=303)
    atividade.curso_id = curso_id
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
    from app.services.dashboard_service import DashboardService

    perfil_stats = DashboardService().get_professor_stats(db)
    perfil_stats["n_turmas_vinculadas"] = len(nav.get("professor_turmas") or [])
    return _perfil_form_response(
        request,
        current_user,
        "/professor",
        template_name="professor/perfil_form.html",
        extra={**nav, "perfil_stats": perfil_stats},
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
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.GESTOR)),
):
    from app.models.aluno import Aluno
    from app.models.gestao import Turma

    escola_ids = _gestor_escola_ids(db, current_user.id)
    turmas_scope = _gestor_turmas_scope(db, current_user.id)
    q_alunos = db.query(Aluno)
    if escola_ids:
        q_alunos = q_alunos.join(Turma, Aluno.turma_id == Turma.id).filter(Turma.escola_id.in_(escola_ids))
    perfil_stats = {
        "n_escolas_escopo": len(escola_ids),
        "n_turmas_escopo": len(turmas_scope),
        "n_alunos_escopo": int(q_alunos.count() or 0),
    }
    return _perfil_form_response(
        request,
        current_user,
        "/gestor",
        template_name="gestor/perfil_form.html",
        extra={"perfil_stats": perfil_stats},
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
    layout = _coordenador_layout_context(db, current_user)
    from app.services.dashboard_service import DashboardService

    escola = layout.get("escola")
    perfil_stats = DashboardService().get_coordenador_stats(db, escola.id if escola else None)
    return _perfil_form_response(
        request,
        current_user,
        "/coordenador",
        template_name="coordenador/perfil_form.html",
        extra={**layout, "perfil_stats": perfil_stats},
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


def _gestor_turmas_scope(db: Session, gestor_user_id: int):
    from app.models.gestao import Turma

    escola_ids = _gestor_escola_ids(db, gestor_user_id)
    if not escola_ids:
        return []
    return (
        db.query(Turma)
        .filter(Turma.escola_id.in_(escola_ids))
        .order_by(Turma.escola_id.asc(), Turma.ano_escolar.asc(), Turma.nome.asc())
        .all()
    )


@app.get("/gestor")
def gestor_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.GESTOR)),
):
    from app.models.aluno import Aluno
    from app.models.gestao import Turma
    from app.models.h5p import AtividadeH5P, ProgressoH5P
    from app.models.interacao_ia import InteracaoIA
    from app.models.professor_h5p import ProfessorAtividadeH5P, ProfessorProgressoH5P
    from app.services.descriptor_performance_service import DescriptorPerformanceService
    from app.services.live_support_service import LiveSupportService

    escola_ids = _gestor_escola_ids(db, current_user.id)
    stats = DashboardService().get_gestor_stats(db, escola_ids=escola_ids or None)
    dsvc = DescriptorPerformanceService()
    live_support = LiveSupportService(db)
    if escola_ids:
        aluno_ids = dsvc.aluno_ids_for_escolas(db, escola_ids)
        escolas_tbl = dsvc.escolas_engajamento(db, escola_ids)
    else:
        aluno_ids = dsvc.aluno_ids_all(db)
        escolas_tbl = dsvc.escolas_engajamento(db, None)

    h5p_trilha_ativas = db.query(func.count(AtividadeH5P.id)).filter(AtividadeH5P.ativo).scalar() or 0

    q_h5p_trilha_conc = (
        db.query(func.count(ProgressoH5P.id))
        .join(Aluno, Aluno.id == ProgressoH5P.aluno_id)
        .filter(ProgressoH5P.concluido)
    )
    q_h5p_prof_conc = (
        db.query(func.count(ProfessorProgressoH5P.id))
        .join(Aluno, Aluno.id == ProfessorProgressoH5P.aluno_id)
        .filter(ProfessorProgressoH5P.concluido)
    )
    q_ia_interacoes = (
        db.query(func.count(InteracaoIA.id))
        .join(Aluno, Aluno.id == InteracaoIA.aluno_id)
    )
    q_h5p_prof_ativas = db.query(func.count(ProfessorAtividadeH5P.id)).filter(ProfessorAtividadeH5P.ativo)
    if escola_ids:
        q_h5p_trilha_conc = (
            q_h5p_trilha_conc.join(Turma, Turma.id == Aluno.turma_id).filter(Turma.escola_id.in_(escola_ids))
        )
        q_h5p_prof_conc = (
            q_h5p_prof_conc.join(Turma, Turma.id == Aluno.turma_id).filter(Turma.escola_id.in_(escola_ids))
        )
        q_ia_interacoes = (
            q_ia_interacoes.join(Turma, Turma.id == Aluno.turma_id).filter(Turma.escola_id.in_(escola_ids))
        )
        q_h5p_prof_ativas = (
            q_h5p_prof_ativas.join(Turma, Turma.id == ProfessorAtividadeH5P.turma_id).filter(Turma.escola_id.in_(escola_ids))
        )

    resource_usage = {
        "h5p_trilha_ativas": int(h5p_trilha_ativas),
        "h5p_trilha_conclusoes": int(q_h5p_trilha_conc.scalar() or 0),
        "h5p_professor_ativas": int(q_h5p_prof_ativas.scalar() or 0),
        "h5p_professor_conclusoes": int(q_h5p_prof_conc.scalar() or 0),
        "ia_interacoes": int(q_ia_interacoes.scalar() or 0),
    }

    return templates.TemplateResponse(
        request,
        "gestor/dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "stats": stats,
            "escolas_engajamento": escolas_tbl,
            "descritores_resumo": dsvc.combined_aggregates_for_alunos(db, aluno_ids)[:6],
            "upcoming_live_classes": live_support.list_live_classes_for_gestor(current_user)[:4],
            "resource_usage": resource_usage,
        },
    )


@app.get("/gestor/lives")
def gestor_lives_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.GESTOR)),
):
    from app.services.live_support_service import LiveSupportService

    qp = request.query_params
    service = LiveSupportService(db)
    turmas_scope = _gestor_turmas_scope(db, current_user.id)
    return templates.TemplateResponse(
        request,
        "gestor/lives.html",
        {
            "request": request,
            "current_user": current_user,
            "turmas_scope": turmas_scope,
            "upcoming_live_classes": service.list_live_classes_for_gestor(current_user),
            "flash_ok": (qp.get("ok") or "").strip(),
            "flash_err": (qp.get("err") or "").strip(),
        },
    )


@app.post("/gestor/lives/agendar")
async def gestor_lives_agendar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(require_role_redirect(UserRole.GESTOR)),
):
    from datetime import datetime
    from urllib.parse import quote

    from app.schemas.live_support_schema import AulaAoVivoCreateRequest
    from app.services.live_support_service import LiveSupportService
    from pydantic import ValidationError
    from sqlalchemy.exc import SQLAlchemyError

    if isinstance(current_user, RedirectResponse):
        return current_user

    form = await request.form()
    turma_raw = (form.get("turma_id") or "").strip()
    turma_id = int(turma_raw) if turma_raw.isdigit() else None
    scope = (form.get("target_scope") or "professores_escolas_gestor").strip().lower()
    disciplina = (form.get("disciplina") or "").strip()
    titulo = (form.get("titulo") or "").strip()
    scheduled_raw = (form.get("scheduled_at") or "").strip()
    if not disciplina or not titulo or not scheduled_raw:
        return RedirectResponse(
            url="/gestor/lives?err=Preencha%20disciplina,%20t%C3%ADtulo%20e%20data/hora.",
            status_code=303,
        )
    try:
        scheduled_at = datetime.fromisoformat(scheduled_raw)
    except Exception:
        return RedirectResponse(
            url="/gestor/lives?err=Data%20e%20hora%20inv%C3%A1lidas.",
            status_code=303,
        )
    try:
        payload = AulaAoVivoCreateRequest(
            turma_id=turma_id,
            target_scope=scope,
            disciplina=disciplina,
            titulo=titulo,
            descricao=(form.get("descricao") or "").strip() or None,
            meeting_url=None,
            scheduled_at=scheduled_at,
            duration_minutes=50,
        )
        LiveSupportService(db).create_live_class(current_user, payload)
    except HTTPException as exc:
        return RedirectResponse(
            url=f"/gestor/lives?err={quote(str(exc.detail)[:200])}",
            status_code=303,
        )
    except ValidationError as exc:
        msg = exc.errors()[0].get("msg") if exc.errors() else "Dados inválidos."
        return RedirectResponse(
            url=f"/gestor/lives?err={quote(str(msg)[:200])}",
            status_code=303,
        )
    except SQLAlchemyError:
        return RedirectResponse(
            url="/gestor/lives?err=Estrutura%20do%20banco%20desatualizada.%20Execute%20alembic%20upgrade%20head.",
            status_code=303,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/gestor/lives?err={quote(str(exc)[:220] or f'Falha ao processar agendamento ({exc.__class__.__name__}).')}",
            status_code=303,
        )
    return RedirectResponse(url="/gestor/lives?ok=agendada", status_code=303)


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
            [
                "codigo",
                "descricao",
                "taxa_conclusao_pct",
                "alunos_com_conclusao",
                "alunos_elegiveis",
                "score_h5p",
                "nota_media_provas",
            ]
        )
        for r in dsvc.combined_aggregates_for_alunos(db, aluno_ids):
            writer.writerow(
                [
                    r["codigo"],
                    r["descricao"],
                    r.get("engajamento_pct", 0),
                    r.get("alunos_h5p_conclusao", 0),
                    r.get("alunos_h5p_elegiveis", 0),
                    r.get("h5p_score_10") if r.get("h5p_score_10") is not None else "",
                    r.get("prova_score_10") if r.get("prova_score_10") is not None else "",
                ]
            )
        filename = "relatorio_descritores.csv"
    elif tipo == "risco_alunos":
        from app.models.aluno import Aluno
        from app.models.gestao import Escola, Turma
        from app.models.user import Usuario

        writer.writerow(["aluno_id", "nome", "turma", "escola", "nivel_risco", "ano_escolar", "nota_media_provas"])
        q = (
            db.query(Aluno, Usuario.nome, Turma.nome, Escola.nome)
            .join(Usuario, Aluno.usuario_id == Usuario.id)
            .outerjoin(Turma, Aluno.turma_id == Turma.id)
            .outerjoin(Escola, Turma.escola_id == Escola.id)
        )
        if escola_ids:
            q = q.filter(Turma.escola_id.in_(escola_ids))
        candidatos = q.all()
        notas_por_aluno = dsvc.notas_provas_por_aluno(db, [aluno.id for aluno, *_ in candidatos])
        for aluno, nome, turma_nome, escola_nome in candidatos:
            if (aluno.nivel_risco or "").upper() != "BAIXO":
                writer.writerow(
                    [
                        aluno.id,
                        nome or "",
                        turma_nome or "",
                        escola_nome or "",
                        aluno.nivel_risco or "",
                        aluno.ano_escolar or "",
                        notas_por_aluno.get(aluno.id, ""),
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
    from app.models.user import AuditLog
    from app.services.licitacao_service import LicitacaoService

    tickets_abertos = (
        db.query(SupportTicket)
        .filter(SupportTicket.status == "aberto")
        .order_by(SupportTicket.updated_at.desc())
        .limit(5)
        .all()
    )
    recent_audits = (
        db.query(AuditLog)
        .order_by(AuditLog.data_hora.desc())
        .limit(6)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "admin/dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "sme_stats": LicitacaoService().get_sme_dashboard(db),
            "recent_audits": recent_audits,
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


def _coordenador_escolas_scope(db: Session, coordenador_user_id: int):
    from app.models.gestao import Escola
    from app.models.relacoes import CoordenadorEscola

    return (
        db.query(Escola)
        .join(CoordenadorEscola, CoordenadorEscola.escola_id == Escola.id)
        .filter(CoordenadorEscola.coordenador_id == coordenador_user_id)
        .order_by(Escola.nome.asc())
        .all()
    )


@app.get("/coordenador/lives")
def coordenador_lives_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.COORDENADOR)),
):
    from app.services.live_support_service import LiveSupportService

    qp = request.query_params
    escolas_scope = _coordenador_escolas_scope(db, current_user.id)
    service = LiveSupportService(db)
    return templates.TemplateResponse(
        request,
        "coordenador/lives.html",
        {
            "request": request,
            "current_user": current_user,
            "escolas_scope": escolas_scope,
            "upcoming_live_classes": service.list_live_classes_for_coordenador(current_user),
            "flash_ok": (qp.get("ok") or "").strip(),
            "flash_err": (qp.get("err") or "").strip(),
        },
    )


@app.post("/coordenador/lives/agendar")
async def coordenador_lives_agendar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(require_role_redirect(UserRole.COORDENADOR)),
):
    from datetime import datetime
    from urllib.parse import quote

    from app.schemas.live_support_schema import AulaAoVivoCreateRequest
    from app.services.live_support_service import LiveSupportService
    from pydantic import ValidationError
    from sqlalchemy.exc import SQLAlchemyError

    if isinstance(current_user, RedirectResponse):
        return current_user

    form = await request.form()
    escola_raw = (form.get("escola_id") or "").strip()
    escola_id = int(escola_raw) if escola_raw.isdigit() else None
    scope = (form.get("target_scope") or "gestores_escolas").strip().lower()
    disciplina = (form.get("disciplina") or "").strip()
    titulo = (form.get("titulo") or "").strip()
    scheduled_raw = (form.get("scheduled_at") or "").strip()
    if not disciplina or not titulo or not scheduled_raw:
        return RedirectResponse(
            url="/coordenador/lives?err=Preencha%20disciplina,%20t%C3%ADtulo%20e%20data/hora.",
            status_code=303,
        )
    try:
        scheduled_at = datetime.fromisoformat(scheduled_raw)
    except Exception:
        return RedirectResponse(
            url="/coordenador/lives?err=Data%20e%20hora%20inv%C3%A1lidas.",
            status_code=303,
        )
    try:
        payload = AulaAoVivoCreateRequest(
            escola_id=escola_id,
            target_scope=scope,
            disciplina=disciplina,
            titulo=titulo,
            descricao=(form.get("descricao") or "").strip() or None,
            meeting_url=None,
            scheduled_at=scheduled_at,
            duration_minutes=50,
        )
        LiveSupportService(db).create_live_class(current_user, payload)
    except HTTPException as exc:
        return RedirectResponse(
            url=f"/coordenador/lives?err={quote(str(exc.detail)[:200])}",
            status_code=303,
        )
    except ValidationError as exc:
        msg = exc.errors()[0].get("msg") if exc.errors() else "Dados inválidos."
        return RedirectResponse(
            url=f"/coordenador/lives?err={quote(str(msg)[:200])}",
            status_code=303,
        )
    except SQLAlchemyError:
        return RedirectResponse(
            url="/coordenador/lives?err=Estrutura%20do%20banco%20desatualizada.%20Execute%20alembic%20upgrade%20head.",
            status_code=303,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/coordenador/lives?err={quote(str(exc)[:220] or f'Falha ao processar agendamento ({exc.__class__.__name__}).')}",
            status_code=303,
        )
    return RedirectResponse(url="/coordenador/lives?ok=agendada", status_code=303)


@app.get("/coordenador")
def coordenador_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.COORDENADOR)),
):
    from app.services.descriptor_performance_service import DescriptorPerformanceService
    from app.services.live_support_service import LiveSupportService

    layout = _coordenador_layout_context(db, current_user)
    escola = layout["escola"]
    stats = DashboardService().get_coordenador_stats(db, escola.id if escola else None)
    dsvc = DescriptorPerformanceService()
    live_support = LiveSupportService(db)
    aluno_ids_escola = dsvc.aluno_ids_for_escolas(db, [escola.id]) if escola else []
    descritores_escola = dsvc.combined_aggregates_for_alunos(db, aluno_ids_escola) if aluno_ids_escola else []
    lacunas_cards = []
    for row in descritores_escola[:2]:
        eng = row.get("engajamento_pct")
        des = row.get("desempenho_score_10")
        lacunas_cards.append(
            {
                "titulo": f"{row.get('codigo') or 'Descritor'} — {(row.get('descricao') or '')[:48]}",
                "pct": max(0, min(100, float(eng or 0))),
                "descricao": f"Engajamento: {eng if eng is not None else '—'}% · Desempenho (prova): {des if des is not None else '—'}/10",
            }
        )

    disc_raw = (request.query_params.get("disciplina") or "geral").strip().lower()
    if disc_raw not in ("geral", "lp", "mat"):
        disc_raw = "geral"
    flash_ok = (request.query_params.get("ok") or "").strip()
    flash_err = (request.query_params.get("err") or "").strip()

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
            "upcoming_live_classes": live_support.list_live_classes_for_coordenador(current_user)[:4],
            "flash_ok": flash_ok,
            "flash_err": flash_err,
            "avaliacoes_institucionais_pendentes": _avaliacoes_institucionais_pendentes_usuario(
                db, current_user
            ),
        },
    )


@app.get("/coordenador/turmas/{turma_id}/analise")
def coordenador_turma_analise_page(
    request: Request,
    turma_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.COORDENADOR)),
    disciplina: str = "geral",
    q: str = "",
    faixa: str = "todas",
    risco: str = "todos",
    ordenar: str = "adesao_asc",
):
    disc = (disciplina or "geral").strip().lower()
    if disc not in ("geral", "lp", "mat"):
        disc = "geral"
    fx = (faixa or "todas").strip().lower()
    if fx not in ("todas", "baixa", "media", "alta"):
        fx = "todas"
    rk = (risco or "todos").strip().lower()
    if rk not in ("todos", "baixo", "elevado"):
        rk = "todos"
    ord_key = (ordenar or "adesao_asc").strip().lower()
    if ord_key not in ("adesao_asc", "adesao_desc", "nome"):
        ord_key = "adesao_asc"

    escola_id = _coordenador_escola_id_for_user(db, current_user.id)
    if not escola_id:
        raise HTTPException(status_code=400, detail="Coordenador sem escola vinculada")

    bundle = _coordenador_turma_analise_detalhe(
        db,
        escola_id,
        turma_id,
        disciplina_key=disc,
        busca_nome=(q or "").strip(),
        faixa_adesao=fx,
        risco_filtro=rk,
        ordenar=ord_key,
    )
    if bundle is None:
        raise HTTPException(status_code=404, detail="Turma não encontrada")

    layout = _coordenador_layout_context(db, current_user)
    return templates.TemplateResponse(
        request,
        "coordenador/turma_analise.html",
        {
            "request": request,
            "current_user": current_user,
            **layout,
            **bundle,
            "filtro_disciplina": disc,
            "filtro_q": (q or "").strip(),
            "filtro_faixa": fx,
            "filtro_risco": rk,
            "filtro_ordenar": ord_key,
        },
    )


@app.get("/coordenador/turmas/{turma_id}/analise/export.csv")
def coordenador_turma_analise_export_csv(
    request: Request,
    turma_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.COORDENADOR)),
    disciplina: str = "geral",
    q: str = "",
    faixa: str = "todas",
    risco: str = "todos",
    ordenar: str = "adesao_asc",
):
    import csv
    import io

    escola_id = _coordenador_escola_id_for_user(db, current_user.id)
    if not escola_id:
        raise HTTPException(status_code=400, detail="Coordenador sem escola vinculada")

    bundle = _coordenador_turma_analise_detalhe(
        db,
        escola_id,
        turma_id,
        disciplina_key=disciplina,
        busca_nome=(q or "").strip(),
        faixa_adesao=(faixa or "todas").strip().lower(),
        risco_filtro=(risco or "todos").strip().lower(),
        ordenar=(ordenar or "adesao_asc").strip().lower(),
    )
    if bundle is None:
        raise HTTPException(status_code=404, detail="Turma não encontrada")

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["nome", "risco", "concluidas", "adesao_pct", "media_nas_provas"])
    for al in bundle.get("alunos") or []:
        writer.writerow(
            [
                al.get("nome", ""),
                al.get("nivel_risco", ""),
                f"{al.get('concluidas', 0)}/{al.get('total_atividades', 0)}",
                al.get("adesao_pct", 0),
                al.get("media_provas", 0),
            ]
        )
    data = "\ufeff" + output.getvalue()
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="analise_turma_{turma_id}.csv"'},
    )


@app.get("/coordenador/turmas/{turma_id}/analise/imprimir")
def coordenador_turma_analise_imprimir(
    request: Request,
    turma_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_role_redirect(UserRole.COORDENADOR)),
    disciplina: str = "geral",
    q: str = "",
    faixa: str = "todas",
    risco: str = "todos",
    ordenar: str = "adesao_asc",
):
    from datetime import datetime

    escola_id = _coordenador_escola_id_for_user(db, current_user.id)
    if not escola_id:
        raise HTTPException(status_code=400, detail="Coordenador sem escola vinculada")

    bundle = _coordenador_turma_analise_detalhe(
        db,
        escola_id,
        turma_id,
        disciplina_key=disciplina,
        busca_nome=(q or "").strip(),
        faixa_adesao=(faixa or "todas").strip().lower(),
        risco_filtro=(risco or "todos").strip().lower(),
        ordenar=(ordenar or "adesao_asc").strip().lower(),
    )
    if bundle is None:
        raise HTTPException(status_code=404, detail="Turma não encontrada")

    rows = [
        [
            al.get("nome", ""),
            al.get("nivel_risco", ""),
            f"{al.get('concluidas', 0)} / {al.get('total_atividades', 0)}",
            f"{al.get('adesao_pct', 0)}%",
            al.get("media_provas", 0),
        ]
        for al in (bundle.get("alunos") or [])
    ]
    return templates.TemplateResponse(
        request,
        "shared/relatorio_imprimir.html",
        {
            "request": request,
            "report_title": f"Análise pedagógica — {bundle.get('turma_label')}",
            "report_subtitle": f"Professor(a): {bundle.get('professor')}",
            "column_labels": ["Nome", "Risco", "Concluídas", "Adesão", "Média nas provas"],
            "rows": rows,
            "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "back_href": f"/coordenador/turmas/{turma_id}/analise?disciplina={disciplina}&q={q}&faixa={faixa}&risco={risco}&ordenar={ordenar}",
            "report_author_label": "Coordenação",
            "report_author_name": (current_user.nome or "").strip(),
            "report_kicker": "Mj Connect Edu — Análise por turma",
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
    from app.models.resposta import RespostaAluno
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
        media_provas = 0.0
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
            _ = avg_score
            status = "Crítico" if adesao < 60 else ("Bom" if adesao < 85 else "Adequado")
        elif aluno_ids and total_atividades == 0:
            status = "Sem atividades"

        if aluno_ids:
            notas_por_aluno = (
                db.query(
                    RespostaAluno.aluno_id,
                    func.count(RespostaAluno.id).label("total"),
                    func.sum(case((RespostaAluno.acertou.is_(True), 1), else_=0)).label("acertos"),
                )
                .filter(RespostaAluno.aluno_id.in_(aluno_ids))
                .group_by(RespostaAluno.aluno_id)
                .all()
            )
            notas = []
            for _, total, acertos in notas_por_aluno:
                total_n = int(total or 0)
                acertos_n = int(acertos or 0)
                if total_n > 0:
                    notas.append((acertos_n / total_n) * 10.0)
            media_provas = round(sum(notas) / len(notas), 2) if notas else 0.0
        out.append(
            {
                "turma_id": t.id,
                "turma": t.nome,
                "professor": professor_nome,
                "adesao_pct": adesao,
                "media_provas": media_provas,
                "status": status,
            }
        )
    return out


def _coordenador_escola_id_for_user(db: Session, coordenador_user_id: int) -> int | None:
    from app.models.gestao import Escola
    from app.models.relacoes import CoordenadorEscola

    return (
        db.query(CoordenadorEscola.escola_id)
        .join(Escola, CoordenadorEscola.escola_id == Escola.id)
        .filter(CoordenadorEscola.coordenador_id == coordenador_user_id)
        .scalar()
    )


def _coordenador_turma_analise_detalhe(
    db: Session,
    escola_id: int,
    turma_id: int,
    *,
    disciplina_key: str,
    busca_nome: str,
    faixa_adesao: str,
    risco_filtro: str,
    ordenar: str,
) -> dict | None:
    """Dados para a página de análise da turma; None se a turma não pertencer à escola."""
    from app.models.aluno import Aluno
    from app.models.gestao import Turma
    from app.models.h5p import AtividadeH5P, ProgressoH5P
    from app.models.resposta import RespostaAluno
    from app.models.relacoes import ProfessorTurma
    from app.models.user import Usuario

    t = db.query(Turma).filter(Turma.id == turma_id, Turma.escola_id == escola_id).first()
    if not t:
        return None

    professor_nome = (
        db.query(Usuario.nome)
        .join(ProfessorTurma, ProfessorTurma.professor_id == Usuario.id)
        .filter(ProfessorTurma.turma_id == t.id)
        .limit(1)
        .scalar()
        or "Sem professor"
    )

    act_ids = _coordenador_atividade_ids_por_disciplina(db, disciplina_key)
    if act_ids is None:
        total_atividades = db.query(AtividadeH5P).filter(AtividadeH5P.ativo.is_(True)).count()
    else:
        total_atividades = len(act_ids)

    aluno_rows = (
        db.query(Aluno.id, Usuario.nome)
        .join(Usuario, Aluno.usuario_id == Usuario.id)
        .filter(Aluno.turma_id == t.id)
        .order_by(Usuario.nome.asc())
        .all()
    )
    aluno_ids = [r[0] for r in aluno_rows]
    n_alunos = len(aluno_ids)

    done_by_aluno: dict[int, int] = {}
    avg_by_aluno: dict[int, float] = {}
    media_provas_by_aluno: dict[int, float] = {}
    risco_by_aluno: dict[int, str] = {}

    if aluno_ids:
        for aid, nr in db.query(Aluno.id, Aluno.nivel_risco).filter(Aluno.id.in_(aluno_ids)).all():
            risco_by_aluno[aid] = (nr or "BAIXO").strip().upper() or "BAIXO"

    if aluno_ids and total_atividades:
        dq = db.query(ProgressoH5P.aluno_id, func.count(ProgressoH5P.id)).filter(
            ProgressoH5P.aluno_id.in_(aluno_ids),
            ProgressoH5P.concluido.is_(True),
        )
        aq = db.query(ProgressoH5P.aluno_id, func.avg(ProgressoH5P.score)).filter(
            ProgressoH5P.aluno_id.in_(aluno_ids),
            ProgressoH5P.concluido.is_(True),
            ProgressoH5P.score.isnot(None),
        )
        if act_ids is not None:
            dq = dq.filter(ProgressoH5P.atividade_id.in_(act_ids))
            aq = aq.filter(ProgressoH5P.atividade_id.in_(act_ids))
        for aid, cnt in dq.group_by(ProgressoH5P.aluno_id).all():
            done_by_aluno[int(aid)] = int(cnt or 0)
        for aid, av in aq.group_by(ProgressoH5P.aluno_id).all():
            if av is not None:
                avg_by_aluno[int(aid)] = round(float(av), 1)

    adesao_turma_pct = 0.0
    status_turma = "Sem dados"
    if n_alunos and total_atividades:
        done_total = sum(done_by_aluno.values())
        adesao_turma_pct = round(
            min(100.0, (done_total / (float(n_alunos) * float(total_atividades))) * 100.0), 1
        )
        status_turma = "Crítico" if adesao_turma_pct < 60 else ("Bom" if adesao_turma_pct < 85 else "Adequado")
    elif n_alunos and total_atividades == 0:
        status_turma = "Sem atividades"

    media_prof_turma = 0.0
    if aluno_ids and total_atividades:
        pq = db.query(func.avg(ProgressoH5P.score)).filter(
            ProgressoH5P.aluno_id.in_(aluno_ids),
            ProgressoH5P.concluido.is_(True),
            ProgressoH5P.score.isnot(None),
        )
        if act_ids is not None:
            pq = pq.filter(ProgressoH5P.atividade_id.in_(act_ids))
        media_prof_turma = round(float(pq.scalar() or 0), 1)

    media_provas_turma = 0.0
    if aluno_ids:
        notas_rows = (
            db.query(
                RespostaAluno.aluno_id,
                func.count(RespostaAluno.id).label("total"),
                func.sum(case((RespostaAluno.acertou.is_(True), 1), else_=0)).label("acertos"),
            )
            .filter(RespostaAluno.aluno_id.in_(aluno_ids))
            .group_by(RespostaAluno.aluno_id)
            .all()
        )
        notas: list[float] = []
        for aid, total, acertos in notas_rows:
            total_n = int(total or 0)
            acertos_n = int(acertos or 0)
            media = round((acertos_n / total_n) * 10.0, 2) if total_n else 0.0
            media_provas_by_aluno[int(aid)] = media
            if total_n:
                notas.append(media)
        media_provas_turma = round(sum(notas) / len(notas), 2) if notas else 0.0

    alunos_out: list[dict] = []
    for aid, nome in aluno_rows:
        nome_s = (nome or "").strip() or "—"
        if busca_nome and busca_nome.lower() not in nome_s.lower():
            continue
        if total_atividades:
            done = done_by_aluno.get(aid, 0)
            adesao = round(min(100.0, (done / float(total_atividades)) * 100.0), 1)
        else:
            done = 0
            adesao = 0.0
        prof_m = avg_by_aluno.get(aid, 0.0)

        if not total_atividades:
            st = "Sem atividades"
        else:
            st = "Crítico" if adesao < 60 else ("Bom" if adesao < 85 else "Adequado")

        if faixa_adesao == "baixa" and adesao >= 60:
            continue
        if faixa_adesao == "media" and (adesao < 60 or adesao >= 85):
            continue
        if faixa_adesao == "alta" and adesao < 85:
            continue

        risco = risco_by_aluno.get(aid, "BAIXO")
        if risco_filtro == "elevado" and risco == "BAIXO":
            continue
        if risco_filtro == "baixo" and risco != "BAIXO":
            continue

        alunos_out.append(
            {
                "aluno_id": aid,
                "nome": nome_s,
                "adesao_pct": adesao,
                "media_provas": media_provas_by_aluno.get(aid, 0.0),
                "status": st,
                "nivel_risco": risco,
                "concluidas": done_by_aluno.get(aid, 0),
                "total_atividades": total_atividades,
            }
        )

    if ordenar == "adesao_desc":
        alunos_out.sort(key=lambda x: (-x["adesao_pct"], x["nome"].lower()))
    elif ordenar == "nome":
        alunos_out.sort(key=lambda x: x["nome"].lower())
    else:
        alunos_out.sort(key=lambda x: (x["adesao_pct"], x["nome"].lower()))

    atividades_criticas: list[dict] = []
    if aluno_ids and total_atividades and (act_ids is None or act_ids):
        # Prioriza atividades efetivamente concluídas por alunos da turma para evitar
        # listas zeradas na visão "Geral" por conta de atividades sem relação com a turma.
        progress_q = db.query(
            ProgressoH5P.atividade_id,
            func.count(func.distinct(ProgressoH5P.aluno_id)).label("alunos_concluiram"),
        ).filter(
            ProgressoH5P.aluno_id.in_(aluno_ids),
            ProgressoH5P.concluido.is_(True),
        )
        if act_ids is not None:
            progress_q = progress_q.filter(ProgressoH5P.atividade_id.in_(act_ids))
        progress_rows = (
            progress_q.group_by(ProgressoH5P.atividade_id)
            .order_by(text("alunos_concluiram ASC"), ProgressoH5P.atividade_id.asc())
            .limit(120)
            .all()
        )

        if progress_rows:
            ids_only = [int(aid) for aid, _ in progress_rows]
            title_rows = (
                db.query(AtividadeH5P.id, AtividadeH5P.titulo)
                .filter(AtividadeH5P.id.in_(ids_only))
                .all()
            )
            title_map = {int(aid): (ttl or f"Atividade #{aid}") for aid, ttl in title_rows}
            for aid, c in progress_rows:
                aid_i = int(aid)
                concluidas = int(c or 0)
                pct = round(min(100.0, (float(concluidas) / float(n_alunos)) * 100.0), 1)
                atividades_criticas.append(
                    {
                        "titulo": title_map.get(aid_i, f"Atividade #{aid_i}")[:80],
                        "pct_turma": pct,
                        "concluiram": concluidas,
                        "total_alunos": n_alunos,
                    }
                )
        elif act_ids:
            # Fallback quando existe escopo de atividades, mas ainda sem conclusões.
            act_list = (
                db.query(AtividadeH5P.id, AtividadeH5P.titulo)
                .filter(AtividadeH5P.ativo.is_(True), AtividadeH5P.id.in_(act_ids))
                .order_by(AtividadeH5P.ordem.asc(), AtividadeH5P.id.asc())
                .limit(12)
                .all()
            )
            for aid, titulo in act_list:
                atividades_criticas.append(
                    {
                        "titulo": (titulo or f"Atividade #{aid}")[:80],
                        "pct_turma": 0.0,
                        "concluiram": 0,
                        "total_alunos": n_alunos,
                    }
                )

        atividades_criticas.sort(key=lambda x: (x["pct_turma"], x["concluiram"]))
        atividades_criticas = atividades_criticas[:12]

    return {
        "turma_id": t.id,
        "turma_label": f"{t.ano_escolar}º Ano {t.nome}",
        "ano_escolar": t.ano_escolar,
        "nome_turma": t.nome or "",
        "professor": professor_nome,
        "disciplina_key": disciplina_key,
        "total_atividades": total_atividades,
        "n_alunos": n_alunos,
        "n_alunos_filtrados": len(alunos_out),
        "adesao_turma_pct": adesao_turma_pct,
        "media_proficiencia_turma": media_prof_turma,
        "media_provas_turma": media_provas_turma,
        "status_turma": status_turma,
        "atividades_criticas": atividades_criticas,
        "alunos": alunos_out,
    }


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


def _role_value_for_ui(role) -> str:
    rv = getattr(role, "value", role)
    return (str(rv or "")).strip().lower()


def _support_user_scope_filter(user: Usuario):
    from app.models.support_ticket import SupportTicket

    clauses = [SupportTicket.usuario_id == user.id]
    email = (getattr(user, "email", "") or "").strip().lower()
    if email:
        clauses.append(func.lower(SupportTicket.email) == email)
    expr = clauses[0]
    for clause in clauses[1:]:
        expr = expr | clause
    return expr


def _support_nav_context_for_role(role_value: str) -> dict:
    rv = (role_value or "").strip().lower()
    if rv == "aluno":
        return {
            "brand_link": "/aluno",
            "menu_title": "Menu do Aluno",
            "menu_partial": "aluno/partials/aluno_menu_default.html",
        }
    if rv == "professor":
        return {
            "brand_link": "/professor",
            "menu_title": "Menu do Professor",
            "menu_partial": "professor/partials/professor_menu_links.html",
        }
    if rv == "gestor":
        return {
            "brand_link": "/gestor",
            "menu_title": "Menu do Gestor",
            "menu_partial": "gestor/partials/gestor_menu_links.html",
        }
    if rv == "coordenador":
        return {
            "brand_link": "/coordenador",
            "menu_title": "Menu do Coordenador",
            "menu_partial": "coordenador/partials/coordenador_menu_links.html",
        }
    return {
        "brand_link": "/",
        "menu_title": "Menu",
        "menu_partial": "partials/empty.html",
    }


@app.get("/suporte/meus-chamados")
def suporte_meus_chamados(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(
        require_role_redirect(UserRole.ALUNO, UserRole.PROFESSOR, UserRole.GESTOR, UserRole.COORDENADOR)
    ),
):
    from app.models.support_ticket import SupportTicket

    if isinstance(current_user, RedirectResponse):
        return current_user

    role_value = _role_value_for_ui(current_user.role)
    tickets = (
        db.query(SupportTicket)
        .filter(_support_user_scope_filter(current_user))
        .order_by(SupportTicket.updated_at.desc(), SupportTicket.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "shared/suporte_meus_chamados.html",
        {
            "request": request,
            "current_user": current_user,
            "role_value": role_value,
            "tickets": tickets,
            "erro": (request.query_params.get("erro") or "").strip(),
            "ok": (request.query_params.get("ok") or "").strip(),
            **_support_nav_context_for_role(role_value),
        },
    )


@app.get("/suporte/meus-chamados/{ticket_id}")
def suporte_meus_chamados_detalhe(
    request: Request,
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(
        require_role_redirect(UserRole.ALUNO, UserRole.PROFESSOR, UserRole.GESTOR, UserRole.COORDENADOR)
    ),
):
    from app.models.support_ticket import SupportTicket, SupportTicketMessage

    if isinstance(current_user, RedirectResponse):
        return current_user

    ticket = (
        db.query(SupportTicket)
        .filter(SupportTicket.id == ticket_id)
        .filter(_support_user_scope_filter(current_user))
        .first()
    )
    if not ticket:
        return RedirectResponse(url="/suporte/meus-chamados?erro=nao_encontrado", status_code=303)
    mensagens = (
        db.query(SupportTicketMessage)
        .filter(SupportTicketMessage.ticket_id == ticket_id)
        .order_by(SupportTicketMessage.created_at.asc())
        .all()
    )
    role_value = _role_value_for_ui(current_user.role)
    return templates.TemplateResponse(
        request,
        "shared/suporte_ticket_usuario.html",
        {
            "request": request,
            "current_user": current_user,
            "role_value": role_value,
            "ticket": ticket,
            "mensagens": mensagens,
            "erro": (request.query_params.get("erro") or "").strip(),
            "ok": (request.query_params.get("ok") or "").strip(),
            **_support_nav_context_for_role(role_value),
        },
    )


@app.post("/suporte/meus-chamados/{ticket_id}/responder")
async def suporte_meus_chamados_responder(
    request: Request,
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario | RedirectResponse = Depends(
        require_role_redirect(UserRole.ALUNO, UserRole.PROFESSOR, UserRole.GESTOR, UserRole.COORDENADOR)
    ),
):
    from datetime import datetime

    from app.models.support_ticket import SupportTicket, SupportTicketMessage

    if isinstance(current_user, RedirectResponse):
        return current_user

    ticket = (
        db.query(SupportTicket)
        .filter(SupportTicket.id == ticket_id)
        .filter(_support_user_scope_filter(current_user))
        .first()
    )
    if not ticket:
        return RedirectResponse(url="/suporte/meus-chamados?erro=nao_encontrado", status_code=303)

    form = await request.form()
    corpo = (form.get("corpo") or "").strip()
    if not corpo:
        return RedirectResponse(
            url=f"/suporte/meus-chamados/{ticket_id}?erro=mensagem_vazia",
            status_code=303,
        )
    if ticket.status == "resolvido":
        return RedirectResponse(
            url=f"/suporte/meus-chamados/{ticket_id}?erro=resolvido",
            status_code=303,
        )

    db.add(
        SupportTicketMessage(
            ticket_id=ticket.id,
            autor_role=_role_value_for_ui(current_user.role) or "usuario",
            corpo=corpo[:8000],
            created_at=datetime.utcnow(),
        )
    )
    ticket.updated_at = datetime.utcnow()
    db.add(ticket)
    db.commit()
    return RedirectResponse(
        url=f"/suporte/meus-chamados/{ticket_id}?ok=respondido",
        status_code=303,
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
    rv = _role_value_for_ui(getattr(current_user, "role", None))
    if current_user and rv in {"aluno", "professor", "gestor", "coordenador"}:
        return RedirectResponse(url=f"/suporte/meus-chamados/{ticket.id}?ok=criado", status_code=303)
    return RedirectResponse(url="/suporte/chamado?ok=1", status_code=303)


@app.get("/")
def home(request: Request):
    dados = {
        "status": "online",
        "system": "Mj Connect Edu Backend",
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
