"""Dimensões compartilhadas entre geração PDF e leitura OCR (grade tabular)."""
from __future__ import annotations

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

PAGE_W, PAGE_H = A4

MARGIN = 8 * mm
SHEET_GAP = 3 * mm
QR_SIZE = 24 * mm
HEADER_H = 30 * mm

# Grade: coluna de sincronismo + Q + A–E
SYNC_COL_W = 4 * mm
GRID_NUM_COL_W = 10 * mm
GRID_CELL_W = 10 * mm
GRID_HEADER_H = 6 * mm
GRID_ROW_H = 6.5 * mm
CORNER_CROSS = 2.2 * mm
CORNER_OFFSET = 1.8 * mm

BUBBLE_R = 2.3 * mm
LETTERS = "ABCDE"
N_ALT = 5

BUBBLE_STEP = GRID_CELL_W
COL_LABEL_W = SYNC_COL_W + GRID_NUM_COL_W
ROW_H_DEFAULT = GRID_ROW_H
MIN_SHEET_H = 72 * mm


def grid_table_size(n_questoes: int, *, cols: int = 1) -> dict:
    cols = max(1, cols)
    per_col = max(1, (n_questoes + cols - 1) // cols)
    table_w = SYNC_COL_W + GRID_NUM_COL_W + N_ALT * GRID_CELL_W
    table_h = GRID_HEADER_H + per_col * GRID_ROW_H
    return {
        "cols": cols,
        "per_col": per_col,
        "table_w": table_w,
        "table_h": table_h,
        "n_questoes": n_questoes,
    }


def compute_sheet_dimensions(n_questoes: int) -> dict:
    grid = grid_table_size(n_questoes, cols=1)
    sheet_h = MARGIN + HEADER_H + grid["table_h"] + MARGIN + 2 * mm
    sheet_h = max(sheet_h, MIN_SHEET_H)
    return {
        "page_w": PAGE_W,
        "page_h": PAGE_H,
        "sheet_w": PAGE_W,
        "sheet_h": sheet_h,
        "grid": grid,
        "cols": grid["cols"],
        "per_col": grid["per_col"],
        "row_h": GRID_ROW_H,
        "n_questoes": n_questoes,
    }


def compute_sheet_layout(n_questoes: int) -> dict:
    dims = compute_sheet_dimensions(n_questoes)
    g = dims["grid"]
    return {
        "page_w": dims["sheet_w"],
        "page_h": dims["sheet_h"],
        "cols": g["cols"],
        "per_col": g["per_col"],
        "row_h": GRID_ROW_H,
        "n_questoes": n_questoes,
        "grid": g,
    }


def cell_center_pdf(grid_left: float, grid_top: float, row: int, alt_index: int) -> tuple[float, float]:
    cx = grid_left + SYNC_COL_W + GRID_NUM_COL_W + (alt_index + 0.5) * GRID_CELL_W
    cy = grid_top - GRID_HEADER_H - (row + 0.5) * GRID_ROW_H
    return cx, cy


def sync_dot_pdf(grid_left: float, grid_top: float, row: int) -> tuple[float, float]:
    """Ponto de sincronismo por linha (centro da coluna sync)."""
    cx = grid_left + SYNC_COL_W / 2
    cy = grid_top - GRID_HEADER_H - (row + 0.5) * GRID_ROW_H
    return cx, cy


def corner_crosses_pdf(grid_left: float, grid_top: float, table_w: float, table_h: float) -> list[tuple[float, float]]:
    """Centros dos '+' de registro fora dos cantos da tabela."""
    o = CORNER_OFFSET
    grid_bottom = grid_top - table_h
    return [
        (grid_left - o, grid_top + o),
        (grid_left + table_w + o, grid_top + o),
        (grid_left - o, grid_bottom - o),
        (grid_left + table_w + o, grid_bottom - o),
    ]
