from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import Optional, List, Sequence
from pathlib import Path
import re
import shutil
import zipfile
import uuid

from app.core.database import get_db
from app.core.config import settings
from app.core.dependencies import require_admin_redirect
from app.models.user import Usuario, UserRole
from app.models.relacoes import ProfessorTurma, GestorEscola, CoordenadorEscola
from app.repositories.gestao_repository import (
    EscolaRepository,
    TurmaRepository,
    CursoRepository,
    TrilhaRepository,
)
from app.repositories.saeb_repository import DescritorRepository
from app.repositories.h5p_repository import AtividadeH5PRepository
from app.repositories.user_repository import UserRepository
from app.repositories.aluno_repository import AlunoRepository
from app.models.aluno import Aluno
from app.services.h5p_upload_service import save_h5p_upload

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _slugify(value: str, default: str = "atividade") -> str:
    raw = (value or "").strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw)
    raw = raw.strip("-")
    return raw or default


def _get_materia_ano_from_trilha(db: Session, trilha_id: Optional[int]) -> tuple[str, str]:
    # fallback padrão quando trilha não foi selecionada
    materia = "geral"
    ano = "ano-geral"
    if not trilha_id:
        return materia, ano

    trilha = TrilhaRepository().get(db, trilha_id)
    if not trilha:
        return materia, ano

    curso_nome = (trilha.curso.nome if getattr(trilha, "curso", None) else "").lower()
    if "mat" in curso_nome:
        materia = "matematica"
    elif "port" in curso_nome:
        materia = "portugues"

    if trilha.ano_escolar:
        ano = f"ano-{trilha.ano_escolar}"
    return materia, ano


def _save_h5p_upload(
    db: Session,
    arquivo_h5p: UploadFile,
    titulo: str,
    trilha_id: Optional[int],
) -> str:
    return save_h5p_upload(db, arquivo_h5p, titulo, trilha_id=trilha_id)


def _validate_h5p_archive_file(arquivo_h5p: UploadFile) -> tuple[bool, str]:
    if not arquivo_h5p or not arquivo_h5p.filename:
        return False, "Selecione um arquivo .h5p para validar"
    if not arquivo_h5p.filename.lower().endswith(".h5p"):
        return False, "Apenas arquivos .h5p são aceitos"

    arquivo_h5p.file.seek(0)
    try:
        with zipfile.ZipFile(arquivo_h5p.file, "r") as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        return False, "Arquivo .h5p inválido ou corrompido"
    finally:
        arquivo_h5p.file.seek(0)

    if "h5p.json" not in names:
        return False, "Pacote inválido: h5p.json ausente"
    if "content/content.json" not in names:
        return False, "Pacote inválido: content/content.json ausente"
    return True, "Arquivo H5P válido para uso no player standalone"


def _resolve_h5p_storage_target(path_ou_json: str) -> Optional[Path]:
    """
    Resolve o caminho físico que deve ser removido para conteúdos H5P locais.
    Remove apenas arquivos/pastas dentro de settings.H5P_CONTENT_DIR.
    """
    raw = (path_ou_json or "").strip().replace("\\", "/").strip("/")
    if not raw:
        return None
    from app.core.media_urls import h5p_content_root

    base_dir = h5p_content_root()
    candidate = (base_dir / raw).resolve()
    try:
        candidate.relative_to(base_dir)
    except ValueError:
        return None

    def _is_safe_package_dir(dir_path: Path) -> bool:
        """
        Só permite apagar diretório de pacote específico, nunca pastas amplas.
        Requisitos:
        - dentro de H5P_CONTENT_DIR
        - estrutura mínima: materia/ano-*/pacote
        - contém h5p.json e content/content.json
        """
        try:
            rel = dir_path.relative_to(base_dir)
        except ValueError:
            return False
        parts = rel.parts
        if len(parts) < 3:
            return False
        if not parts[1].startswith("ano-"):
            return False
        if not (dir_path / "h5p.json").is_file():
            return False
        if not (dir_path / "content" / "content.json").is_file():
            return False
        return True

    # Novo formato: path aponta para a pasta do pacote extraído
    if candidate.exists() and candidate.is_dir():
        return candidate if _is_safe_package_dir(candidate) else None

    # Compatibilidade antiga: path termina em content/content.json
    if candidate.suffix.lower() == ".json":
        parts = candidate.parts
        if len(parts) >= 2 and parts[-2].lower() == "content":
            pkg_dir = candidate.parent.parent
            try:
                pkg_dir.relative_to(base_dir)
            except ValueError:
                return None
            if pkg_dir.exists() and _is_safe_package_dir(pkg_dir):
                return pkg_dir
            return None
        # Não remove arquivos soltos para evitar exclusão indevida.
        return None
    return None


