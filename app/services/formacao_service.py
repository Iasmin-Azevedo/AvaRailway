from __future__ import annotations

import io
from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from app.models.formacao import (
    EncontroPresencialFormacaoBNCC,
    ParticipanteTurmaFormacaoBNCC,
    PapelParticipanteFormacao,
    ProgramaFormacaoBNCC,
    ProgramaFormacaoRecurso,
    StatusParticipacaoFormacao,
    TipoRecursoFormacao,
    TurmaFormacaoBNCC,
)
from app.models.user import Usuario


class FormacaoService:
    def criar_programa(
        self,
        db: Session,
        *,
        nome: str,
        descricao: str | None,
        publico_alvo: str | None,
    ) -> ProgramaFormacaoBNCC:
        obj = ProgramaFormacaoBNCC(
            nome=nome,
            descricao=descricao,
            publico_alvo=publico_alvo,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def vincular_recurso(
        self,
        db: Session,
        *,
        programa_id: int,
        tipo_recurso: TipoRecursoFormacao,
        titulo: str,
        trilha_id: int | None = None,
        moodle_course_id: int | None = None,
        descricao: str | None = None,
    ) -> ProgramaFormacaoRecurso:
        obj = ProgramaFormacaoRecurso(
            programa_id=programa_id,
            tipo_recurso=tipo_recurso,
            titulo=titulo,
            trilha_id=trilha_id,
            moodle_course_id=moodle_course_id,
            descricao=descricao,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def criar_turma(
        self,
        db: Session,
        *,
        programa_id: int,
        nome: str,
        escola_id: int | None = None,
        limite_participantes: int = 30,
    ) -> TurmaFormacaoBNCC:
        obj = TurmaFormacaoBNCC(
            programa_id=programa_id,
            nome=nome,
            escola_id=escola_id,
            limite_participantes=limite_participantes or 30,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def inscrever_participante(
        self,
        db: Session,
        *,
        turma_id: int,
        usuario_id: int,
        papel_participante: PapelParticipanteFormacao,
    ) -> ParticipanteTurmaFormacaoBNCC:
        existente = (
            db.query(ParticipanteTurmaFormacaoBNCC)
            .filter(
                ParticipanteTurmaFormacaoBNCC.turma_id == turma_id,
                ParticipanteTurmaFormacaoBNCC.usuario_id == usuario_id,
            )
            .first()
        )
        if existente:
            return existente
        obj = ParticipanteTurmaFormacaoBNCC(
            turma_id=turma_id,
            usuario_id=usuario_id,
            papel_participante=papel_participante,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def atualizar_progresso_participante(
        self,
        db: Session,
        *,
        participante_id: int,
        carga_horaria_remota_realizada: float,
        carga_horaria_presencial_realizada: float,
        devolutiva: str | None = None,
    ) -> ParticipanteTurmaFormacaoBNCC | None:
        item = db.query(ParticipanteTurmaFormacaoBNCC).filter(
            ParticipanteTurmaFormacaoBNCC.id == participante_id
        ).first()
        if not item:
            return None
        item.carga_horaria_remota_realizada = max(0.0, float(carga_horaria_remota_realizada or 0.0))
        item.carga_horaria_presencial_realizada = max(0.0, float(carga_horaria_presencial_realizada or 0.0))
        item.devolutiva = (devolutiva or "").strip() or None
        total_realizado = item.carga_horaria_remota_realizada + item.carga_horaria_presencial_realizada
        meta = float((item.turma.programa.carga_horaria_total if item.turma and item.turma.programa else 80) or 80)
        item.status = (
            StatusParticipacaoFormacao.CONCLUIDO
            if total_realizado >= meta
            else StatusParticipacaoFormacao.EM_ANDAMENTO
        )
        item.certificado_emitido = item.status == StatusParticipacaoFormacao.CONCLUIDO
        db.commit()
        db.refresh(item)
        return item

    def resumo_programas(self, db: Session) -> dict:
        programas = db.query(ProgramaFormacaoBNCC).filter(ProgramaFormacaoBNCC.ativo.is_(True)).all()
        participantes = db.query(ParticipanteTurmaFormacaoBNCC).all()
        concluidos = [
            p
            for p in participantes
            if str(getattr(p.status, "value", p.status)) == StatusParticipacaoFormacao.CONCLUIDO.value
        ]
        return {
            "programas_ativos": len(programas),
            "turmas_ativas": sum(len(p.turmas) for p in programas),
            "participantes": len(participantes),
            "concluidos": len(concluidos),
        }

    def listagem_programas(self, db: Session) -> list[dict]:
        out: list[dict] = []
        for programa in (
            db.query(ProgramaFormacaoBNCC)
            .filter(ProgramaFormacaoBNCC.ativo.is_(True))
            .order_by(ProgramaFormacaoBNCC.nome.asc())
            .all()
        ):
            out.append(
                {
                    "id": programa.id,
                    "nome": programa.nome,
                    "publico_alvo": programa.publico_alvo or "",
                    "carga_horaria_total": programa.carga_horaria_total,
                    "carga_horaria_presencial": programa.carga_horaria_presencial,
                    "carga_horaria_remota": programa.carga_horaria_remota,
                    "n_turmas": len(programa.turmas),
                    "n_recursos": len(programa.recursos),
                }
            )
        return out

    def criar_encontro_presencial(
        self,
        db: Session,
        *,
        turma_id: int,
        titulo: str,
        data_encontro: datetime,
        carga_horaria: float = 4.0,
        local: str | None = None,
    ) -> EncontroPresencialFormacaoBNCC:
        obj = EncontroPresencialFormacaoBNCC(
            turma_id=turma_id,
            titulo=titulo,
            data_encontro=data_encontro,
            carga_horaria=carga_horaria,
            local=(local or "").strip() or None,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def gerar_certificado_pdf(self, db: Session, *, participante_id: int) -> tuple[bytes, str]:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas

        participante = (
            db.query(ParticipanteTurmaFormacaoBNCC)
            .options(
                joinedload(ParticipanteTurmaFormacaoBNCC.turma).joinedload(TurmaFormacaoBNCC.programa),
            )
            .filter(ParticipanteTurmaFormacaoBNCC.id == participante_id)
            .first()
        )
        if not participante:
            raise ValueError("Participante não encontrado.")
        usuario = db.query(Usuario).filter(Usuario.id == participante.usuario_id).first()
        nome = (usuario.nome if usuario else None) or "Participante"
        programa = participante.turma.programa if participante.turma else None
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        w, h = A4
        c.setFont("Helvetica-Bold", 22)
        c.drawCentredString(w / 2, h - 50 * mm, "Certificado de Conclusão")
        c.setFont("Helvetica", 14)
        c.drawCentredString(w / 2, h - 70 * mm, f"Certificamos que {nome}")
        c.drawCentredString(
            w / 2,
            h - 80 * mm,
            f"concluiu o programa {(programa.nome if programa else 'BNCC Computação')}",
        )
        c.setFont("Helvetica", 11)
        c.drawCentredString(w / 2, h - 95 * mm, f"Turma: {participante.turma.nome if participante.turma else '—'}")
        c.drawCentredString(w / 2, h - 102 * mm, f"Emitido em {datetime.utcnow().strftime('%d/%m/%Y')}")
        c.showPage()
        c.save()
        buf.seek(0)
        participante.certificado_emitido = True
        db.commit()
        safe = "".join(ch if ch.isalnum() else "_" for ch in nome)[:30]
        return buf.read(), f"certificado_{safe}.pdf"
