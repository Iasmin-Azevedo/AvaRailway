from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta, timezone
from app.core.database import get_db
from app.core.config import settings
from app.core.security import criar_token_acesso, criar_refresh_token
from app.models.user import UserRole
from app.schemas.user_schema import UserCreate, UserResponse
from app.repositories.user_repository import UserRepository
from app.repositories.aluno_repository import AlunoRepository
import re

router = APIRouter()
page_router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
user_repo = UserRepository()
aluno_repo = AlunoRepository()


def _get_aluno_nome(request: Request, db: Session) -> str:
    aluno_nome = "Aluno"
    token = request.cookies.get(settings.ACCESS_COOKIE_NAME)
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


def _get_aluno_id_from_request(request: Request, db: Session) -> Optional[int]:
    from app.models.aluno import Aluno
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email = payload.get("sub")
        if not email:
            return None
        user = user_repo.get_by_email(db, email)
        if not user:
            return None
        aluno = db.query(Aluno).filter(Aluno.usuario_id == user.id).first()
        return aluno.id if aluno else None
    except JWTError:
        return None


def _as_int(value) -> Optional[int]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _sanitize_signup_fields(nome, email, senha) -> tuple[str, str, str]:
    return (str(nome or "").strip(), str(email or "").strip().lower(), str(senha or "").strip())


def _extract_score_from_payload(payload: dict | None) -> Optional[float]:
    """Extrai score de payloads variados do H5P e normaliza para 0..100."""
    if not isinstance(payload, dict):
        return None

    def _to_float(value) -> Optional[float]:
        try:
            return float(value)
        except Exception:
            return None

    raw_score = payload.get("score")
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}

    if raw_score is None:
        score_obj = result.get("score") if isinstance(result.get("score"), dict) else {}
        raw = _to_float(score_obj.get("raw"))
        max_score = _to_float(score_obj.get("max"))
        if raw is not None and max_score and max_score > 0:
            return max(0.0, min(100.0, (raw / max_score) * 100.0))
        raw_score = result.get("score")
        if raw_score is None:
            raw_score = result.get("score_scaled")

    score = _to_float(raw_score)
    if score is not None:
        if 0.0 <= score <= 1.0:
            score *= 100.0
        return max(0.0, min(100.0, score))

    merged = " ".join(str(v) for v in payload.values() if v is not None)
    m = re.search(r"(\d+)\s*/\s*(\d+)", merged)
    if m:
        hit = float(m.group(1))
        total = float(m.group(2))
        if total > 0:
            return max(0.0, min(100.0, (hit / total) * 100.0))
    return None


@page_router.get("/aluno")
def aluno_home(request: Request, db: Session = Depends(get_db)):
    """Tela inicial do aluno (dashboard)."""
    from app.models.aluno import Aluno
    from app.services.dashboard_service import DashboardService
    from app.services.live_support_service import LiveSupportService
    aluno_nome = _get_aluno_nome(request, db)
    aluno_id = None
    aluno_ano = None
    current_user = None
    token = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    if token:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            email = payload.get("sub")
            if email:
                user = user_repo.get_by_email(db, email)
                if user:
                    current_user = user
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
    atividades_turma_total = 0
    atividades_turma_concluidas = 0

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

    upcoming_live_classes = []
    if current_user:
        upcoming_live_classes = LiveSupportService(db).list_live_classes_for_student(current_user)
    if aluno_id:
        from app.models.aluno import Aluno
        from app.models.professor_h5p import ProfessorAtividadeH5P, ProfessorProgressoH5P

        aluno = db.query(Aluno).filter(Aluno.id == aluno_id).first()
        if aluno and aluno.turma_id:
            atividades_turma_total = (
                db.query(ProfessorAtividadeH5P)
                .filter(
                    ProfessorAtividadeH5P.turma_id == aluno.turma_id,
                    ProfessorAtividadeH5P.ativo,
                )
                .count()
            )
            atividades_turma_concluidas = (
                db.query(ProfessorProgressoH5P)
                .join(
                    ProfessorAtividadeH5P,
                    ProfessorAtividadeH5P.id == ProfessorProgressoH5P.atividade_id,
                )
                .filter(
                    ProfessorProgressoH5P.aluno_id == aluno_id,
                    ProfessorProgressoH5P.concluido,
                    ProfessorAtividadeH5P.turma_id == aluno.turma_id,
                    ProfessorAtividadeH5P.ativo,
                )
                .count()
            )

    return templates.TemplateResponse(
        request,
        "aluno/dashboard.html",
        {
            "aluno_nome": aluno_nome,
            "aluno_ano": aluno_ano,
            "stats": stats,
            "preview_trilha": preview_trilha,
            "preview_curso_nome": preview_curso_nome,
            "preview_atividades_total": preview_atividades_total,
            "upcoming_live_classes": upcoming_live_classes,
            "atividades_turma_total": atividades_turma_total,
            "atividades_turma_concluidas": atividades_turma_concluidas,
        },
    )



