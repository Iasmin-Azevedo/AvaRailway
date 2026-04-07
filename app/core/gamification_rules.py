from typing import Optional


# Progressao rapida: primeiros niveis sobem com poucas atividades bem resolvidas.
LEVEL_THRESHOLDS: list[dict[str, Optional[int | str]]] = [
    {"nivel": "Novato", "min": 0, "max": 600, "proximo": "Intermediário"},
    {"nivel": "Intermediário", "min": 600, "max": 1200, "proximo": "Especialista"},
    {"nivel": "Especialista", "min": 1200, "max": 2000, "proximo": "Mestre SAEB"},
    {"nivel": "Mestre SAEB", "min": 2000, "max": 2600, "proximo": "Lenda SAEB"},
    {"nivel": "Lenda SAEB", "min": 2600, "max": 3200, "proximo": None},
]

# XP base por tipo de atividade H5P.
XP_BASE_BY_TYPE: dict[str, int] = {
    "quiz": 80,
    "multiple-choice": 78,
    "fill-blanks": 75,
    "interactive-book": 62,
    "drag-words": 72,
    "course-presentation": 58,
    "drag-drop": 70,
    "video": 50,
    "flashcards": 60,
    "presentation": 55,
    "outro": 50,
}

XP_DEFAULT_BASE = 50
XP_FIRST_COMPLETION_ONLY = True

# Bonus maximo de score por tipo (score em 0..100).
XP_MAX_SCORE_BONUS_BY_TYPE: dict[str, int] = {
    "quiz": 40,
    "multiple-choice": 38,
    "fill-blanks": 35,
    "interactive-book": 26,
    "drag-words": 34,
    "course-presentation": 22,
    "drag-drop": 35,
    "video": 20,
    "flashcards": 25,
    "presentation": 20,
    "outro": 20,
}

XP_DEFAULT_MAX_SCORE_BONUS = 20


def calculate_xp_gain(activity_type: str, score: Optional[float], is_first_completion: bool) -> int:
    """
    Calcula XP de uma atividade com base no tipo e no score.
    Score esperado em 0..100. Fora da faixa e normalizado.
    """
    if XP_FIRST_COMPLETION_ONLY and not is_first_completion:
        return 0

    tipo = (activity_type or "outro").strip().lower()
    base_xp = XP_BASE_BY_TYPE.get(tipo, XP_DEFAULT_BASE)
    max_bonus = XP_MAX_SCORE_BONUS_BY_TYPE.get(tipo, XP_DEFAULT_MAX_SCORE_BONUS)

    if score is None:
        return int(base_xp)

    normalized = max(0.0, min(100.0, float(score)))
    bonus = int((normalized / 100.0) * max_bonus)
    return int(base_xp + bonus)


def get_level_progress(xp_total: int) -> dict:
    xp = int(xp_total or 0)
    faixa = LEVEL_THRESHOLDS[-1]
    for f in LEVEL_THRESHOLDS:
        if xp < int(f["max"]):  # type: ignore[arg-type]
            faixa = f
            break

    base = int(faixa["min"])  # type: ignore[arg-type]
    meta = int(faixa["max"])  # type: ignore[arg-type]
    atual_no_nivel = max(0, xp - base)
    meta_no_nivel = max(1, meta - base)
    pct = max(0, min(100, int((atual_no_nivel / meta_no_nivel) * 100)))

    return {
        "nivel": faixa["nivel"],
        "proximo_nivel": faixa["proximo"],
        "xp_atual_nivel": atual_no_nivel,
        "xp_meta_nivel": meta_no_nivel,
        "xp_pct_nivel": pct,
    }