def _remove_atividade_h5p_com_arquivos(db: Session, atividade_id: int) -> bool:
    atividade = AtividadeH5PRepository().get(db, atividade_id)
    if not atividade:
        return False
    from app.models.h5p import ProgressoH5P
    db.query(ProgressoH5P).filter(ProgressoH5P.atividade_id == atividade_id).delete()
    db.commit()
    if not AtividadeH5PRepository().delete(db, atividade_id):
        return False
    target = _resolve_h5p_storage_target(atividade.path_ou_json or "")
    if target:
        try:
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.is_file():
                target.unlink(missing_ok=True)
        except Exception:
            pass
    return True


# --- Escolas ---
@router.get("/escolas")
def escolas_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    escolas = EscolaRepository().listar(db, ativo_only=False)
    return templates.TemplateResponse(
        request,
        "admin/escolas_list.html",
        {"request": request, "escolas": escolas},
    )


@router.get("/escolas/nova")
def escolas_nova(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    return templates.TemplateResponse(
        request,
        "admin/escola_form.html",
        {"request": request, "escola": None},
    )


@router.get("/escolas/{id}/editar")
def escolas_editar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    escola = EscolaRepository().get(db, id)
    if not escola:
        return RedirectResponse(url="/admin/escolas", status_code=302)
    return templates.TemplateResponse(
        request,
        "admin/escola_form.html",
        {"request": request, "escola": escola},
    )


@router.post("/escolas/nova")
def escolas_criar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    nome: str = Form(...),
    ativo: Optional[str] = Form(None),
    endereco: Optional[str] = Form(None),
):
    from app.schemas.gestao_schema import EscolaCreate
    data = EscolaCreate(nome=nome, ativo=(ativo or "").lower() == "true", endereco=endereco or None)
    EscolaRepository().create(db, data)
    return RedirectResponse(url="/admin/escolas", status_code=303)


@router.post("/escolas/{id}/editar")
def escolas_atualizar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    nome: str = Form(...),
    ativo: Optional[str] = Form(None),
    endereco: Optional[str] = Form(None),
):
    from app.schemas.gestao_schema import EscolaUpdate
    data = EscolaUpdate(nome=nome, ativo=(ativo or "").lower() == "true", endereco=endereco or None)
    if not EscolaRepository().update(db, id, data):
        return RedirectResponse(url="/admin/escolas", status_code=302)
    return RedirectResponse(url="/admin/escolas", status_code=303)


@router.post("/escolas/{id}/deletar")
def escolas_deletar(
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    # Evita remover escola com turmas vinculadas.
    if TurmaRepository().listar(db, escola_id=id):
        return RedirectResponse(url="/admin/escolas?erro=vinculos", status_code=303)
    try:
        if not EscolaRepository().delete(db, id):
            return RedirectResponse(url="/admin/escolas", status_code=302)
    except IntegrityError:
        db.rollback()
        return RedirectResponse(url="/admin/escolas?erro=vinculos", status_code=303)
    return RedirectResponse(url="/admin/escolas?ok=deletado", status_code=303)


# --- Turmas ---
@router.get("/turmas")
def turmas_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    escola_id: Optional[int] = None,
):
    turmas = TurmaRepository().listar(db, escola_id=escola_id)
    escolas = EscolaRepository().listar(db, ativo_only=False)
    return templates.TemplateResponse(
        request,
        "admin/turmas_list.html",
        {"request": request, "turmas": turmas, "escolas": escolas},
    )


@router.get("/turmas/nova")
def turmas_nova(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    escolas = EscolaRepository().listar(db, ativo_only=False)
    return templates.TemplateResponse(
        request,
        "admin/turma_form.html",
        {"request": request, "turma": None, "escolas": escolas},
    )


@router.get("/turmas/{id}/editar")
def turmas_editar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    turma = TurmaRepository().get(db, id)
    if not turma:
        return RedirectResponse(url="/admin/turmas", status_code=302)
    escolas = EscolaRepository().listar(db, ativo_only=False)
    return templates.TemplateResponse(
        request,
        "admin/turma_form.html",
        {"request": request, "turma": turma, "escolas": escolas},
    )


@router.post("/turmas/nova")
def turmas_criar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    nome: str = Form(...),
    ano_escolar: int = Form(...),
    escola_id: int = Form(...),
    ano_letivo: Optional[str] = Form(None),
):
    from app.schemas.gestao_schema import TurmaCreate
    data = TurmaCreate(nome=nome, ano_escolar=ano_escolar, escola_id=escola_id, ano_letivo=ano_letivo)
    TurmaRepository().create(db, data)
    return RedirectResponse(url="/admin/turmas", status_code=303)