@page_router.get("/aluno/missao1")
def aluno_missao_1(request: Request, db: Session = Depends(get_db)):
    aluno_nome = _get_aluno_nome(request, db)
    aluno_ano = None
    token = request.cookies.get("access_token")
    if token:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            email = payload.get("sub")
            if email:
                user = user_repo.get_by_email(db, email)
                if user:
                    from app.models.aluno import Aluno
                    aluno = db.query(Aluno).filter(Aluno.usuario_id == user.id).first()
                    if aluno:
                        aluno_ano = aluno.ano_escolar
        except JWTError:
            pass
    return templates.TemplateResponse(
        request,
        "aluno/missao1_desafios.html",
        {"aluno_nome": aluno_nome, "aluno_ano": aluno_ano},
    )


@page_router.get("/aluno/configuracoes")
def aluno_configuracoes(request: Request, db: Session = Depends(get_db)):
    from app.services.dashboard_service import DashboardService

    aluno_nome = _get_aluno_nome(request, db)
    aluno_id = _get_aluno_id_from_request(request, db)
    aluno_ano = None
    if aluno_id:
        from app.models.aluno import Aluno

        aluno = db.query(Aluno).filter(Aluno.id == aluno_id).first()
        aluno_ano = aluno.ano_escolar if aluno else None
    stats = DashboardService().get_aluno_stats(db, aluno_id) if aluno_id else {}
    return templates.TemplateResponse(
        request,
        "aluno/configuracoes.html",
        {
            "aluno_nome": aluno_nome,
            "aluno_ano": aluno_ano,
            "stats": stats,
        },
    )


@page_router.get("/aluno/xp-resumo")
def aluno_xp_resumo(request: Request, db: Session = Depends(get_db)):
    from app.services.dashboard_service import DashboardService

    aluno_id = _get_aluno_id_from_request(request, db)
    if not aluno_id:
        raise HTTPException(status_code=401, detail="Nao autenticado")
    stats = DashboardService().get_aluno_stats(db, aluno_id)
    return {
        "xp_total": int(stats.get("xp_total") or 0),
        "xp_atual_nivel": int(stats.get("xp_atual_nivel") or 0),
        "xp_meta_nivel": int(stats.get("xp_meta_nivel") or 600),
        "xp_pct_nivel": int(stats.get("xp_pct_nivel") or 0),
    }


@page_router.get("/aluno/trilhas")
@page_router.get("/aluno/portugues")
def aluno_trilhas(request: Request, db: Session = Depends(get_db)):
    """Lista trilhas e atividades H5P para o aluno (padrão: Português)."""
    return _render_trilhas_por_materia(
        request=request,
        db=db,
        materia_slug="portugues",
        template_name="aluno/trilhas.html",
    )


@page_router.get("/aluno/trilhas/matematica")
@page_router.get("/aluno/matematica")
def aluno_trilhas_matematica(request: Request, db: Session = Depends(get_db)):
    """Lista trilhas e atividades H5P de Matemática para o aluno."""
    return _render_trilhas_por_materia(
        request=request,
        db=db,
        materia_slug="matematica",
        template_name="aluno/trilhas_matematica.html",
    )


