import re
import unicodedata


class ChatRouterService:
    GENERAL_PATTERNS = [
        r"\boi\b",
        r"\bola\b",
        r"\btudo bem\b",
        r"\bme explica\b",
        r"\bo que e\b",
        r"\bresuma\b",
        r"\bcomo estudar\b",
        r"\bqual a diferenca\b",
    ]
    SYSTEM_PATTERNS = [
        r"\bmeu desempenho\b",
        r"\bminha nota\b",
        r"\bmeus descritores\b",
        r"\bminhas medalhas\b",
        r"\bminha turma\b",
        r"\bconteudo no sistema\b",
        r"\batividade\b",
        r"\bcurso\b",
        r"\bmaterial\b",
    ]
    INSTITUTIONAL_PATTERNS = [
        r"\bquais alunos\b",
        r"\bqual turma\b",
        r"\bindicadores\b",
        r"\bgestao\b",
        r"\bcoordenador\b",
        r"\bescola\b",
    ]

    def _normalize(self, text: str) -> str:
        value = unicodedata.normalize("NFKD", text.lower().strip())
        return "".join(ch for ch in value if not unicodedata.combining(ch))

    def classify(self, text: str) -> str:
        value = self._normalize(text)
        if any(re.search(pattern, value) for pattern in self.INSTITUTIONAL_PATTERNS):
            return "institutional"
        if any(re.search(pattern, value) for pattern in self.SYSTEM_PATTERNS):
            if any(re.search(pattern, value) for pattern in self.GENERAL_PATTERNS):
                return "hybrid"
            return "pedagogical"
        return "general"