@router.post("/turmas/{id}/editar")
def turmas_atualizar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    nome: str = Form(...),
    ano_escolar: int = Form(...),
    escola_id: int = Form(...),
    ano_letivo: Optional[str] = Form(None),
):
    from app.schemas.gestao_schema import TurmaUpdate
    data = TurmaUpdate(nome=nome, ano_escolar=ano_escolar, escola_id=escola_id, ano_letivo=ano_letivo)
    if not TurmaRepository().update(db, id, data):
        return RedirectResponse(url="/admin/turmas", status_code=302)
    return RedirectResponse(url="/admin/turmas", status_code=303)


@router.post("/turmas/{id}/deletar")
def turmas_deletar(
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    # Desvincula alunos desta turma para permitir deleção.
    db.query(Aluno).filter(Aluno.turma_id == id).update({"turma_id": None})
    db.commit()
    try:
        if not TurmaRepository().delete(db, id):
            return RedirectResponse(url="/admin/turmas", status_code=302)
    except IntegrityError:
        db.rollback()
        return RedirectResponse(url="/admin/turmas?erro=vinculos", status_code=303)
    return RedirectResponse(url="/admin/turmas?ok=deletado", status_code=303)


# --- Cursos ---
@router.get("/cursos")
def cursos_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    cursos = CursoRepository().listar(db)
    return templates.TemplateResponse(
        request,
        "admin/cursos_list.html",
        {"request": request, "cursos": cursos},
    )


@router.get("/cursos/nova")
def cursos_nova(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    return templates.TemplateResponse(
        request,
        "admin/curso_form.html",
        {"request": request, "curso": None},
    )


@router.get("/cursos/{id}/editar")
def cursos_editar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    curso = CursoRepository().get(db, id)
    if not curso:
        return RedirectResponse(url="/admin/cursos", status_code=302)
    return templates.TemplateResponse(
        request,
        "admin/curso_form.html",
        {"request": request, "curso": curso},
    )


@router.post("/cursos/nova")
def cursos_criar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    nome: str = Form(...),
):
    from app.schemas.gestao_schema import CursoCreate
    CursoRepository().create(db, CursoCreate(nome=nome))
    return RedirectResponse(url="/admin/cursos", status_code=303)


@router.post("/cursos/{id}/editar")
def cursos_atualizar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    nome: str = Form(...),
):
    from app.schemas.gestao_schema import CursoUpdate
    if not CursoRepository().update(db, id, CursoUpdate(nome=nome)):
        return RedirectResponse(url="/admin/cursos", status_code=302)
    return RedirectResponse(url="/admin/cursos", status_code=303)


@router.post("/cursos/{id}/deletar")
def cursos_deletar(
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    if TrilhaRepository().listar(db, curso_id=id):
        return RedirectResponse(url="/admin/cursos?erro=vinculos", status_code=303)
    try:
        if not CursoRepository().delete(db, id):
            return RedirectResponse(url="/admin/cursos", status_code=302)
    except IntegrityError:
        db.rollback()
        return RedirectResponse(url="/admin/cursos?erro=vinculos", status_code=303)
    return RedirectResponse(url="/admin/cursos?ok=deletado", status_code=303)


# --- Trilhas ---
@router.get("/trilhas")
def trilhas_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    curso_id: Optional[int] = None,
):
    trilhas = TrilhaRepository().listar(db, curso_id=curso_id)
    cursos = CursoRepository().listar(db)
    return templates.TemplateResponse(
        request,
        "admin/trilhas_list.html",
        {"request": request, "trilhas": trilhas, "cursos": cursos},
    )


@router.get("/trilhas/nova")
def trilhas_nova(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    cursos = CursoRepository().listar(db)
    return templates.TemplateResponse(
        request,
        "admin/trilha_form.html",
        {"request": request, "trilha": None, "cursos": cursos},
    )


@router.get("/trilhas/{id}/editar")
def trilhas_editar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    trilha = TrilhaRepository().get(db, id)
    if not trilha:
        return RedirectResponse(url="/admin/trilhas", status_code=302)
    cursos = CursoRepository().listar(db)
    return templates.TemplateResponse(
        request,
        "admin/trilha_form.html",
        {"request": request, "trilha": trilha, "cursos": cursos},
    )


@router.post("/trilhas/nova")
def trilhas_criar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    nome: str = Form(...),
    curso_id: int = Form(...),
    ano_escolar: Optional[str] = Form(None),
    ordem: int = Form(0),
):
    from app.schemas.gestao_schema import TrilhaCreate
    ano_int = int(ano_escolar) if ano_escolar and ano_escolar.strip() else None
    data = TrilhaCreate(nome=nome, curso_id=curso_id, ano_escolar=ano_int, ordem=ordem)
    TrilhaRepository().create(db, data)
    return RedirectResponse(url="/admin/trilhas", status_code=303)