def _render_trilhas_por_materia(
    request: Request,
    db: Session,
    materia_slug: str,
    template_name: str,
):
    """Renderiza trilhas filtradas por matéria (português/matemática)."""
    from app.models.aluno import Aluno
    from app.models.gestao import Curso
    from app.models.saeb import Descritor
    from app.repositories.gestao_repository import TrilhaRepository
    from app.repositories.h5p_repository import AtividadeH5PRepository

    aluno_nome = _get_aluno_nome(request, db)
    aluno_id = _get_aluno_id_from_request(request, db)
    aluno_ano = None
    aluno_turma_id = None
    token = request.cookies.get(settings.ACCESS_COOKIE_NAME)
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
                        aluno_turma_id = aluno.turma_id
        except JWTError:
            pass

    materia_map = {
        "portugues": ("Língua Portuguesa", "%portug%"),
        "matematica": ("Matemática", "%matem%"),
    }
    materia_nome, curso_like = materia_map.get(
        (materia_slug or "").strip().lower(),
        ("Língua Portuguesa", "%portug%"),
    )

    curso = db.query(Curso).filter(Curso.nome.ilike(curso_like)).first()
    trilhas = (
        TrilhaRepository().listar(db, curso_id=curso.id, ano_escolar=aluno_ano)
        if curso
        else []
    )

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

    atividades_concluidas = set()
    if aluno_id:
        from app.models.h5p import ProgressoH5P
        rows = (
            db.query(ProgressoH5P.atividade_id)
            .filter(
                ProgressoH5P.aluno_id == aluno_id,
                ProgressoH5P.concluido,
            )
            .all()
        )
        atividades_concluidas = {r[0] for r in rows}

    atividades_professor_turma = []
    atividades_professor_concluidas = set()
    if aluno_turma_id and aluno_id:
        from app.models.professor_h5p import ProfessorAtividadeH5P, ProfessorProgressoH5P

        atividades_professor_turma = (
            db.query(ProfessorAtividadeH5P)
            .filter(
                ProfessorAtividadeH5P.turma_id == aluno_turma_id,
                ProfessorAtividadeH5P.ativo,
            )
            .order_by(ProfessorAtividadeH5P.created_at.desc())
            .all()
        )
        concl_rows = (
            db.query(ProfessorProgressoH5P.atividade_id)
            .filter(
                ProfessorProgressoH5P.aluno_id == aluno_id,
                ProfessorProgressoH5P.concluido,
            )
            .all()
        )
        atividades_professor_concluidas = {r[0] for r in concl_rows}

    progresso_por_trilha = {}
    trilhas_bloqueadas = set()
    total_atividades_geral = 0
    total_concluidas_geral = 0
    trilha_anterior_completa = True
    for t in trilhas:
        acts = atividades_por_trilha.get(t.id, [])
        total = len(acts)
        concluidas = sum(1 for a in acts if a.id in atividades_concluidas)
        pct = int((concluidas / total) * 100) if total else 0
        if not trilha_anterior_completa:
            trilhas_bloqueadas.add(t.id)
        total_atividades_geral += total
        total_concluidas_geral += concluidas
        progresso_por_trilha[t.id] = {
            "total": total,
            "concluidas": concluidas,
            "pct": pct,
        }
        trilha_anterior_completa = (total == 0) or (concluidas >= total)
    progresso_geral = {
        "total": total_atividades_geral,
        "concluidas": total_concluidas_geral,
        "pct": int((total_concluidas_geral / total_atividades_geral) * 100)
        if total_atividades_geral
        else 0,
    }

    from app.services.dashboard_service import DashboardService
    stats = DashboardService().get_aluno_stats(db, aluno_id) if aluno_id else {}

    return templates.TemplateResponse(
        request,
        template_name,
        {
            "aluno_nome": aluno_nome,
            "aluno_ano": aluno_ano,
            "stats": stats,
            "materia_nome": materia_nome,
            "materia_slug": materia_slug,
            "trilhas": trilhas,
            "atividades_por_trilha": atividades_por_trilha,
            "atividades_concluidas": atividades_concluidas,
            "descritores_por_trilha": descritores_por_trilha,
            "tipos_por_trilha": tipos_por_trilha,
            "progresso_por_trilha": progresso_por_trilha,
            "progresso_geral": progresso_geral,
            "trilhas_bloqueadas": trilhas_bloqueadas,
            "atividades_professor_turma": atividades_professor_turma,
            "atividades_professor_concluidas": atividades_professor_concluidas,
        },
    )


