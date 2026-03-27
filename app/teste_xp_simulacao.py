"""
Simulador rapido de XP para calibracao de regras.

Exemplo:
python app/teste_xp_simulacao.py --tipo quiz --score 80 --qtd 12
python app/teste_xp_simulacao.py --plano quiz:85:8 video:70:4
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.gamification_rules import LEVEL_THRESHOLDS, calculate_xp_gain


def _simulate_item(tipo: str, score: float, qtd: int) -> tuple[int, int]:
    xp_unit = calculate_xp_gain(tipo, score, is_first_completion=True)
    xp_total = xp_unit * max(0, qtd)
    return xp_unit, xp_total


def _next_level_info(xp_total: int) -> tuple[str, str | None, int]:
    for faixa in LEVEL_THRESHOLDS:
        min_xp = int(faixa["min"])  # type: ignore[arg-type]
        max_xp = int(faixa["max"])  # type: ignore[arg-type]
        if xp_total < max_xp:
            falta = max(0, max_xp - xp_total)
            return str(faixa["nivel"]), faixa["proximo"], falta  # type: ignore[return-value]
    last = LEVEL_THRESHOLDS[-1]
    return str(last["nivel"]), None, 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulador de pontuacao XP")
    parser.add_argument("--tipo", default=None, help="Tipo unico (quiz, video, etc.)")
    parser.add_argument("--score", type=float, default=80.0, help="Score medio 0..100")
    parser.add_argument("--qtd", type=int, default=10, help="Quantidade de atividades")
    parser.add_argument(
        "--plano",
        nargs="*",
        default=[],
        help="Lista tipo:score:qtd (ex.: quiz:85:8 video:70:4)",
    )
    parser.add_argument("--xp-atual", type=int, default=0, help="XP atual do aluno")
    args = parser.parse_args()

    rows: list[tuple[str, float, int, int, int]] = []
    if args.plano:
        for item in args.plano:
            try:
                tipo, score_str, qtd_str = item.split(":")
                score = float(score_str)
                qtd = int(qtd_str)
            except ValueError:
                raise SystemExit(f"Formato invalido em '{item}'. Use tipo:score:qtd")
            xp_unit, xp_total = _simulate_item(tipo, score, qtd)
            rows.append((tipo, score, qtd, xp_unit, xp_total))
    else:
        tipo = args.tipo or "quiz"
        xp_unit, xp_total = _simulate_item(tipo, args.score, args.qtd)
        rows.append((tipo, args.score, args.qtd, xp_unit, xp_total))

    ganho_total = sum(r[4] for r in rows)
    xp_final = int(args.xp_atual + ganho_total)
    nivel_atual, proximo, falta = _next_level_info(xp_final)

    print("=== Simulacao de XP ===")
    print(f"XP atual: {args.xp_atual}")
    print("-" * 60)
    print(f"{'Tipo':<14}{'Score':>8}{'Qtd':>8}{'XP/atv':>10}{'XP total':>12}")
    print("-" * 60)
    for tipo, score, qtd, xp_unit, xp_total in rows:
        print(f"{tipo:<14}{score:>8.1f}{qtd:>8}{xp_unit:>10}{xp_total:>12}")
    print("-" * 60)
    print(f"Ganho total: {ganho_total}")
    print(f"XP final: {xp_final}")
    print(f"Nivel apos simulacao: {nivel_atual}")
    if proximo:
        print(f"Falta para proximo nivel ({proximo}): {falta} XP")
    else:
        print("Ja esta no nivel maximo configurado.")


if __name__ == "__main__":
    main()
