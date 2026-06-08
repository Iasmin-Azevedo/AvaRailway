#!/usr/bin/env python3
"""Validação em lote do OCR de gabaritos para a PoC Paracuru.

Uso:
  python scripts/validar_ocr_lote.py tests/fixtures/ocr/*.png
  python scripts/validar_ocr_lote.py --n-questoes 4 --json-out docs/OCR_VALIDACAO_LOTE_POC.json caminho/*.png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.gabarito_ocr_service import GabaritoOcrService


def validar_lote(paths: list[Path], *, n_questoes: int) -> dict:
    svc = GabaritoOcrService()
    detalhes: list[dict] = []
    for path in paths:
        row: dict = {"arquivo": path.name}
        try:
            data = path.read_bytes()
            r = svc.processar_imagem(data, n_questoes=n_questoes)
            respostas = {x["questao_numero"]: x.get("resposta_marcada") for x in r.get("respostas") or []}
            preenchidas = sum(1 for v in respostas.values() if v)
            row.update(
                {
                    "ok": True,
                    "participacao_id": r.get("participacao_id"),
                    "respostas": respostas,
                    "questoes_lidas": preenchidas,
                    "questoes_total": len(respostas),
                    "taxa_leitura_pct": round(100 * preenchidas / max(len(respostas), 1), 1),
                }
            )
        except Exception as exc:
            row.update({"ok": False, "erro": str(exc), "taxa_leitura_pct": 0.0})
        detalhes.append(row)

    taxas = [d.get("taxa_leitura_pct", 0) for d in detalhes]
    return {
        "folhas": len(detalhes),
        "folhas_ok": sum(1 for d in detalhes if d.get("ok")),
        "media_taxa_leitura_pct": round(sum(taxas) / max(len(taxas), 1), 1),
        "n_questoes": n_questoes,
        "detalhes": detalhes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validação OCR em lote (PoC Paracuru)")
    parser.add_argument("imagens", nargs="+", help="Caminhos das imagens PNG/JPG")
    parser.add_argument("--n-questoes", type=int, default=4)
    parser.add_argument("--json-out", type=str, default="")
    args = parser.parse_args()

    paths = [Path(p) for p in args.imagens]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        print("Arquivos não encontrados:", ", ".join(str(p) for p in missing), file=sys.stderr)
        return 1

    resultado = validar_lote(paths, n_questoes=args.n_questoes)
    text = json.dumps(resultado, ensure_ascii=False, indent=2)
    print(text)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")

    # Critério PoC: ≥10 folhas, média ≥85%, folhas base 100% se presentes
    if resultado["folhas"] < 10:
        return 2
    if resultado["media_taxa_leitura_pct"] < 85:
        return 3
    bases = {f"Group_{n}.png" for n in ("241", "243", "244", "245")}
    base_rows = [d for d in resultado["detalhes"] if d.get("arquivo") in bases]
    if base_rows:
        for d in base_rows:
            if not d.get("ok") or d.get("taxa_leitura_pct", 0) < 100:
                return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