@page_router.get("/aluno/atividade/{id}")
def aluno_atividade(request: Request, id: int, db: Session = Depends(get_db)):
    """Página do player H5P standalone para a atividade."""
    from app.repositories.h5p_repository import AtividadeH5PRepository
    aluno_nome = _get_aluno_nome(request, db)
    atividade = AtividadeH5PRepository().get(db, id)
    if not atividade or not atividade.ativo:
        return RedirectResponse(url="/aluno/portugues", status_code=302)

    aluno_id = _get_aluno_id_from_request(request, db)
    if not aluno_id:
        # Tenta recuperar usuário autenticado e autocriar perfil de aluno se estiver faltando.
        token = request.cookies.get("access_token")
        if not token:
            return RedirectResponse(url="/login", status_code=302)
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            email = payload.get("sub")
            user = user_repo.get_by_email(db, email) if email else None
            if not user:
                return RedirectResponse(url="/login", status_code=302)
            if str(getattr(user, "role", "")).lower() not in {"aluno", "userrole.aluno"}:
                return RedirectResponse(url="/", status_code=302)

            from app.models.aluno import Aluno, PontuacaoGamificacao
            existing = db.query(Aluno).filter(Aluno.usuario_id == user.id).first()
            if existing:
                aluno_id = existing.id
            else:
                ano_default = (
                    getattr(getattr(atividade, "trilha", None), "ano_escolar", None) or 1
                )
                novo = Aluno(usuario_id=user.id, turma_id=None, ano_escolar=int(ano_default))
                db.add(novo)
                db.commit()
                db.refresh(novo)
                db.add(PontuacaoGamificacao(aluno_id=novo.id, xp_total=0, nivel="Novato"))
                db.commit()
                aluno_id = novo.id
        except JWTError:
            return RedirectResponse(url="/login", status_code=302)

    aluno_ano = None
    from app.models.aluno import Aluno
    aluno = db.query(Aluno).filter(Aluno.id == aluno_id).first()
    aluno_ano = aluno.ano_escolar if aluno else None

    # Segurança: aluno só acessa atividades da trilha do próprio ano (ou trilha sem ano definido)
    if atividade.trilha_id:
        from app.repositories.gestao_repository import TrilhaRepository
        trilha = TrilhaRepository().get(db, atividade.trilha_id)
        if trilha and aluno_ano and trilha.ano_escolar and trilha.ano_escolar != aluno_ano:
            destino_ano = "/aluno/matematica" if "mat" in ((trilha.curso.nome or "").lower() if getattr(trilha, "curso", None) else "") else "/aluno/portugues"
            return RedirectResponse(url=f"{destino_ano}?acesso_negado_ano=1", status_code=302)

    # Segurança adicional: trilha N só libera quando trilha N-1 estiver 100%.
    if atividade.trilha_id and aluno_id:
        from app.models.h5p import ProgressoH5P
        from app.repositories.gestao_repository import TrilhaRepository
        from app.repositories.h5p_repository import AtividadeH5PRepository, ProgressoH5PRepository

        trilha_atual = TrilhaRepository().get(db, atividade.trilha_id)
        if trilha_atual:
            trilhas_mesmo_curso = TrilhaRepository().listar(
                db,
                curso_id=trilha_atual.curso_id,
                ano_escolar=trilha_atual.ano_escolar,
            )
            idx = next((i for i, tr in enumerate(trilhas_mesmo_curso) if tr.id == trilha_atual.id), 0)
            if idx > 0:
                trilha_anterior = trilhas_mesmo_curso[idx - 1]
                acts_prev = AtividadeH5PRepository().listar(db, trilha_id=trilha_anterior.id, ativo_only=True)
                if acts_prev:
                    concl_ids = {
                        r[0]
                        for r in db.query(ProgressoH5P.atividade_id)
                        .filter(
                            ProgressoH5P.aluno_id == aluno_id,
                            ProgressoH5P.concluido,
                        )
                        .all()
                    }
                    if any(a.id not in concl_ids for a in acts_prev):
                        destino = "/aluno/matematica" if "mat" in (((trilha_atual.curso.nome if getattr(trilha_atual, "curso", None) else "") or "").lower()) else "/aluno/portugues"
                        return RedirectResponse(url=f"{destino}?acesso_bloqueado_trilha=1", status_code=302)

    atividade_concluida = False
    if aluno_id:
        from app.repositories.h5p_repository import ProgressoH5PRepository
        progresso = ProgressoH5PRepository().get(db, aluno_id, id)
        atividade_concluida = bool(progresso and progresso.concluido)

    from app.services.dashboard_service import DashboardService
    stats = DashboardService().get_aluno_stats(db, aluno_id) if aluno_id else {}
    completion_token = ""
    if aluno_id:
        completion_token = jwt.encode(
            {
                "scope": "h5p_complete",
                "atividade_id": id,
                "aluno_id": aluno_id,
                "exp": datetime.now(timezone.utc) + timedelta(minutes=120),
            },
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        )
    content_base_url = ""
    content_missing_reason = None
    if atividade.path_ou_json:
        raw_path = atividade.path_ou_json.strip().replace("\\", "/").strip("/")
        path_obj = Path(raw_path)
        h5p_base_dir = Path(settings.H5P_CONTENT_DIR).resolve()

        def _normalize_candidates(value: str) -> list[str]:
            v = (value or "").strip("/").replace("\\", "/")
            out = [v]
            if v.startswith("static/h5p/"):
                out.append(v[len("static/h5p/"):])
            if v.startswith("h5p/"):
                out.append(v[len("h5p/"):])
            # remove duplicados mantendo ordem
            seen = set()
            uniq = []
            for c in out:
                if c and c not in seen:
                    seen.add(c)
                    uniq.append(c)
            return uniq

        def _pick_valid_h5p_dir(candidates_rel: list[str]) -> Optional[str]:
            for rel in candidates_rel:
                full = (h5p_base_dir / rel).resolve()
                try:
                    full.relative_to(h5p_base_dir)
                except ValueError:
                    continue
                if full.is_dir() and (full / "h5p.json").is_file():
                    return rel
            return None

        # Novo padrão: path_ou_json aponta para pasta do pacote
        if path_obj.suffix.lower() != ".json":
            rel = _pick_valid_h5p_dir(_normalize_candidates(raw_path))
            if rel:
                content_base_url = f"/static/h5p/{rel}"
        else:
            # Compatibilidade com registros antigos: .../content/content.json
            parts = path_obj.parts
            if len(parts) >= 2 and parts[-2].lower() == "content":
                base_parts = "/".join(parts[:-2])
                rel = _pick_valid_h5p_dir(_normalize_candidates(base_parts))
                if rel:
                    content_base_url = f"/static/h5p/{rel}"

        if not content_base_url:
            content_missing_reason = (
                "Conteúdo H5P não encontrado no servidor. "
                "Peça ao admin para reenviar o arquivo .h5p desta atividade."
            )

    trilhas_url = "/aluno/matematica" if "mat" in (
        atividade.trilha.curso.nome.lower()
        if getattr(getattr(atividade, "trilha", None), "curso", None)
        else ""
    ) else "/aluno/portugues"
    next_atividade_url = None
    if atividade.trilha_id:
        from app.repositories.h5p_repository import AtividadeH5PRepository
        atividades_trilha = AtividadeH5PRepository().listar(
            db, trilha_id=atividade.trilha_id, ativo_only=True
        )
        for idx, item in enumerate(atividades_trilha):
            if item.id == atividade.id and idx + 1 < len(atividades_trilha):
                next_atividade_url = f"/aluno/atividade/{atividades_trilha[idx + 1].id}"
                break

    tipo_para_template = {
        "quiz": "aluno/atividade_h5p_quiz.html",
        "drag-drop": "aluno/atividade_h5p_drag_drop.html",
        "video": "aluno/atividade_h5p_video.html",
        "flashcards": "aluno/atividade_h5p_flashcards.html",
        "presentation": "aluno/atividade_h5p_presentation.html",
    }
    template_path = tipo_para_template.get(atividade.tipo, "aluno/atividade_h5p_outro.html")

    return templates.TemplateResponse(
        request,
        template_path,
        {
            "aluno_nome": aluno_nome,
            "aluno_ano": aluno_ano,
            "stats": stats,
            "atividade": atividade,
            "content_base_url": content_base_url,
            "content_missing_reason": content_missing_reason,
            "trilhas_url": trilhas_url,
            "next_atividade_url": next_atividade_url,
            "completion_token": completion_token,
            "atividade_concluida": atividade_concluida,
        },
    )


