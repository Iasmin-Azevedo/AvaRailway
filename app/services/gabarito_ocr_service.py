"""Leitura OMR: QR + grade tabular com cantoneiras e coluna de sincronismo."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
from typing import Any

from PIL import Image, ImageOps

from reportlab.lib.units import mm

from app.core.config import settings
from app.services.gabarito_layout import (
    CORNER_CROSS,
    CORNER_OFFSET,
    GRID_CELL_W,
    GRID_HEADER_H,
    GRID_NUM_COL_W,
    GRID_ROW_H,
    HEADER_H,
    LETTERS,
    MARGIN,
    QR_SIZE,
    SYNC_COL_W,
    compute_sheet_layout,
)


class GabaritoOcrService:
    def processar_imagem(self, image_bytes: bytes, *, n_questoes: int) -> dict[str, Any]:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img)
        img = self._normalizar_tamanho(img)
        qr_info = self._decode_qr(img)
        participacao_id = qr_info.get("participacao_id")
        aplicacao_id = qr_info.get("aplicacao_id")
        aluno_id = qr_info.get("aluno_id")
        avaliacao_id = qr_info.get("avaliacao_id")
        modo = qr_info.get("mode")
        qr_rect = qr_info.get("qr_rect")
        gray = ImageOps.autocontrast(img.convert("L"))
        layout = compute_sheet_layout(n_questoes)
        respostas_grid = self._ler_grade_marcada(gray, layout=layout, n_questoes=n_questoes, qr_rect=qr_rect)
        # Modo robusto: sempre roda também o fallback legado para
        # aumentar recall em folhas reais (scanner/celular/PDF).
        respostas_leg = self._detect_bubbles_legacy(gray, n_questoes=n_questoes, qr_rect=qr_rect)
        respostas = self._merge_respostas(respostas_grid, respostas_leg, n_questoes=n_questoes)
        return {
            "participacao_id": participacao_id,
            "aplicacao_id": aplicacao_id,
            "aluno_id": aluno_id,
            "avaliacao_id": avaliacao_id,
            "mode": modo,
            "respostas": respostas,
            "erros": [],
        }

    @staticmethod
    def _normalizar_tamanho(img: Image.Image, *, max_dim: int = 2600) -> Image.Image:
        w, h = img.size
        maior = max(w, h)
        if maior <= max_dim:
            return img
        scale = max_dim / float(maior)
        nw = max(1, int(w * scale))
        nh = max(1, int(h * scale))
        return img.resize((nw, nh), Image.Resampling.LANCZOS)

    @staticmethod
    def _cobertura_respostas(respostas: list[dict[str, Any]] | None, *, n_questoes: int) -> float:
        if not respostas or n_questoes <= 0:
            return 0.0
        marcadas = sum(1 for r in respostas if (r.get("resposta_marcada") or "").strip().upper() in LETTERS)
        return marcadas / float(n_questoes)

    def processar_multiplas(
        self,
        files: list[tuple[str, bytes]],
        *,
        n_questoes: int,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for nome, data in files:
            try:
                row = self.processar_imagem(data, n_questoes=n_questoes)
                row["arquivo"] = nome
                row["ok"] = True
            except Exception as exc:
                row = {
                    "arquivo": nome,
                    "ok": False,
                    "erro": str(exc),
                    "participacao_id": None,
                    "aplicacao_id": None,
                    "respostas": [],
                }
            out.append(row)
        return out

    def _pyzbar_decode(self):
        try:
            from pyzbar.pyzbar import decode as pyzbar_decode

            return pyzbar_decode
        except ImportError as exc:
            if "zbar" in str(exc).lower() or "Unable to find zbar" in str(exc):
                raise ValueError(
                    "Leitor QR indisponível no servidor: instale libzbar0 "
                    "(reconstrua o container: docker compose build backend)."
                ) from exc
            raise ValueError("Biblioteca pyzbar não instalada.") from exc

    def _decode_qr(self, img: Image.Image) -> dict[str, Any]:
        pyzbar_decode = self._pyzbar_decode()
        candidates: list[tuple[Image.Image, tuple[int, int]]] = []
        base = img.convert("L")
        candidates.append((base, (0, 0)))
        candidates.append((ImageOps.autocontrast(base), (0, 0)))
        w, h = base.size
        for box in (
            (int(w * 0.45), 0, w, int(h * 0.4)),
            (int(w * 0.5), 0, w, int(h * 0.32)),
        ):
            crop = base.crop(box)
            candidates.append((crop, (box[0], box[1])))
            cw, ch = crop.size
            if cw > 0 and ch > 0:
                candidates.append(
                    (crop.resize((cw * 3, ch * 3), Image.Resampling.LANCZOS), (box[0], box[1]))
                )

        for source, offset in candidates:
            for angle in (0, 90, 180, 270):
                rotated = source if angle == 0 else source.rotate(angle, expand=True)
                for obj in pyzbar_decode(rotated):
                    try:
                        payload = json.loads(obj.data.decode("utf-8"))
                        rect = obj.rect
                        if offset != (0, 0):
                            rect = type(rect)(
                                rect.left + offset[0],
                                rect.top + offset[1],
                                rect.width,
                                rect.height,
                            )
                        pid = int(payload.get("p") or 0) or None
                        aid = int(payload.get("a") or 0) or None
                        if pid:
                            return {
                                "participacao_id": pid,
                                "aplicacao_id": aid,
                                "aluno_id": None,
                                "avaliacao_id": None,
                                "mode": "aplicacao",
                                "qr_rect": rect,
                            }
                        mode = (payload.get("m") or "").strip().lower()
                        if mode == "trilha":
                            aluno_id = int(payload.get("al") or 0) or None
                            avaliacao_id = int(payload.get("av") or 0) or None
                            sig = (payload.get("sig") or "").strip()
                            if aluno_id and avaliacao_id and self._validar_assinatura_trilha(
                                avaliacao_id=avaliacao_id,
                                aluno_id=aluno_id,
                                assinatura=sig,
                            ):
                                return {
                                    "participacao_id": None,
                                    "aplicacao_id": None,
                                    "aluno_id": aluno_id,
                                    "avaliacao_id": avaliacao_id,
                                    "mode": "trilha",
                                    "qr_rect": rect,
                                }
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
        raise ValueError("QR Code não encontrado. Use folha gerada pelo sistema (PDF) e foto nítida.")

    @staticmethod
    def _assinatura_trilha(*, avaliacao_id: int, aluno_id: int) -> str:
        secret = (settings.SECRET_KEY or "mj-connect-default-secret").encode("utf-8")
        msg = f"trilha:{int(avaliacao_id)}:{int(aluno_id)}".encode("utf-8")
        return hmac.new(secret, msg, hashlib.sha256).hexdigest()[:16]

    def _validar_assinatura_trilha(self, *, avaliacao_id: int, aluno_id: int, assinatura: str) -> bool:
        esperada = self._assinatura_trilha(avaliacao_id=avaliacao_id, aluno_id=aluno_id)
        return bool(assinatura) and hmac.compare_digest(assinatura, esperada)

    def _ler_grade_marcada(
        self,
        img: Image.Image,
        *,
        layout: dict,
        n_questoes: int,
        qr_rect: Any,
    ) -> list[dict[str, Any]] | None:
        if not qr_rect or not qr_rect.width:
            return None
        scale = qr_rect.width / QR_SIZE
        w, h = img.size
        y_search0 = int(qr_rect.top + qr_rect.height)
        y_search1 = int(min(h, y_search0 + (HEADER_H + layout["grid"]["table_h"] + 14 * mm) * scale))
        x_search0 = int(MARGIN * scale * 0.35)
        x_search1 = int(min(w, w * 0.75))

        corners = self._corners_from_qr_calibrated(img, qr_rect, scale, layout, n_questoes)
        if corners is None:
            corners = self._find_table_corners(img, x_search0, y_search0, x_search1, y_search1, scale, layout)
        if corners is None:
            return None

        tl, tr, bl, br = corners
        grid = layout["grid"]
        table_w = grid["table_w"]
        sync_rows = self._find_sync_row_ys(img, tl, bl, scale, n_questoes)

        r = max(4, int(2.3 * mm * scale * 1.15))
        respostas: list[dict[str, Any]] = []
        for row in range(n_questoes):
            if sync_rows and row < len(sync_rows):
                cy = sync_rows[row]
            else:
                v_norm = (GRID_HEADER_H + (row + 0.5) * GRID_ROW_H) / grid["table_h"]
                _, cy = self._bilinear_map(tl, tr, bl, br, 0.5, v_norm)

            scores: list[tuple[str, float]] = []
            for alt_i, letra in enumerate(LETTERS):
                u_norm = (SYNC_COL_W + GRID_NUM_COL_W + (alt_i + 0.5) * GRID_CELL_W) / table_w
                left_x = self._interp_edge_y(tl, bl, cy)
                right_x = self._interp_edge_y(tr, br, cy)
                cx = left_x * (1 - u_norm) + right_x * u_norm
                fill = self._fill_score(img, int(cx), int(cy), r)
                dark = self._darkness_ratio(img, int(cx), int(cy), r)
                score = fill if fill >= 0.3 else dark
                scores.append((letra, score))
            marcada = self._escolher_marcada(scores)
            respostas.append({"questao_numero": row + 1, "resposta_marcada": marcada})
        return respostas

    @staticmethod
    def _merge_respostas(
        primary: list[dict[str, Any]] | None,
        fallback: list[dict[str, Any]] | None,
        *,
        n_questoes: int,
    ) -> list[dict[str, Any]]:
        if not primary and not fallback:
            return [{"questao_numero": i + 1, "resposta_marcada": None} for i in range(n_questoes)]
        out: list[dict[str, Any]] = []
        for i in range(n_questoes):
            p = (primary or [{}])[i] if primary and i < len(primary) else {}
            f = (fallback or [{}])[i] if fallback and i < len(fallback) else {}
            marcada = p.get("resposta_marcada") or f.get("resposta_marcada")
            out.append(
                {
                    "questao_numero": p.get("questao_numero") or f.get("questao_numero") or (i + 1),
                    "resposta_marcada": marcada,
                }
            )
        return out

    @staticmethod
    def _escolher_marcada(scores: list[tuple[str, float]]) -> str | None:
        scores = sorted(scores, key=lambda t: t[1], reverse=True)
        if not scores:
            return None
        best, best_v = scores[0]
        second_v = scores[1][1] if len(scores) > 1 else 0
        sep = best_v - second_v
        # Empate técnico: evita enviesar para "A" quando todos os scores
        # ficam muito parecidos (folha clara/ruído).
        if abs(sep) < 0.006:
            return None
        # Calibração mais permissiva para folhas reais de celular/PDF,
        # evitando cenário de reconhecer apenas 1 questão.
        if best_v >= 0.14 and sep >= 0.03:
            return best
        if best_v >= 0.06 and sep >= 0.025:
            return best
        if best_v >= 0.04 and sep >= 0.018 and best_v >= second_v * 1.35:
            return best
        if best_v >= 0.032 and sep >= 0.014 and best_v >= second_v * 1.25:
            return best
        # Fallback de emergência: evita perder todas as questões
        # em folhas mais claras, mantendo separação mínima.
        if best_v >= 0.022 and sep >= 0.008:
            return best
        return None

    def _corners_from_qr_calibrated(
        self,
        img: Image.Image,
        qr_rect: Any,
        scale: float,
        layout: dict,
        n_questoes: int,
    ) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]] | None:
        grid = layout["grid"]
        table_w = grid["table_w"] * scale
        table_h = grid["table_h"] * scale
        grid_left = MARGIN * scale
        base_top = float(qr_rect.top + qr_rect.height)
        scan_step = max(1, int(scale * 0.8))
        y_min = int(base_top - 6 * mm * scale)
        y_max = int(base_top + 14 * mm * scale)
        span = max(1, y_max - y_min)
        scan_step = max(scan_step, int(span / 80))
        best_top = base_top + 4 * mm * scale
        best_metric = -1.0
        for gt in range(y_min, y_max, scan_step):
            tl = (grid_left, float(gt))
            tr = (grid_left + table_w, float(gt))
            bl = (grid_left, float(gt) + table_h)
            br = (grid_left + table_w, float(gt) + table_h)
            metric = self._metric_grid_corners(img, tl, tr, bl, br, layout, n_questoes, scale)
            if metric > best_metric:
                best_metric = metric
                best_top = float(gt)
        if best_metric < 0:
            return None
        tl = (grid_left, best_top)
        tr = (grid_left + table_w, best_top)
        bl = (grid_left, best_top + table_h)
        br = (grid_left + table_w, best_top + table_h)
        quad = (tl, tr, bl, br)
        if not self._validate_quad(quad, scale, layout):
            return None
        return quad

    def _metric_grid_corners(
        self,
        img: Image.Image,
        tl: tuple[float, float],
        tr: tuple[float, float],
        bl: tuple[float, float],
        br: tuple[float, float],
        layout: dict,
        n_questoes: int,
        scale: float,
    ) -> float:
        grid = layout["grid"]
        table_w = grid["table_w"]
        r = max(4, int(2.3 * mm * scale * 1.15))
        metric = 0.0
        for row in range(n_questoes):
            v_norm = (GRID_HEADER_H + (row + 0.5) * GRID_ROW_H) / grid["table_h"]
            _, cy = self._bilinear_map(tl, tr, bl, br, 0.5, v_norm)
            scores: list[float] = []
            for alt_i in range(len(LETTERS)):
                u_norm = (SYNC_COL_W + GRID_NUM_COL_W + (alt_i + 0.5) * GRID_CELL_W) / table_w
                left_x = self._interp_edge_y(tl, bl, cy)
                right_x = self._interp_edge_y(tr, br, cy)
                cx = left_x * (1 - u_norm) + right_x * u_norm
                fill = self._fill_score(img, int(cx), int(cy), r)
                dark = self._darkness_ratio(img, int(cx), int(cy), r)
                scores.append(fill if fill >= 0.3 else dark)
            scores.sort(reverse=True)
            if scores[0] < 0.04:
                continue
            metric += scores[0] + (scores[0] - scores[1]) * 4
        return metric

    @staticmethod
    def _order_corners_tl_tr_bl_br(
        points: list[tuple[float, float]],
    ) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]] | None:
        if len(points) < 4:
            return None
        if len(points) > 4:
            by_y = sorted(points, key=lambda p: p[1])
            half = max(2, len(by_y) // 5)
            top_pool = by_y[:half]
            bot_pool = by_y[-half:]
            top = sorted(top_pool, key=lambda p: p[0])
            bottom = sorted(bot_pool, key=lambda p: p[0])
            return top[0], top[-1], bottom[0], bottom[-1]
        pts = sorted(points, key=lambda p: p[1])
        top = sorted(pts[:2], key=lambda p: p[0])
        bottom = sorted(pts[2:], key=lambda p: p[0])
        return top[0], top[1], bottom[0], bottom[1]

    def _find_table_corners(
        self,
        img: Image.Image,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        scale: float,
        layout: dict | None = None,
    ) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]] | None:
        cross_pts = self._find_corner_crosses(img, x0, y0, x1, y1, scale)
        if cross_pts:
            ordered_cross = self._order_corners_tl_tr_bl_br(cross_pts)
            if ordered_cross:
                ctl, ctr, cbl, cbr = ordered_cross
                offset = CORNER_OFFSET * scale
                table_pts = [
                    (ctl[0] + offset, ctl[1] - offset),
                    (ctr[0] - offset, ctr[1] - offset),
                    (cbl[0] + offset, cbl[1] + offset),
                    (cbr[0] - offset, cbr[1] + offset),
                ]
                ordered = self._order_corners_tl_tr_bl_br(table_pts)
                if ordered and self._validate_quad(ordered, scale, layout):
                    return ordered

        rect_pts = self._find_rect_from_lines(img, x0, y0, x1, y1, scale)
        if rect_pts:
            ordered = self._order_corners_tl_tr_bl_br(rect_pts)
            if ordered and self._validate_quad(ordered, scale, layout):
                return ordered

        legacy = self._find_four_marks_legacy(img, x0, y0, x1, y1, scale)
        if legacy and self._validate_quad(legacy, scale, layout):
            return legacy
        return None

    def _find_corner_crosses(
        self,
        img: Image.Image,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        scale: float,
    ) -> list[tuple[float, float]] | None:
        arm = max(3, int(CORNER_CROSS * scale * 0.9))
        step = max(2, arm // 2)
        hits: list[tuple[float, float, float]] = []
        for y in range(y0, max(y0 + 1, y1 - arm * 2), step):
            for x in range(x0, max(x0 + 1, x1 - arm * 2), step):
                score = self._cross_score(img, x, y, arm)
                if score >= 0.42:
                    hits.append((x + arm, y + arm, score))
        if len(hits) < 4:
            return None
        hits.sort(key=lambda h: h[2], reverse=True)
        merged: list[tuple[float, float]] = []
        min_dist = arm * 2.5
        for hx, hy, _ in hits:
            if any(((hx - mx) ** 2 + (hy - my) ** 2) ** 0.5 < min_dist for mx, my in merged):
                continue
            merged.append((hx, hy))
            if len(merged) >= 4:
                break
        return merged if len(merged) == 4 else None

    def _cross_score(self, img: Image.Image, x: int, y: int, arm: int) -> float:
        w, h = img.size
        cx, cy = x + arm, y + arm
        horiz = vert = 0
        for dx in range(-arm, arm + 1):
            px, py = cx + dx, cy
            if 0 <= px < w and 0 <= py < h and img.getpixel((px, py)) < 100:
                horiz += 1
        for dy in range(-arm, arm + 1):
            px, py = cx, cy + dy
            if 0 <= px < w and 0 <= py < h and img.getpixel((px, py)) < 100:
                vert += 1
        denom = (arm * 2 + 1) * 2
        return (horiz + vert) / denom

    def _find_rect_from_lines(
        self,
        img: Image.Image,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        scale: float,
    ) -> list[tuple[float, float]] | None:
        top_y = None
        bot_y = None
        left_x = None
        right_x = None
        for y in range(y0, y1, max(2, int(scale))):
            dark = sum(1 for x in range(x0, x1, 3) if img.getpixel((x, y)) < 110)
            ratio = dark / max(1, (x1 - x0) // 3)
            if ratio > 0.35:
                if top_y is None:
                    top_y = y
                bot_y = y
        for x in range(x0, x1, max(2, int(scale))):
            dark = sum(1 for y in range(y0, y1, 3) if img.getpixel((x, y)) < 110)
            ratio = dark / max(1, (y1 - y0) // 3)
            if ratio > 0.28:
                if left_x is None:
                    left_x = x
                right_x = x
        if top_y is None or bot_y is None or left_x is None or right_x is None:
            return None
        return [
            (float(left_x), float(top_y)),
            (float(right_x), float(top_y)),
            (float(left_x), float(bot_y)),
            (float(right_x), float(bot_y)),
        ]

    def _find_four_marks_legacy(
        self,
        img: Image.Image,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        scale: float,
    ) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]] | None:
        mark_px = max(5, int(3.5 * mm * scale))
        step = max(2, mark_px // 3)
        blobs: list[tuple[float, float, float]] = []
        for y in range(y0, max(y0 + 1, y1 - mark_px), step):
            for x in range(x0, max(x0 + 1, x1 - mark_px), step):
                patch = img.crop((x, y, min(img.size[0], x + mark_px), min(img.size[1], y + mark_px)))
                if patch.size[0] < mark_px // 2:
                    continue
                dark = sum(1 for p in patch.getdata() if p < 95) / (patch.size[0] * patch.size[1])
                if dark >= 0.55:
                    blobs.append((x + mark_px / 2, y + mark_px / 2, dark))
        if len(blobs) < 4:
            return None
        blobs.sort(key=lambda b: b[2], reverse=True)
        candidates = [(b[0], b[1]) for b in blobs[: min(16, len(blobs))]]
        ordered = self._order_corners_tl_tr_bl_br(candidates)
        if ordered and self._validate_quad(ordered, scale, None):
            return ordered
        return None

    def _validate_quad(
        self,
        quad: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]],
        scale: float,
        layout: dict | None,
    ) -> bool:
        tl, tr, bl, br = quad
        width_top = ((tr[0] - tl[0]) ** 2 + (tr[1] - tl[1]) ** 2) ** 0.5
        width_bot = ((br[0] - bl[0]) ** 2 + (br[1] - bl[1]) ** 2) ** 0.5
        height_l = ((bl[0] - tl[0]) ** 2 + (bl[1] - tl[1]) ** 2) ** 0.5
        height_r = ((br[0] - tr[0]) ** 2 + (br[1] - tr[1]) ** 2) ** 0.5
        min_w = min(width_top, width_bot)
        min_h = min(height_l, height_r)
        if min_w < 35 * scale or min_h < 20 * scale:
            return False
        if layout:
            grid = layout["grid"]
            exp_w = grid["table_w"] * scale
            exp_h = grid["table_h"] * scale
            if min_w < exp_w * 0.5 or min_h < exp_h * 0.45:
                return False
            ratio = min_w / max(min_h, 1)
            exp_ratio = grid["table_w"] / max(grid["table_h"], 1)
            if abs(ratio - exp_ratio) > exp_ratio * 0.45:
                return False
        return True

    def _find_sync_row_ys(
        self,
        img: Image.Image,
        tl: tuple[float, float],
        bl: tuple[float, float],
        scale: float,
        n_rows: int,
    ) -> list[float] | None:
        sync_x = tl[0] + SYNC_COL_W * scale * 0.5
        x0 = int(sync_x - 3 * mm * scale)
        x1 = int(sync_x + 3 * mm * scale)
        y0 = int(min(tl[1], bl[1]) + GRID_HEADER_H * scale * 0.5)
        y1 = int(max(tl[1], bl[1]))
        dot_r = max(2, int(0.55 * mm * scale))
        blobs: list[tuple[float, float]] = []
        step = max(1, dot_r)
        for y in range(y0, y1, step):
            for x in range(x0, x1, step):
                dark = self._darkness_ratio(img, x, y, dot_r)
                if dark >= 0.45:
                    blobs.append((x, y))
        if len(blobs) < max(2, n_rows // 2):
            return None
        merged: list[float] = []
        min_dist = GRID_ROW_H * scale * 0.45
        for _, by in sorted(blobs, key=lambda b: b[1]):
            if any(abs(by - my) < min_dist for my in merged):
                continue
            merged.append(by)
        merged.sort()
        if len(merged) >= n_rows:
            return merged[:n_rows]
        return merged if len(merged) >= max(2, n_rows - 1) else None

    @staticmethod
    def _interp_edge_y(
        top: tuple[float, float],
        bottom: tuple[float, float],
        y: float,
    ) -> float:
        dy = bottom[1] - top[1]
        if abs(dy) < 1:
            return top[0]
        t = (y - top[1]) / dy
        t = max(0.0, min(1.0, t))
        return top[0] * (1 - t) + bottom[0] * t

    @staticmethod
    def _bilinear_map(
        tl: tuple[float, float],
        tr: tuple[float, float],
        bl: tuple[float, float],
        br: tuple[float, float],
        u: float,
        v: float,
    ) -> tuple[float, float]:
        top_x = tl[0] * (1 - u) + tr[0] * u
        top_y = tl[1] * (1 - u) + tr[1] * u
        bot_x = bl[0] * (1 - u) + br[0] * u
        bot_y = bl[1] * (1 - u) + br[1] * u
        cx = top_x * (1 - v) + bot_x * v
        cy = top_y * (1 - v) + bot_y * v
        return cx, cy

    def _fill_score(self, img: Image.Image, cx: int, cy: int, r: int) -> float:
        w, h = img.size
        inner_r = max(2, int(r * 0.55))
        inner_dark = inner_total = 0
        ring_dark = ring_total = 0
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy > r * r:
                    continue
                x, y = cx + dx, cy + dy
                if not (0 <= x < w and 0 <= y < h):
                    continue
                dark = img.getpixel((x, y)) < 115
                if dx * dx + dy * dy <= inner_r * inner_r:
                    inner_total += 1
                    if dark:
                        inner_dark += 1
                else:
                    ring_total += 1
                    if dark:
                        ring_dark += 1
        if inner_total == 0:
            return 0.0
        inner_ratio = inner_dark / inner_total
        ring_ratio = ring_dark / ring_total if ring_total else 0.0
        if inner_ratio < 0.25:
            return ring_ratio * 0.15
        return inner_ratio + max(0.0, inner_ratio - ring_ratio) * 0.5

    def _darkness_ratio(self, img: Image.Image, cx: int, cy: int, r: int) -> float:
        w, h = img.size
        dark = total = 0
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy > r * r:
                    continue
                x, y = cx + dx, cy + dy
                if 0 <= x < w and 0 <= y < h:
                    total += 1
                    if img.getpixel((x, y)) < 120:
                        dark += 1
        return dark / total if total else 0.0

    def _detect_bubbles_legacy(
        self,
        img: Image.Image,
        *,
        n_questoes: int,
        qr_rect: Any,
    ) -> list[dict[str, Any]]:
        from app.services.gabarito_layout import BUBBLE_R, BUBBLE_STEP, COL_LABEL_W, ROW_H_DEFAULT

        w, h = img.size
        scale = qr_rect.width / QR_SIZE if qr_rect and qr_rect.width > 0 else w / 595.0
        x0 = int(MARGIN * scale)
        x1 = int(min(w, w * 0.62))
        y0 = int(qr_rect.top + qr_rect.height + 2 * mm * scale)
        y1 = int(min(h, y0 + (HEADER_H + n_questoes * ROW_H_DEFAULT + 8 * mm) * scale))
        row_ys = self._find_row_centers_legacy(img, x0, x1, y0, y1, n_questoes, scale)
        step = int(BUBBLE_STEP * scale)
        base = x0 + int(COL_LABEL_W * scale) + step // 2
        anchor = base + step // 2
        r = max(4, int(BUBBLE_R * scale * 1.2))
        start_x = self._calibrar_inicio_legacy(img, row_ys, x0, x1, r, scale, base, anchor, step)
        respostas = []
        for q_idx, cy in enumerate(row_ys[:n_questoes]):
            marcada = self._marcada_linha_legacy(img, int(cy), start_x, r, step)
            respostas.append({"questao_numero": q_idx + 1, "resposta_marcada": marcada})
        return respostas

    def _find_row_centers_legacy(
        self, img: Image.Image, x0: int, x1: int, y0: int, y1: int, n_rows: int, scale: float
    ) -> list[int]:
        from app.services.gabarito_layout import ROW_H_DEFAULT

        scores: list[tuple[int, float]] = []
        for y in range(y0, y1, max(1, int(scale * 0.8))):
            dark = sum(1 for x in range(x0, x1, 2) if img.getpixel((x, y)) < 140)
            total = max(1, (x1 - x0) // 2)
            scores.append((y, dark / total))
        min_dist = int(ROW_H_DEFAULT * scale * 0.55)
        peaks: list[int] = []
        for y, score in sorted(scores, key=lambda t: t[1], reverse=True):
            if score < 0.06:
                continue
            if any(abs(y - py) < min_dist for py in peaks):
                continue
            peaks.append(y)
            if len(peaks) >= n_rows:
                break
        peaks.sort()
        if len(peaks) >= n_rows:
            return peaks[:n_rows]
        row_px = ROW_H_DEFAULT * scale
        y_start = y0 + 4 * mm * scale
        return [int(y_start + i * row_px + row_px / 2) for i in range(n_rows)]

    def _calibrar_inicio_legacy(
        self, img, row_ys, x0, x1, r, scale, base, anchor, step
    ) -> int:
        best_start = anchor
        best_metric = -1.0
        scan_step = max(1, step // 12)
        half_window = max(step // 2, scan_step * 2)
        for shift in range(-half_window, half_window + 1, scan_step):
            start = anchor + shift
            if start < x0 or start + 4 * step > x1:
                continue
            metric = 0.0
            for cy in row_ys:
                raw = [self._darkness_ratio(img, start + i * step, int(cy), r) for i in range(5)]
                raw.sort(reverse=True)
                metric += raw[0] + (raw[0] - raw[1]) * 3
            if metric > best_metric:
                best_metric = metric
                best_start = start
        return best_start

    def _marcada_linha_legacy(self, img, cy, start_x, r, step) -> str | None:
        fill_scores = [self._fill_score(img, start_x + i * step, cy, r) for i in range(5)]
        if max(fill_scores) >= 0.35:
            scores = list(zip(LETTERS, fill_scores))
        else:
            scores = [(LETTERS[i], self._darkness_ratio(img, start_x + i * step, cy, r)) for i in range(5)]
        return self._escolher_marcada(scores)