@router.post("/trilhas/{id}/editar")
def trilhas_atualizar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    nome: str = Form(...),
    curso_id: int = Form(...),
    ano_escolar: Optional[str] = Form(None),
    ordem: int = Form(0),
):
    from app.schemas.gestao_schema import TrilhaUpdate
    ano_int = int(ano_escolar) if ano_escolar and ano_escolar.strip() else None
    data = TrilhaUpdate(nome=nome, curso_id=curso_id, ano_escolar=ano_int, ordem=ordem)
    if not TrilhaRepository().update(db, id, data):
        return RedirectResponse(url="/admin/trilhas", status_code=302)
    return RedirectResponse(url="/admin/trilhas", status_code=303)


@router.post("/trilhas/{id}/deletar")
def trilhas_deletar(
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    atividades = AtividadeH5PRepository().listar(db, trilha_id=id, ativo_only=False)
    for a in atividades:
        _remove_atividade_h5p_com_arquivos(db, a.id)
    try:
        if not TrilhaRepository().delete(db, id):
            return RedirectResponse(url="/admin/trilhas", status_code=302)
    except IntegrityError:
        db.rollback()
        return RedirectResponse(url="/admin/trilhas?erro=vinculos", status_code=303)
    return RedirectResponse(url="/admin/trilhas?ok=deletado", status_code=303)


# --- Descritores ---
@router.get("/descritores")
def descritores_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    disciplina: Optional[str] = None,
):
    descritores = DescritorRepository().listar(db, disciplina=disciplina)
    return templates.TemplateResponse(
        request,
        "admin/descritores_list.html",
        {"request": request, "descritores": descritores},
    )


@router.get("/descritores/novo")
def descritores_novo(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    return templates.TemplateResponse(
        request,
        "admin/descritor_form.html",
        {"request": request, "descritor": None},
    )


@router.get("/descritores/{id}/editar")
def descritores_editar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    descritor = DescritorRepository().get(db, id)
    if not descritor:
        return RedirectResponse(url="/admin/descritores", status_code=302)
    return templates.TemplateResponse(
        request,
        "admin/descritor_form.html",
        {"request": request, "descritor": descritor},
    )


@router.post("/descritores/novo")
def descritores_criar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    codigo: str = Form(...),
    descricao: str = Form(...),
    disciplina: str = Form(...),
):
    DescritorRepository().create(db, codigo, descricao, disciplina)
    return RedirectResponse(url="/admin/descritores", status_code=303)


@router.post("/descritores/{id}/editar")
def descritores_atualizar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    codigo: str = Form(...),
    descricao: str = Form(...),
    disciplina: str = Form(...),
):
    from app.schemas.saeb_schema import DescritorUpdate
    data = DescritorUpdate(codigo=codigo, descricao=descricao, disciplina=disciplina)
    if not DescritorRepository().update(db, id, data.codigo, data.descricao, data.disciplina):
        return RedirectResponse(url="/admin/descritores", status_code=302)
    return RedirectResponse(url="/admin/descritores", status_code=303)