@page_router.post("/aluno/atividade/{id}")
async def aluno_atividade_post(id: int, request: Request, db: Session = Depends(get_db)):
    """
    Fallback defensivo:
    alguns conteúdos H5P disparam submit HTML para a rota da página.
    Registra conclusão/XP quando possível e redireciona para GET.
    """
    from app.repositories.h5p_repository import AtividadeH5PRepository, ProgressoH5PRepository
    from app.models.aluno import PontuacaoGamificacao
    from app.core.gamification_rules import calculate_xp_gain, get_level_progress

    atividade = AtividadeH5PRepository().get(db, id)
    aluno_id = _get_aluno_id_from_request(request, db)

    if atividade and aluno_id:
        payload = None
        try:
            payload = await request.json()
        except Exception:
            try:
                form = await request.form()
                payload = dict(form)
            except Exception:
                payload = None

        score = _extract_score_from_payload(payload)
        progresso_repo = ProgressoH5PRepository()
        progresso_atual = progresso_repo.get(db, aluno_id, id)
        primeira_conclusao = not (progresso_atual and progresso_atual.concluido)
        progresso_repo.marcar_concluido(db, aluno_id, id, score=score)

        if primeira_conclusao:
            gamificacao = (
                db.query(PontuacaoGamificacao)
                .filter(PontuacaoGamificacao.aluno_id == aluno_id)
                .first()
            )
            if not gamificacao:
                gamificacao = PontuacaoGamificacao(aluno_id=aluno_id, xp_total=0, nivel="Novato")
                db.add(gamificacao)
                db.commit()
                db.refresh(gamificacao)

            ganho_xp = calculate_xp_gain(
                activity_type=getattr(atividade, "tipo", "outro"),
                score=score,
                is_first_completion=True,
            )
            gamificacao.xp_total = int((gamificacao.xp_total or 0) + ganho_xp)
            nivel_info = get_level_progress(gamificacao.xp_total)
            gamificacao.nivel = nivel_info["nivel"]
            db.commit()

    return RedirectResponse(url=f"/aluno/atividade/{id}", status_code=303)


