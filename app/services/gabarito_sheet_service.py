"""Geração de folhas de resposta em PDF com QR, grade tabular e marcas de registro."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
from types import SimpleNamespace
import zipfile

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session, joinedload

from app.models.aluno import Aluno
from app.models.avaliacao import AplicacaoProva, Avaliacao, ParticipacaoAplicacaoProva, Questao
from app.models.user import Usuario
from app.core.config import settings
from app.services.gabarito_layout import (
    BUBBLE_R,
    CORNER_CROSS,
    GRID_CELL_W,
    GRID_HEADER_H,
    GRID_NUM_COL_W,
    GRID_ROW_H,
    HEADER_H,
    LETTERS,
    MARGIN,
    PAGE_H,
    PAGE_W,
    QR_SIZE,
    SHEET_GAP,
    SYNC_COL_W,
    cell_center_pdf,
    compute_sheet_dimensions,
    corner_crosses_pdf,
    sync_dot_pdf,
)


class GabaritoSheetService:
    def gerar_pdf_participacao(
        self,
        db: Session,
        *,
        participacao_id: int,
    ) -> tuple[bytes, str]:
        participacao = self._load_participacao(db, participacao_id)
        participacao._nome_aluno_cache = self._nome_aluno(db, participacao.aluno_id)
        questoes = self._questoes(db, participacao.aplicacao.avaliacao_id)
        dims = compute_sheet_dimensions(len(questoes))
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(dims["sheet_w"], dims["sheet_h"]))
        self._draw_folha(
            c,
            participacao=participacao,
            questoes=questoes,
            dims=dims,
            sheet_top=dims["sheet_h"] - MARGIN,
        )
        c.save()
        buf.seek(0)
        nome = self._nome_aluno(db, participacao.aluno_id)
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in nome)[:40]
        return buf.read(), f"folha_{safe}_p{participacao.id}.pdf"

    def gerar_pdf_aplicacao_completo(
        self,
        db: Session,
        *,
        aplicacao_id: int,
    ) -> tuple[bytes, str]:
        participacoes = (
            db.query(ParticipacaoAplicacaoProva)
            .filter(ParticipacaoAplicacaoProva.aplicacao_id == aplicacao_id)
            .order_by(ParticipacaoAplicacaoProva.id.asc())
            .all()
        )
        if not participacoes:
            raise ValueError("Nenhuma participação nesta aplicação.")
        aplic = db.query(AplicacaoProva).filter(AplicacaoProva.id == aplicacao_id).first()
        if not aplic:
            raise ValueError("Aplicação não encontrada.")
        questoes = self._questoes(db, aplic.avaliacao_id)
        dims = compute_sheet_dimensions(len(questoes))
        sheet_h = dims["sheet_h"]

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        y_top = PAGE_H - MARGIN

        for i, participacao in enumerate(participacoes):
            if y_top - sheet_h < MARGIN:
                c.showPage()
                y_top = PAGE_H - MARGIN

            participacao = self._load_participacao(db, participacao.id)
            participacao._nome_aluno_cache = self._nome_aluno(db, participacao.aluno_id)
            self._draw_folha(
                c,
                participacao=participacao,
                questoes=questoes,
                dims=dims,
                sheet_top=y_top,
            )
            y_top -= sheet_h + SHEET_GAP

        c.save()
        buf.seek(0)
        return buf.read(), f"folhas_aplicacao_{aplicacao_id}.pdf"

    def gerar_zip_aplicacao(self, db: Session, *, aplicacao_id: int) -> tuple[bytes, str]:
        participacoes = (
            db.query(ParticipacaoAplicacaoProva)
            .filter(ParticipacaoAplicacaoProva.aplicacao_id == aplicacao_id)
            .order_by(ParticipacaoAplicacaoProva.id.asc())
            .all()
        )
        if not participacoes:
            raise ValueError("Nenhuma participação nesta aplicação.")
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in participacoes:
                pdf_bytes, filename = self.gerar_pdf_participacao(db, participacao_id=p.id)
                zf.writestr(filename, pdf_bytes)
        zip_buf.seek(0)
        return zip_buf.read(), f"folhas_aplicacao_{aplicacao_id}.zip"

    def gerar_pdf_avaliacao_trilha_completo(
        self,
        db: Session,
        *,
        avaliacao_id: int,
        elegiveis: list[dict],
    ) -> tuple[bytes, str]:
        avaliacao = db.query(Avaliacao).filter(Avaliacao.id == avaliacao_id).first()
        if not avaliacao:
            raise ValueError("Prova não encontrada.")
        if not elegiveis:
            raise ValueError("Nenhum aluno elegível para o ano escolar da trilha.")
        questoes = self._questoes(db, avaliacao_id)
        dims = compute_sheet_dimensions(len(questoes))
        sheet_h = dims["sheet_h"]
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        y_top = PAGE_H - MARGIN
        fake_aplicacao = SimpleNamespace(id=0, titulo="Modo trilha", avaliacao=avaliacao)

        for item in elegiveis:
            if y_top - sheet_h < MARGIN:
                c.showPage()
                y_top = PAGE_H - MARGIN
            fake_participacao = SimpleNamespace(
                id=0,
                aluno_id=item["aluno_id"],
                aplicacao=fake_aplicacao,
                _nome_aluno_cache=item.get("aluno_nome") or f"Aluno #{item['aluno_id']}",
                _participacao_label=f"Aluno #{item['aluno_id']}",
                _qr_payload_cache=self._build_trilha_payload(
                    avaliacao_id=avaliacao_id,
                    aluno_id=int(item["aluno_id"]),
                ),
            )
            self._draw_folha(
                c,
                participacao=fake_participacao,
                questoes=questoes,
                dims=dims,
                sheet_top=y_top,
            )
            y_top -= sheet_h + SHEET_GAP

        c.save()
        buf.seek(0)
        return buf.read(), f"folhas_trilha_avaliacao_{avaliacao_id}.pdf"

    def gerar_zip_avaliacao_trilha(
        self,
        db: Session,
        *,
        avaliacao_id: int,
        elegiveis: list[dict],
    ) -> tuple[bytes, str]:
        if not elegiveis:
            raise ValueError("Nenhum aluno elegível para o ano escolar da trilha.")
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in elegiveis:
                pdf_bytes, _ = self.gerar_pdf_avaliacao_trilha_completo(
                    db,
                    avaliacao_id=avaliacao_id,
                    elegiveis=[item],
                )
                nome = "".join(
                    ch if ch.isalnum() or ch in "-_" else "_"
                    for ch in (item.get("aluno_nome") or f"aluno_{item['aluno_id']}")
                )[:40]
                zf.writestr(f"folha_{nome}_a{item['aluno_id']}.pdf", pdf_bytes)
        zip_buf.seek(0)
        return zip_buf.read(), f"folhas_trilha_avaliacao_{avaliacao_id}.zip"

    def _load_participacao(self, db: Session, participacao_id: int) -> ParticipacaoAplicacaoProva:
        participacao = (
            db.query(ParticipacaoAplicacaoProva)
            .options(
                joinedload(ParticipacaoAplicacaoProva.aplicacao).joinedload(AplicacaoProva.avaliacao),
            )
            .filter(ParticipacaoAplicacaoProva.id == participacao_id)
            .first()
        )
        if not participacao or not participacao.aplicacao:
            raise ValueError("Participação não encontrada.")
        return participacao

    def _questoes(self, db: Session, avaliacao_id: int) -> list:
        questoes = (
            db.query(Questao)
            .filter(Questao.avaliacao_id == avaliacao_id)
            .order_by(Questao.numero.asc(), Questao.id.asc())
            .all()
        )
        if not questoes:
            raise ValueError("A prova não possui questões.")
        return questoes

    def _nome_aluno(self, db: Session, aluno_id: int) -> str:
        aluno = db.query(Aluno).filter(Aluno.id == aluno_id).first()
        if not aluno:
            return "Aluno"
        usuario = db.query(Usuario).filter(Usuario.id == aluno.usuario_id).first()
        return (usuario.nome if usuario else None) or f"Aluno #{aluno.id}"

    def _draw_folha(
        self,
        c: canvas.Canvas,
        *,
        participacao: ParticipacaoAplicacaoProva,
        questoes: list,
        dims: dict,
        sheet_top: float,
    ) -> None:
        width = dims["sheet_w"]
        grid_info = dims["grid"]
        table_w = grid_info["table_w"]
        table_h = grid_info["table_h"]
        per_col = grid_info["per_col"]

        aplicacao = participacao.aplicacao
        avaliacao = aplicacao.avaliacao
        nome_aluno = getattr(participacao, "_nome_aluno_cache", None) or "Aluno"
        payload = getattr(participacao, "_qr_payload_cache", None) or json.dumps(
            {"p": participacao.id, "a": aplicacao.id}, separators=(",", ":")
        )
        qr_img = self._qr_image(payload)

        y_top = sheet_top
        c.drawImage(qr_img, width - MARGIN - QR_SIZE, y_top - QR_SIZE, QR_SIZE, QR_SIZE)

        c.setFont("Helvetica-Bold", 9)
        c.drawString(MARGIN, y_top - 4 * mm, (avaliacao.titulo if avaliacao else "Prova")[:60])
        c.setFont("Helvetica", 7)
        c.drawString(
            MARGIN,
            y_top - 8 * mm,
            f"Aluno: {nome_aluno[:40]}  ·  {getattr(participacao, '_participacao_label', f'Participação #{participacao.id}')}",
        )
        if aplicacao.titulo:
            c.drawString(MARGIN, y_top - 11 * mm, aplicacao.titulo[:48])
        c.setFont("Helvetica", 6.5)
        c.drawString(MARGIN, y_top - 14 * mm, "Preencha o círculo da alternativa (A–E).")

        grid_left = MARGIN
        grid_top = y_top - HEADER_H
        self._draw_omr_table(
            c,
            grid_left=grid_left,
            grid_top=grid_top,
            table_w=table_w,
            table_h=table_h,
            questoes=questoes,
            per_col=per_col,
        )

        sheet_bottom = sheet_top - dims["sheet_h"]
        c.setStrokeColorRGB(0.82, 0.82, 0.82)
        c.setLineWidth(0.25)
        c.line(MARGIN, sheet_bottom + 1, width - MARGIN, sheet_bottom + 1)
        c.setStrokeColorRGB(0, 0, 0)

    def _draw_corner_cross(self, c: canvas.Canvas, cx: float, cy: float) -> None:
        s = CORNER_CROSS
        c.setStrokeColorRGB(0, 0, 0)
        c.setLineWidth(0.6)
        c.line(cx - s, cy, cx + s, cy)
        c.line(cx, cy - s, cx, cy + s)

    def _draw_omr_table(
        self,
        c: canvas.Canvas,
        *,
        grid_left: float,
        grid_top: float,
        table_w: float,
        table_h: float,
        questoes: list,
        per_col: int,
    ) -> None:
        n = len(questoes)
        grid_bottom = grid_top - table_h

        for cx, cy in corner_crosses_pdf(grid_left, grid_top, table_w, table_h):
            self._draw_corner_cross(c, cx, cy)

        c.setLineWidth(0.45)
        c.setStrokeColorRGB(0, 0, 0)
        c.rect(grid_left, grid_bottom, table_w, table_h, fill=0, stroke=1)

        y_header = grid_top - GRID_HEADER_H
        c.line(grid_left, y_header, grid_left + table_w, y_header)
        x_sync = grid_left + SYNC_COL_W
        c.line(x_sync, grid_bottom, x_sync, grid_top)
        x_after_num = grid_left + SYNC_COL_W + GRID_NUM_COL_W
        c.line(x_after_num, grid_bottom, x_after_num, grid_top)
        for i in range(1, len(LETTERS)):
            x = x_after_num + i * GRID_CELL_W
            c.line(x, grid_bottom, x, grid_top)

        c.setFont("Helvetica-Bold", 6)
        c.drawCentredString(grid_left + SYNC_COL_W / 2, y_header + 1.8 * mm, "·")
        c.drawCentredString(x_after_num - GRID_NUM_COL_W / 2, y_header + 1.8 * mm, "Q")
        for i, letra in enumerate(LETTERS):
            cx = x_after_num + (i + 0.5) * GRID_CELL_W
            c.drawCentredString(cx, y_header + 1.8 * mm, letra)

        dot_r = 0.55 * mm
        for row in range(per_col):
            idx = row
            if idx >= n:
                break
            questao = questoes[idx]
            num = questao.numero if questao.numero is not None else (idx + 1)
            cy = grid_top - GRID_HEADER_H - (row + 0.5) * GRID_ROW_H
            y_row_top = grid_top - GRID_HEADER_H - row * GRID_ROW_H
            c.line(grid_left, y_row_top, grid_left + table_w, y_row_top)

            sx, sy = sync_dot_pdf(grid_left, grid_top, row)
            c.setFillColorRGB(0.35, 0.35, 0.35)
            c.circle(sx, sy, dot_r, fill=1, stroke=0)

            c.setFont("Helvetica-Bold", 7)
            c.drawCentredString(x_after_num - GRID_NUM_COL_W / 2, cy - 2.2, str(num))
            for i, letra in enumerate(LETTERS):
                cx, _ = cell_center_pdf(grid_left, grid_top, row, i)
                c.setFillColorRGB(1, 1, 1)
                c.circle(cx, cy, BUBBLE_R, stroke=1, fill=1)
                c.setFont("Helvetica", 6)
                c.setFillColorRGB(0, 0, 0)
                c.drawCentredString(cx, cy - 2.0, letra)

    def _qr_image(self, payload: str):
        import qrcode
        from reportlab.lib.utils import ImageReader

        qr = qrcode.QRCode(version=2, box_size=4, border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return ImageReader(buf)

    def _build_trilha_payload(self, *, avaliacao_id: int, aluno_id: int) -> str:
        sig = self._trilha_signature(avaliacao_id=avaliacao_id, aluno_id=aluno_id)
        return json.dumps(
            {"m": "trilha", "av": int(avaliacao_id), "al": int(aluno_id), "sig": sig},
            separators=(",", ":"),
        )

    @staticmethod
    def _trilha_signature(*, avaliacao_id: int, aluno_id: int) -> str:
        secret = (settings.SECRET_KEY or "mj-connect-default-secret").encode("utf-8")
        msg = f"trilha:{int(avaliacao_id)}:{int(aluno_id)}".encode("utf-8")
        return hmac.new(secret, msg, hashlib.sha256).hexdigest()[:16]