@router.post("/descritores/{id}/deletar")
def descritores_deletar(
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    # Remove vínculo de atividades antes de deletar descritor.
    from app.models.h5p import AtividadeH5P
    db.query(AtividadeH5P).filter(AtividadeH5P.descritor_id == id).update({"descritor_id": None})
    db.commit()
    try:
        if not DescritorRepository().delete(db, id):
            return RedirectResponse(url="/admin/descritores", status_code=302)
    except IntegrityError:
        db.rollback()
        return RedirectResponse(url="/admin/descritores?erro=vinculos", status_code=303)
    return RedirectResponse(url="/admin/descritores?ok=deletado", status_code=303)


# --- Usuários ---
def _set_professor_turmas(db: Session, professor_id: int, turma_ids: Optional[List[int]]) -> None:
    db.query(ProfessorTurma).filter(ProfessorTurma.professor_id == professor_id).delete()
    if turma_ids:
        for tid in turma_ids:
            db.add(ProfessorTurma(professor_id=professor_id, turma_id=tid))
    db.commit()


def _set_gestor_escolas(db: Session, gestor_id: int, escola_ids: Optional[List[int]]) -> None:
    db.query(GestorEscola).filter(GestorEscola.gestor_id == gestor_id).delete()
    if escola_ids:
        for eid in escola_ids:
            db.add(GestorEscola(gestor_id=gestor_id, escola_id=eid))
    db.commit()


def _set_coordenador_escola(db: Session, coordenador_id: int, escola_id: Optional[int]) -> None:
    db.query(CoordenadorEscola).filter(
        CoordenadorEscola.coordenador_id == coordenador_id
    ).delete()
    if escola_id:
        db.add(CoordenadorEscola(coordenador_id=coordenador_id, escola_id=escola_id))
    db.commit()


def _parse_int_list(value: Optional[Sequence[str]]) -> List[int]:
    """
    Converte o valor vindo do formulário (que pode ser string única ou lista de strings)
    em uma lista de inteiros.
    """
    if value is None:
        return []
    if isinstance(value, str):
        v = value.strip()
        return [int(v)] if v else []
    result: List[int] = []
    for item in value:
        s = str(item).strip()
        if s:
            result.append(int(s))
    return result


def _set_aluno_turma(db: Session, usuario_id: int, turma_id_raw: Optional[str], ano_raw: Optional[str]) -> None:
    """
    Garante que exista um registro de Aluno vinculado ao usuário, com turma e ano_escolar.
    Se já existir, atualiza; se não existir, cria.
    """
    if not turma_id_raw or not ano_raw:
        return
    try:
        turma_id = int(str(turma_id_raw))
        ano = int(str(ano_raw))
    except ValueError:
        return

    repo = AlunoRepository()
    aluno = db.query(Aluno).filter(Aluno.usuario_id == usuario_id).first()
    if not aluno:
        repo.create(db, usuario_id, turma_id, ano)
        return

    aluno.turma_id = turma_id
    aluno.ano_escolar = ano
    db.commit()


@router.get("/usuarios")
def usuarios_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    role: Optional[str] = None,
):
    role_enum = None
    if role:
        try:
            role_enum = UserRole(role)
        except ValueError:
            pass
    usuarios = UserRepository().listar(db, role=role_enum, ativo_only=False)
    return templates.TemplateResponse(
        request,
        "admin/usuarios_list.html",
        {"request": request, "usuarios": usuarios},
    )


