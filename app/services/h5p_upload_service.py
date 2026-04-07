from pathlib import Path
from typing import Optional
import re
import shutil
import uuid
import zipfile

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.repositories.gestao_repository import TrilhaRepository, TurmaRepository


def _slugify(value: str, default: str = "atividade") -> str:
    raw = (value or "").strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return raw or default


def _get_materia_ano_from_trilha(db: Session, trilha_id: Optional[int]) -> tuple[str, str]:
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


def _get_materia_ano_from_turma(db: Session, turma_id: Optional[int]) -> tuple[str, str]:
    materia = "geral"
    ano = "ano-geral"
    if not turma_id:
        return materia, ano
    turma = TurmaRepository().get(db, turma_id)
    if not turma:
        return materia, ano
    if turma.ano_escolar:
        ano = f"ano-{int(turma.ano_escolar)}"
    return materia, ano


def save_h5p_upload(
    db: Session,
    arquivo_h5p: UploadFile,
    titulo: str,
    *,
    trilha_id: Optional[int] = None,
    turma_id: Optional[int] = None,
) -> str:
    if not arquivo_h5p or not arquivo_h5p.filename:
        raise HTTPException(status_code=400, detail="Arquivo .h5p é obrigatório")
    if not arquivo_h5p.filename.lower().endswith(".h5p"):
        raise HTTPException(status_code=400, detail="Apenas arquivos .h5p são aceitos")

    if trilha_id:
        materia, ano = _get_materia_ano_from_trilha(db, trilha_id)
    else:
        materia, ano = _get_materia_ano_from_turma(db, turma_id)

    base_dir = Path(settings.H5P_CONTENT_DIR).resolve()
    target_dir = base_dir / materia / ano / f"{_slugify(titulo)}-{uuid.uuid4().hex[:8]}"
    target_dir.mkdir(parents=True, exist_ok=True)
    pacote_path = target_dir / "upload.h5p"
    with pacote_path.open("wb") as out:
        shutil.copyfileobj(arquivo_h5p.file, out)
    try:
        with zipfile.ZipFile(pacote_path, "r") as zf:
            zf.extractall(target_dir)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Arquivo .h5p inválido/corrompido") from exc
    finally:
        if pacote_path.exists():
            pacote_path.unlink()

    if not (target_dir / "h5p.json").is_file() or not (target_dir / "content" / "content.json").is_file():
        raise HTTPException(
            status_code=400,
            detail="Pacote H5P inválido: h5p.json ou content/content.json não encontrado",
        )

    return target_dir.relative_to(base_dir).as_posix()
