from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.user import AuditLog


class AuditService:
    @staticmethod
    def log(
        db: Session,
        *,
        usuario_id: int | None,
        acao: str,
        detalhes: str,
        categoria: str | None = None,
        entidade: str | None = None,
        entidade_id: int | None = None,
        ip: str | None = None,
    ) -> AuditLog:
        item = AuditLog(
            usuario_id=usuario_id,
            acao=acao[:50],
            categoria=(categoria or "").strip()[:50] or None,
            entidade=(entidade or "").strip()[:80] or None,
            entidade_id=entidade_id,
            detalhes=detalhes[:4000],
            ip=ip,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item
