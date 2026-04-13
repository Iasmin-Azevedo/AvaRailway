"""URLs públicas para conteúdo H5P e uploads (fora de /static quando necessário)."""

from pathlib import Path

from app.core.config import settings

# Diretório do pacote `app` (igual a Path(app.main.__file__).resolve().parent).
_APP_DIR = Path(__file__).resolve().parent.parent


def h5p_content_root() -> Path:
    """Diretório absoluto onde os pacotes H5P extraídos são armazenados (mesma regra do mount /h5p)."""
    p = Path(settings.H5P_CONTENT_DIR)
    if not p.is_absolute():
        p = _APP_DIR / p
    return p.resolve()


def user_upload_root() -> Path:
    """Diretório de uploads de usuário (mount /media)."""
    p = Path(settings.USER_UPLOAD_DIR)
    if not p.is_absolute():
        p = _APP_DIR / p
    return p.resolve()


def h5p_public_url(rel_path: str) -> str:
    rel = (rel_path or "").strip().replace("\\", "/").strip("/")
    if not rel:
        return ""
    prefix = (settings.H5P_URL_PREFIX or "/h5p").rstrip("/")
    return f"{prefix}/{rel}"
