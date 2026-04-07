import re


try:
    import sympy
except Exception:  # pragma: no cover - dependencia opcional
    sympy = None


class ChatMathService:
    """Resolve e explica perguntas matematicas simples com mais precisao."""

    KEYWORDS = {
        "matematica",
        "fracao",
        "equacao",
        "expressao",
        "porcentagem",
        "percentual",
        "regra de tres",
        "divisao",
        "multiplicacao",
        "subtracao",
        "soma",
    }

    def _looks_like_math(self, text: str) -> bool:
        value = text.lower()
        if any(keyword in value for keyword in self.KEYWORDS):
            return True
        return bool(re.search(r"[\d\+\-\*/=()]{3,}", value))

    def try_answer(self, text: str) -> str | None:
        if not sympy or not self._looks_like_math(text):
            return None

        cleaned = text.lower().replace("^", "**")
        expression = re.sub(r"[^0-9a-z\+\-\*/=\(\)\.\s\*]", " ", cleaned)
        expression = " ".join(expression.split())
        if not expression:
            return None

        try:
            if "=" in expression:
                left, right = expression.split("=", 1)
                x = sympy.Symbol("x")
                equation = sympy.Eq(sympy.sympify(left), sympy.sympify(right))
                solution = sympy.solve(equation, x)
                if solution:
                    return (
                        "Encontrei uma equacao. "
                        f"A solucao para x e {solution[0]}. "
                        "Se quiser, eu tambem posso explicar o passo a passo."
                    )

            result = sympy.sympify(expression).simplify()
            if result is not None:
                return (
                    f"Resolvi a expressao informada. O resultado e {result}. "
                    "Se quiser, eu posso detalhar o raciocinio em etapas."
                )
        except Exception:
            return None

        return None
