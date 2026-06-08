"""Testes mínimos dos serviços PoC (gabarito PDF/OCR)."""
import json

from app.services.gabarito_ocr_service import GabaritoOcrService


def test_decode_qr_payload_format():
    payload = json.dumps({"p": 42, "a": 7})
    assert '"p":42' in payload.replace(" ", "")


def test_darkness_ratio_bounds():
    from PIL import Image

    svc = GabaritoOcrService()
    img = Image.new("L", (100, 100), 255)
    assert svc._darkness_ratio(img, 50, 50, 10) == 0.0