@page_router.get("/aluno/atividade-professor/{id}")
def aluno_atividade_professor(request: Request, id: int, db: Session = Depends(get_db)):
    from app.models.aluno import Aluno
    from app.models.professor_h5p import ProfessorAtividadeH5P, ProfessorProgressoH5P
    from app.services.dashboard_service import DashboardService

    aluno_nome = _get_aluno_nome(request, db)
    aluno_id = _get_aluno_id_from_request(request, db)
    if not aluno_id:
        return RedirectResponse(url="/login", status_code=302)
    aluno = db.query(Aluno).filter(Aluno.id == aluno_id).first()
    if not aluno:
        return RedirectResponse(url="/login", status_code=302)

    atividade = db.query(ProfessorAtividadeH5P).filter(ProfessorAtividadeH5P.id == id, ProfessorAtividadeH5P.ativo).first()
    if not atividade or not aluno.turma_id or atividade.turma_id != aluno.turma_id:
        return RedirectResponse(url="/aluno/portugues?acesso_negado_ano=1", status_code=302)

    progresso = db.query(ProfessorProgressoH5P).filter(
        ProfessorProgressoH5P.aluno_id == aluno_id,
        ProfessorProgressoH5P.atividade_id == id,
    ).first()
    atividade_concluida = bool(progresso and progresso.concluido)
    stats = DashboardService().get_aluno_stats(db, aluno_id)

    content_base_url = ""
    if atividade.path_ou_json:
        raw_path = atividade.path_ou_json.strip().replace("\\", "/").strip("/")
        h5p_base_dir = Path(settings.H5P_CONTENT_DIR).resolve()
        full = (h5p_base_dir / raw_path).resolve()
        try:
            full.relative_to(h5p_base_dir)
            if full.is_dir() and (full / "h5p.json").is_file():
                content_base_url = f"/static/h5p/{raw_path}"
        except ValueError:
            content_base_url = ""

    return templates.TemplateResponse(
        request,
        "aluno/atividade_h5p_professor.html",
        {
            "aluno_nome": aluno_nome,
            "aluno_ano": aluno.ano_escolar,
            "stats": stats,
            "atividade": atividade,
            "content_base_url": content_base_url,
            "content_missing_reason": None if content_base_url else "Conteúdo H5P não encontrado.",
            "trilhas_url": "/aluno/portugues",
            "next_atividade_url": "/aluno/portugues",
            "completion_token": "",
            "atividade_concluida": atividade_concluida,
            "completion_endpoint": f"/api/h5p/professor-atividades/{id}/concluir",
            "manual_completion_enabled": True,
        },
    )