@router.get("/usuarios/novo")
def usuarios_novo(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    escolas = EscolaRepository().listar(db, ativo_only=True)
    turmas = TurmaRepository().listar(db)
    return templates.TemplateResponse(
        request,
        "admin/usuario_form.html",
        {
            "request": request,
            "usuario": None,
            "roles": list(UserRole),
            "escolas": escolas,
            "turmas": turmas,
            "professor_turma_ids": [],
            "gestor_escola_ids": [],
            "coordenador_escola_id": None,
            "aluno_turma_id": None,
            "aluno_escola_id": None,
            "aluno_ano": None,
            "permite_cadastro_trilha_geral": False,
        },
    )


@router.get("/usuarios/{id}/editar")
def usuarios_editar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    usuario = UserRepository().get_by_id(db, id)
    if not usuario:
        return RedirectResponse(url="/admin/usuarios", status_code=302)
    escolas = EscolaRepository().listar(db, ativo_only=True)
    turmas = TurmaRepository().listar(db)
    professor_turma_ids = [pt.turma_id for pt in usuario.professor_turmas]
    gestor_escola_ids = [ge.escola_id for ge in usuario.gestor_escolas]
    coordenador_escola_id = (
        usuario.coordenador_escola.escola_id if usuario.coordenador_escola else None
    )

    aluno_turma_id = None
    aluno_escola_id = None
    aluno_ano = None
    aluno = db.query(Aluno).filter(Aluno.usuario_id == usuario.id).first()
    if aluno:
        aluno_turma_id = aluno.turma_id
        aluno_ano = aluno.ano_escolar
        if aluno_turma_id:
            for t in turmas:
                if t.id == aluno_turma_id:
                    aluno_escola_id = t.escola_id
                    break
    return templates.TemplateResponse(
        request,
        "admin/usuario_form.html",
        {
            "request": request,
            "usuario": usuario,
            "roles": list(UserRole),
            "escolas": escolas,
            "turmas": turmas,
            "professor_turma_ids": professor_turma_ids,
            "gestor_escola_ids": gestor_escola_ids,
            "coordenador_escola_id": coordenador_escola_id,
            "aluno_turma_id": aluno_turma_id,
            "aluno_escola_id": aluno_escola_id,
            "aluno_ano": aluno_ano,
            "permite_cadastro_trilha_geral": bool(getattr(usuario, "permite_cadastro_trilha_geral", False)),
        },
    )


@router.post("/usuarios/novo")
async def usuarios_criar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    form = await request.form()
    nome = form.get("nome")
    email = form.get("email")
    senha = form.get("senha")
    role = form.get("role") or "aluno"
    aluno_turma_id = form.get("aluno_turma_id")
    aluno_ano = form.get("aluno_ano")
    professor_turmas_raw = form.getlist("professor_turmas")
    gestor_escolas_raw = form.getlist("gestor_escolas")
    coordenador_escola_raw = form.get("coordenador_escola")
    permite_cadastro_trilha_geral = (form.get("permite_cadastro_trilha_geral") or "").lower() == "true"
    from app.schemas.user_schema import UserCreate

    try:
        role_enum = UserRole(role)
    except ValueError:
        role_enum = UserRole.ALUNO

    data = UserCreate(
        nome=nome,
        email=email,
        senha=senha,
        role=role_enum,
        permite_cadastro_trilha_geral=(permite_cadastro_trilha_geral if role_enum == UserRole.PROFESSOR else False),
    )
    try:
        user = UserRepository().create(db, data)
    except Exception:
        return RedirectResponse(url="/admin/usuarios/novo?erro=email", status_code=303)

    prof_turma_ids = _parse_int_list(professor_turmas_raw)
    gestor_escola_ids = _parse_int_list(gestor_escolas_raw)
    coord_escola_id: Optional[int] = None
    if coordenador_escola_raw is not None and str(coordenador_escola_raw).strip():
        coord_escola_id = int(str(coordenador_escola_raw).strip())

    if user.role == UserRole.PROFESSOR:
        _set_professor_turmas(db, user.id, prof_turma_ids)
        u = UserRepository().get_by_id(db, user.id)
        if u:
            u.moodle_user_id = (form.get("moodle_user_id") or "").strip() or None
            db.commit()
    elif user.role == UserRole.GESTOR:
        _set_gestor_escolas(db, user.id, gestor_escola_ids)
    elif user.role == UserRole.COORDENADOR:
        _set_coordenador_escola(db, user.id, coord_escola_id)
    elif user.role == UserRole.ALUNO:
        _set_aluno_turma(db, user.id, aluno_turma_id, aluno_ano)

    return RedirectResponse(url="/admin/usuarios", status_code=303)


@router.post("/usuarios/{id}/editar")
async def usuarios_atualizar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    form = await request.form()
    nome = form.get("nome")
    email = form.get("email")
    senha = form.get("senha") or None
    role = form.get("role") or "aluno"
    ativo_raw = form.get("ativo")
    aluno_turma_id = form.get("aluno_turma_id")
    aluno_ano = form.get("aluno_ano")
    professor_turmas_raw = form.getlist("professor_turmas")
    gestor_escolas_raw = form.getlist("gestor_escolas")
    coordenador_escola_raw = form.get("coordenador_escola")
    permite_cadastro_trilha_geral = (form.get("permite_cadastro_trilha_geral") or "").lower() == "true"
    try:
        role_enum = UserRole(role)
    except ValueError:
        role_enum = UserRole.ALUNO

    user = UserRepository().update(
        db,
        id,
        nome=nome,
        email=email,
        senha=senha,
        role=role_enum,
        ativo=(ativo_raw or "").lower() == "true",
        permite_cadastro_trilha_geral=(permite_cadastro_trilha_geral if role_enum == UserRole.PROFESSOR else False),
    )
    if not user:
        return RedirectResponse(url="/admin/usuarios", status_code=302)

    if role_enum == UserRole.PROFESSOR:
        user.moodle_user_id = (form.get("moodle_user_id") or "").strip() or None
        db.commit()

    prof_turma_ids = _parse_int_list(professor_turmas_raw)
    gestor_escola_ids = _parse_int_list(gestor_escolas_raw)
    coord_escola_id: Optional[int] = None
    if coordenador_escola_raw is not None and str(coordenador_escola_raw).strip():
        coord_escola_id = int(str(coordenador_escola_raw).strip())

    if user.role == UserRole.PROFESSOR:
        _set_professor_turmas(db, user.id, prof_turma_ids)
        _set_gestor_escolas(db, user.id, [])
        _set_coordenador_escola(db, user.id, None)
    elif user.role == UserRole.GESTOR:
        _set_gestor_escolas(db, user.id, gestor_escola_ids)
        _set_professor_turmas(db, user.id, [])
        _set_coordenador_escola(db, user.id, None)
    elif user.role == UserRole.COORDENADOR:
        _set_coordenador_escola(db, user.id, coord_escola_id)
        _set_professor_turmas(db, user.id, [])
        _set_gestor_escolas(db, user.id, [])
    elif user.role == UserRole.ALUNO:
        _set_aluno_turma(db, user.id, aluno_turma_id, aluno_ano)

    return RedirectResponse(url="/admin/usuarios", status_code=303)


@router.post("/usuarios/{id}/toggle-trilha-geral")
def usuarios_toggle_trilha_geral(
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    user = UserRepository().get_by_id(db, id)
    if not user or user.role != UserRole.PROFESSOR:
        return RedirectResponse(url="/admin/usuarios", status_code=302)
    novo_valor = not bool(getattr(user, "permite_cadastro_trilha_geral", False))
    UserRepository().update(db, id, permite_cadastro_trilha_geral=novo_valor)
    return RedirectResponse(url="/admin/usuarios", status_code=303)


@router.post("/usuarios/{id}/deletar")
def usuarios_deletar(
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    # Evita autoexclusão da sessão admin atual.
    if current_user and current_user.id == id:
        return RedirectResponse(url="/admin/usuarios?erro=auto_delete", status_code=303)

    user = UserRepository().get_by_id(db, id)
    if not user:
        return RedirectResponse(url="/admin/usuarios", status_code=302)

    try:
        from app.models.h5p import ProgressoH5P
        from app.models.aluno import PontuacaoGamificacao
        from app.models.relacoes import ProfessorTurma, GestorEscola, CoordenadorEscola

        db.query(ProfessorTurma).filter(ProfessorTurma.professor_id == id).delete()
        db.query(GestorEscola).filter(GestorEscola.gestor_id == id).delete()
        db.query(CoordenadorEscola).filter(CoordenadorEscola.coordenador_id == id).delete()
        aluno = db.query(Aluno).filter(Aluno.usuario_id == id).first()
        if aluno:
            db.query(ProgressoH5P).filter(ProgressoH5P.aluno_id == aluno.id).delete()
            db.query(PontuacaoGamificacao).filter(PontuacaoGamificacao.aluno_id == aluno.id).delete()
            db.delete(aluno)
        db.commit()

        if not UserRepository().delete(db, id):
            return RedirectResponse(url="/admin/usuarios", status_code=302)
    except IntegrityError:
        db.rollback()
        return RedirectResponse(url="/admin/usuarios?erro=vinculos", status_code=303)

    return RedirectResponse(url="/admin/usuarios?ok=deletado", status_code=303)


# --- Atividades H5P ---
@router.get("/atividades-h5p")
def atividades_h5p_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    trilha_id: Optional[int] = None,
):
    atividades = AtividadeH5PRepository().listar(db, trilha_id=trilha_id, ativo_only=False)
    trilhas = TrilhaRepository().listar(db)
    trilha_nomes = {t.id: t.nome for t in trilhas}
    return templates.TemplateResponse(
        request,
        "admin/atividades_h5p_list.html",
        {"request": request, "atividades": atividades, "trilhas": trilhas, "trilha_nomes": trilha_nomes},
    )


@router.get("/atividades-h5p/nova")
def atividades_h5p_nova(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    trilhas = TrilhaRepository().listar(db)
    descritores = DescritorRepository().listar(db)
    return templates.TemplateResponse(
        request,
        "admin/atividade_h5p_form.html",
        {"request": request, "atividade": None, "trilhas": trilhas, "descritores": descritores},
    )


@router.get("/atividades-h5p/{id}/editar")
def atividades_h5p_editar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    atividade = AtividadeH5PRepository().get(db, id)
    if not atividade:
        return RedirectResponse(url="/admin/atividades-h5p", status_code=302)
    trilhas = TrilhaRepository().listar(db)
    descritores = DescritorRepository().listar(db)
    return templates.TemplateResponse(
        request,
        "admin/atividade_h5p_form.html",
        {"request": request, "atividade": atividade, "trilhas": trilhas, "descritores": descritores},
    )


@router.post("/atividades-h5p/validar-upload")
async def atividades_h5p_validar_upload(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    arquivo_h5p: UploadFile | None = File(None),
):
    ok, msg = _validate_h5p_archive_file(arquivo_h5p)
    return JSONResponse({"ok": ok, "message": msg})


@router.post("/atividades-h5p/nova")
def atividades_h5p_criar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    titulo: str = Form(...),
    tipo: str = Form("quiz"),
    path_ou_json: str = Form(""),
    arquivo_h5p: UploadFile | None = File(None),
    trilha_id: Optional[str] = Form(None),
    descritor_id: Optional[str] = Form(None),
    ordem: int = Form(0),
    ativo: Optional[str] = Form(None),
):
    from app.schemas.h5p_schema import AtividadeH5PCreate
    tri_id = int(trilha_id) if trilha_id and str(trilha_id).strip() else None
    desc_id = int(descritor_id) if descritor_id and str(descritor_id).strip() else None
    conteudo_path = path_ou_json.strip() if path_ou_json else ""
    if arquivo_h5p and arquivo_h5p.filename:
        conteudo_path = _save_h5p_upload(db, arquivo_h5p, titulo=titulo, trilha_id=tri_id)
    if not conteudo_path:
        raise HTTPException(
            status_code=400,
            detail="Informe um caminho de conteúdo ou envie um arquivo .h5p",
        )
    data = AtividadeH5PCreate(
        titulo=titulo,
        tipo=tipo,
        path_ou_json=conteudo_path,
        trilha_id=tri_id,
        descritor_id=desc_id,
        ordem=ordem,
        ativo=(ativo or "").lower() == "true",
    )
    AtividadeH5PRepository().create(db, data)
    return RedirectResponse(url="/admin/atividades-h5p", status_code=303)


@router.post("/atividades-h5p/{id}/editar")
def atividades_h5p_atualizar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    titulo: str = Form(...),
    tipo: str = Form("quiz"),
    path_ou_json: str = Form(""),
    arquivo_h5p: UploadFile | None = File(None),
    trilha_id: Optional[str] = Form(None),
    descritor_id: Optional[str] = Form(None),
    ordem: int = Form(0),
    ativo: Optional[str] = Form(None),
):
    from app.schemas.h5p_schema import AtividadeH5PUpdate
    tri_id = int(trilha_id) if trilha_id and str(trilha_id).strip() else None
    desc_id = int(descritor_id) if descritor_id and str(descritor_id).strip() else None
    atual = AtividadeH5PRepository().get(db, id)
    if not atual:
        return RedirectResponse(url="/admin/atividades-h5p", status_code=302)

    conteudo_path = path_ou_json.strip() if path_ou_json else (atual.path_ou_json or "")
    if arquivo_h5p and arquivo_h5p.filename:
        conteudo_path = _save_h5p_upload(db, arquivo_h5p, titulo=titulo, trilha_id=tri_id)

    data = AtividadeH5PUpdate(
        titulo=titulo,
        tipo=tipo,
        path_ou_json=conteudo_path,
        trilha_id=tri_id,
        descritor_id=desc_id,
        ordem=ordem,
        ativo=(ativo or "").lower() == "true",
    )
    if not AtividadeH5PRepository().update(db, id, data):
        return RedirectResponse(url="/admin/atividades-h5p", status_code=302)
    return RedirectResponse(url="/admin/atividades-h5p", status_code=303)


@router.post("/atividades-h5p/{id}/deletar")
def atividades_h5p_deletar(
    request: Request,
    id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    if not _remove_atividade_h5p_com_arquivos(db, id):
        return RedirectResponse(url="/admin/atividades-h5p", status_code=302)
    return RedirectResponse(url="/admin/atividades-h5p?ok=deletado", status_code=303)


@router.get("/suporte")
def admin_suporte_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    from app.models.support_ticket import SupportTicket

    tickets = db.query(SupportTicket).order_by(SupportTicket.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "admin/suporte_list.html",
        {"request": request, "tickets": tickets},
    )


@router.get("/suporte/{ticket_id}")
def admin_suporte_ticket(
    request: Request,
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    from app.models.support_ticket import SupportTicket, SupportTicketMessage

    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        return RedirectResponse(url="/admin/suporte", status_code=302)
    mensagens = (
        db.query(SupportTicketMessage)
        .filter(SupportTicketMessage.ticket_id == ticket_id)
        .order_by(SupportTicketMessage.created_at.asc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "admin/suporte_ticket.html",
        {"request": request, "ticket": ticket, "mensagens": mensagens},
    )


@router.post("/suporte/{ticket_id}/responder")
async def admin_suporte_responder(
    request: Request,
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
    corpo: str = Form(...),
):
    from datetime import datetime

    from app.models.support_ticket import SupportTicket, SupportTicketMessage

    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        return RedirectResponse(url="/admin/suporte", status_code=302)
    texto = (corpo or "").strip()
    if texto:
        db.add(
            SupportTicketMessage(
                ticket_id=ticket_id,
                autor_role="admin",
                corpo=texto[:8000],
                created_at=datetime.utcnow(),
            )
        )
        if ticket.status == "aberto":
            ticket.status = "em_andamento"
        ticket.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse(url=f"/admin/suporte/{ticket_id}", status_code=303)


@router.post("/suporte/{ticket_id}/resolver")
def admin_suporte_resolver(
    request: Request,
    ticket_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_admin_redirect),
):
    from datetime import datetime

    from app.models.support_ticket import SupportTicket

    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if ticket:
        ticket.status = "resolvido"
        ticket.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse(url=f"/admin/suporte/{ticket_id}", status_code=303)
