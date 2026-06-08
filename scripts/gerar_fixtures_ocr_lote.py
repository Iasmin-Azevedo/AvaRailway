#!/usr/bin/env python3
"""Gera variantes de fixtures OCR (4 originais + 6 derivadas = 10+) para validação em lote.

Uso:
  python scripts/gerar_fixtures_ocr_lote.py
  python scripts/validar_ocr_lote.py tests/fixtures/ocr/*.png
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageEnhance, ImageOps

FIXTURES = ROOT / "tests" / "fixtures" / "ocr"
BASE_NAMES = ["Group_241.png", "Group_243.png", "Group_244.png", "Group_245.png"]

VARIANTS = [
    ("_bright", lambda im: ImageEnhance.Brightness(im).enhance(1.12)),
    ("_dim", lambda im: ImageEnhance.Brightness(im).enhance(0.88)),
    ("_contrast", lambda im: ImageEnhance.Contrast(im).enhance(1.15)),
    ("_autocontrast", lambda im: ImageOps.autocontrast(im)),
    ("_rot1", lambda im: im.rotate(1.2, expand=True, fillcolor=255)),
    ("_rotm1", lambda im: im.rotate(-1.2, expand=True, fillcolor=255)),
]


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    created = 0
    for base in BASE_NAMES:
        src = FIXTURES / base
        if not src.is_file():
            print(f"Pulando (ausente): {src}")
            continue
        im = Image.open(src).convert("L")
        for suffix, fn in VARIANTS:
            out = FIXTURES / f"{src.stem}{suffix}.png"
            if out.exists():
                continue
            out_im = fn(im.copy())
            out_im.save(out, format="PNG")
            created += 1
            print(f"Criado: {out.name}")
    total = len(list(FIXTURES.glob("*.png")))
    print(f"\nTotal PNG em {FIXTURES}: {total}")
    return 0 if total >= 10 else 1


if __name__ == "__main__":
    raise SystemExit(main())