@page_router.post("/aluno/atividade-professor/{id}")
async def aluno_atividade_professor_post(id: int, request: Request, db: Session = Depends(get_db)):
    from app.core.gamification_rules import calculate_xp_gain, get_level_progress
    from app.models.aluno import Aluno, PontuacaoGamificacao
    from app.models.professor_h5p import ProfessorAtividadeH5P, ProfessorProgressoH5P

    aluno_id = _get_aluno_id_from_request(request, db)
    if not aluno_id:
        return RedirectResponse(url="/login", status_code=302)
    aluno = db.query(Aluno).filter(Aluno.id == aluno_id).first()
    atividade = db.query(ProfessorAtividadeH5P).filter(ProfessorAtividadeH5P.id == id, ProfessorAtividadeH5P.ativo).first()
    if not aluno or not atividade or not aluno.turma_id or atividade.turma_id != aluno.turma_id:
        return RedirectResponse(url="/aluno/portugues?acesso_negado_ano=1", status_code=302)

    payload = None
    try:
        payload = await request.json()
    except Exception:
        try:
            form = await request.form()
            payload = dict(form)
        except Exception:
            payload = None
    score = _extract_score_from_payload(payload)

    progresso = db.query(ProfessorProgressoH5P).filter(
        ProfessorProgressoH5P.aluno_id == aluno_id,
        ProfessorProgressoH5P.atividade_id == id,
    ).first()
    primeira_conclusao = not (progresso and progresso.concluido)
    if not progresso:
        progresso = ProfessorProgressoH5P(aluno_id=aluno_id, atividade_id=id, tentativas=0)
        db.add(progresso)
    progresso.tentativas = int((progresso.tentativas or 0) + 1)
    progresso.concluido = True
    progresso.score = score
    progresso.data_conclusao = datetime.utcnow()
    db.commit()

    if primeira_conclusao:
        gamificacao = db.query(PontuacaoGamificacao).filter(PontuacaoGamificacao.aluno_id == aluno_id).first()
        if not gamificacao:
            gamificacao = PontuacaoGamificacao(aluno_id=aluno_id, xp_total=0, nivel="Novato")
            db.add(gamificacao)
            db.commit()
            db.refresh(gamificacao)
        ganho_xp = calculate_xp_gain(
            activity_type=getattr(atividade, "tipo", "outro"),
            score=score,
            is_first_completion=True,
        )
        gamificacao.xp_total = int((gamificacao.xp_total or 0) + ganho_xp)
        gamificacao.nivel = get_level_progress(gamificacao.xp_total)["nivel"]
        db.commit()

    return RedirectResponse(url=f"/aluno/atividade-professor/{id}", status_code=303)


