"""Testes de validação OCR em lote (fixtures PoC Paracuru)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.gabarito_ocr_service import GabaritoOcrService

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ocr"
EXPECTED = {
    "Group_243": {"1": "B", "2": "B", "3": "B", "4": "B"},
    "Group_244": {"1": "B", "2": "B", "3": "B", "4": "B"},
    "Group_245": {"1": "B", "2": "B", "3": "B", "4": "B"},
    "Group_241": {"1": "C", "2": "C", "3": "C", "4": "C"},
}


def _fixture_paths() -> list[Path]:
    if not FIXTURES.is_dir():
        return []
    bases = [FIXTURES / f"Group_{n}.png" for n in ("241", "243", "244", "245")]
    return [p for p in bases if p.is_file()]


def _all_fixture_paths() -> list[Path]:
    if not FIXTURES.is_dir():
        return []
    return sorted(FIXTURES.glob("Group_*.png"))


@pytest.mark.skipif(not _fixture_paths(), reason="Fixtures OCR não disponíveis")
@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: p.name[:20])
def test_ocr_lote_fixture(path: Path):
    key = next((k for k in EXPECTED if k in path.name), None)
    assert key, f"Fixture sem gabarito esperado: {path.name}"

    svc = GabaritoOcrService()
    r = svc.processar_imagem(path.read_bytes(), n_questoes=4)
    assert r.get("participacao_id"), "QR/participação não identificados"

    got = {str(x["questao_numero"]): x.get("resposta_marcada") for x in r["respostas"]}
    exp = {str(k): v for k, v in EXPECTED[key].items()}
    assert got == exp, json.dumps({"esperado": exp, "lido": got}, ensure_ascii=False)


@pytest.mark.skipif(len(_all_fixture_paths()) < 10, reason="Menos de 10 fixtures OCR")
def test_ocr_lote_minimo_dez_folhas():
    svc = GabaritoOcrService()
    ok_qr = 0
    lidas = 0
    total_q = 0
    for path in _all_fixture_paths():
        try:
            r = svc.processar_imagem(path.read_bytes(), n_questoes=4)
        except ValueError:
            continue
        if r.get("participacao_id"):
            ok_qr += 1
        for resp in r.get("respostas") or []:
            total_q += 1
            if resp.get("resposta_marcada"):
                lidas += 1
    n = len(_all_fixture_paths())
    assert n >= 10, f"Esperado ≥10 fixtures, encontrado {n}"
    assert ok_qr >= int(n * 0.92), f"QR OK em {ok_qr}/{n} (mín. 92%)"
    assert lidas / max(total_q, 1) >= 0.85, f"Taxa leitura {100*lidas/max(total_q,1):.1f}%"


@pytest.mark.skipif(not _fixture_paths(), reason="Fixtures OCR base não disponíveis")
def test_ocr_lote_taxa_minima_poc():
    svc = GabaritoOcrService()
    total = acertos = 0
    for path in _fixture_paths():
        key = next((k for k in EXPECTED if k in path.name), None)
        if not key:
            continue
        r = svc.processar_imagem(path.read_bytes(), n_questoes=4)
        got = {x["questao_numero"]: x.get("resposta_marcada") for x in r["respostas"]}
        for q, exp in EXPECTED[key].items():
            total += 1
            if got.get(int(q)) == exp:
                acertos += 1
    taxa = 100 * acertos / max(total, 1)
    assert taxa >= 90, f"Taxa OCR abaixo do mínimo PoC: {taxa:.1f}%"