@page_router.post("/aluno")
async def criar_aluno_web(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    nome, email, senha = _sanitize_signup_fields(form.get("nome"), form.get("email"), form.get("senha"))
    turma_id = _as_int(form.get("turma_id"))
    ano = _as_int(form.get("ano"))

    if not nome or not email or not senha:
        return RedirectResponse(url="/cadastro?erro=campos_obrigatorios", status_code=303)
    if len(senha) < 6:
        return RedirectResponse(url="/cadastro?erro=senha_curta", status_code=303)
    if turma_id is None or ano is None:
        return RedirectResponse(url="/cadastro?erro=turma_ano_obrigatorios", status_code=303)
    if user_repo.get_by_email(db, email):
        return RedirectResponse(url="/cadastro?erro=email_duplicado", status_code=303)

    user = UserCreate(
        nome=nome,
        email=email,
        senha=senha,
        role=UserRole.ALUNO,
    )
    novo_user = None
    try:
        novo_user = user_repo.create(db, user)
        aluno_repo.create(db, novo_user.id, turma_id, ano)
        access_token = criar_token_acesso({"sub": novo_user.email})
        refresh_token = criar_refresh_token({"sub": novo_user.email})
        response = RedirectResponse(url="/aluno", status_code=303)
        response.set_cookie(
            key=settings.ACCESS_COOKIE_NAME,
            value=access_token,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite="lax",
            domain=settings.COOKIE_DOMAIN,
        )
        response.set_cookie(
            key=settings.REFRESH_COOKIE_NAME,
            value=refresh_token,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite="lax",
            domain=settings.COOKIE_DOMAIN,
        )
        return response
    except IntegrityError:
        db.rollback()
        return RedirectResponse(url="/cadastro?erro=email_duplicado", status_code=303)
    except Exception:
        db.rollback()
        # Evita estado parcial (usuário criado sem perfil de aluno)
        if novo_user:
            try:
                user_repo.delete(db, novo_user.id)
            except Exception:
                db.rollback()
        return RedirectResponse(url="/cadastro?erro=falha_cadastro", status_code=303)


@page_router.get("/aluno/suporte/chamado")
def aluno_suporte_chamado_get(request: Request, db: Session = Depends(get_db)):
    aluno_id = _get_aluno_id_from_request(request, db)
    if not aluno_id:
        return RedirectResponse(url="/login", status_code=302)
    token = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    user = None
    if token:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            email = payload.get("sub")
            if email:
                user = user_repo.get_by_email(db, email)
        except JWTError:
            user = None

    from app.services.dashboard_service import DashboardService
    from app.models.aluno import Aluno

    aluno = db.query(Aluno).filter(Aluno.id == aluno_id).first()
    return templates.TemplateResponse(
        request,
        "aluno/suporte_chamado.html",
        {
            "aluno_nome": _get_aluno_nome(request, db),
            "aluno_ano": (aluno.ano_escolar if aluno else None),
            "stats": DashboardService().get_aluno_stats(db, aluno_id),
            "email_default": (getattr(user, "email", "") or ""),
            "erro": request.query_params.get("erro"),
            "ok": request.query_params.get("ok"),
        },
    )


@page_router.post("/aluno/suporte/chamado")
async def aluno_suporte_chamado_post(request: Request, db: Session = Depends(get_db)):
    from datetime import datetime
    from app.models.support_ticket import SupportTicket, SupportTicketMessage

    aluno_id = _get_aluno_id_from_request(request, db)
    if not aluno_id:
        return RedirectResponse(url="/login", status_code=302)
    token = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    current_user = None
    if token:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            email = payload.get("sub")
            if email:
                current_user = user_repo.get_by_email(db, email)
        except JWTError:
            current_user = None

    form = await request.form()
    email = (form.get("email") or "").strip()
    assunto = (form.get("assunto") or "").strip()
    mensagem = (form.get("mensagem") or "").strip()
    if current_user and getattr(current_user, "email", None):
        email = email or current_user.email
    if not email or not assunto or not mensagem:
        return RedirectResponse(url="/aluno/suporte/chamado?erro=campos", status_code=303)

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
    return RedirectResponse(url="/aluno/suporte/chamado?ok=1", status_code=303)


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
        nome, email, senha = _sanitize_signup_fields(
            payload.get("nome"),
            payload.get("email"),
            payload.get("senha"),
        )
        user = UserCreate(
            nome=nome,
            email=email,
            senha=senha,
            role=payload.get("role", "aluno"),
        )
        turma_id = turma_id if turma_id is not None else payload.get("turma_id")
        ano = ano if ano is not None else payload.get("ano")
    else:
        form = await request.form()
        nome, email, senha = _sanitize_signup_fields(
            form.get("nome"),
            form.get("email"),
            form.get("senha"),
        )
        user = UserCreate(
            nome=nome,
            email=email,
            senha=senha,
            role="aluno",
        )
        turma_id = turma_id if turma_id is not None else form.get("turma_id")
        ano = ano if ano is not None else form.get("ano")

    turma_id_int = _as_int(turma_id)
    ano_int = _as_int(ano)
    if not nome or not email or not senha:
        if accepts_html:
            return RedirectResponse(url="/cadastro?erro=campos_obrigatorios", status_code=303)
        raise HTTPException(status_code=422, detail="nome, email e senha são obrigatórios")
    if len(senha) < 6:
        if accepts_html:
            return RedirectResponse(url="/cadastro?erro=senha_curta", status_code=303)
        raise HTTPException(status_code=422, detail="senha deve ter ao menos 6 caracteres")
    if turma_id_int is None or ano_int is None:
        if accepts_html:
            return RedirectResponse(url="/cadastro?erro=turma_ano_obrigatorios", status_code=303)
        raise HTTPException(status_code=422, detail="turma_id e ano sao obrigatorios")
    if user_repo.get_by_email(db, email):
        if accepts_html:
            return RedirectResponse(url="/cadastro?erro=email_duplicado", status_code=303)
        raise HTTPException(status_code=409, detail="email já cadastrado")

    novo_user = None
    try:
        novo_user = user_repo.create(db, user)
        aluno_repo.create(db, novo_user.id, turma_id_int, ano_int)
    except IntegrityError:
        db.rollback()
        if accepts_html:
            return RedirectResponse(url="/cadastro?erro=email_duplicado", status_code=303)
        raise HTTPException(status_code=409, detail="email já cadastrado")
    except Exception:
        db.rollback()
        if novo_user:
            try:
                user_repo.delete(db, novo_user.id)
            except Exception:
                db.rollback()
        if accepts_html:
            return RedirectResponse(url="/cadastro?erro=falha_cadastro", status_code=303)
        raise HTTPException(status_code=500, detail="falha ao finalizar cadastro de aluno")

    if accepts_html:
        return RedirectResponse(url="/aluno", status_code=303)
    return novo_user
