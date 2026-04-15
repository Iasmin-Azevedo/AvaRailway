import re
import unicodedata


class ChatRouterService:
    """Classifica a intenção principal da mensagem enviada ao chatbot."""

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
    MATH_PATTERNS = [
        r"\bmatematica\b",
        r"\bfracao\b",
        r"\bfracoes\b",
        r"\bdivisao\b",
        r"\bmultiplicacao\b",
        r"\bporcentagem\b",
        r"\bequacao\b",
        r"\bconta\b",
        r"\bnumero\b",
        r"\bgeometria\b",
    ]
    PORTUGUESE_PATTERNS = [
        r"\bportugues\b",
        r"\blingua portuguesa\b",
        r"\btexto\b",
        r"\binterpretacao\b",
        r"\bacentuacao\b",
        r"\bvirgula\b",
        r"\bgramatica\b",
        r"\bsubstantivo\b",
        r"\badjetivo\b",
    ]
    TEACHER_HELP_PATTERNS = [
        r"\bfalar com (o )?professor\b",
        r"\bchamar (o )?professor\b",
        r"\bquero ajuda do professor\b",
        r"\bquero tirar duvida com o professor\b",
        r"\bprofessor dessa materia\b",
        r"\bpreciso do professor\b",
    ]
    ACTIVITY_PATTERNS = [
        r"\batividade\b",
        r"\bexercicio\b",
        r"\btarefa\b",
        r"\bquestao\b",
        r"\bquestoes\b",
        r"\bprova\b",
        r"\bsimulado\b",
    ]
    LIVE_CLASS_PATTERNS = [
        r"\baula ao vivo\b",
        r"\bao vivo\b",
        r"\bvideoconferencia\b",
        r"\breuniao\b",
        r"\bmeet\b",
        r"\bjitsi\b",
        r"\bchamada\b",
    ]
    PLATFORM_PATTERNS = [
        r"\bplataforma\b",
        r"\bsistema\b",
        r"\btrilha\b",
        r"\bdesempenho\b",
        r"\bmedalha\b",
        r"\bpontuacao\b",
        r"\bdashboard\b",
        r"\blogin\b",
    ]
    MATH_STEMS = ("mat", "frac", "equa", "divis", "multi", "porcen", "geometr", "num")
    PORTUGUESE_STEMS = ("port", "ling", "text", "interpre", "acent", "virgul", "gramat", "substant", "adjet")
    TEACHER_HELP_STEMS = ("prof", "docent", "ajud", "duvid", "explic")
    ACTIVITY_STEMS = ("ativ", "exerc", "taref", "quest", "prov", "simulad")
    LIVE_CLASS_STEMS = ("aula", "vivo", "video", "reunia", "meet", "jitsi", "chamad")
    PLATFORM_STEMS = ("plataform", "sistem", "trilh", "desempenh", "medalh", "pontu", "dashboard", "login")

    def _normalize(self, text: str) -> str:
        value = unicodedata.normalize("NFKD", text.lower().strip())
        return "".join(ch for ch in value if not unicodedata.combining(ch))

    def _tokens(self, text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", self._normalize(text))

    def _has_stem(self, tokens: list[str], stems: tuple[str, ...]) -> bool:
        return any(token.startswith(stem) for token in tokens for stem in stems)

    def classify(self, text: str) -> str:
        """Classifica a mensagem em contexto geral, pedagógico ou institucional."""
        value = self._normalize(text)
        tokens = self._tokens(text)
        if any(re.search(pattern, value) for pattern in self.INSTITUTIONAL_PATTERNS):
            return "institutional"
        if self._has_stem(tokens, ("gest", "coord", "escol", "indic", "relat")):
            return "institutional"
        if any(re.search(pattern, value) for pattern in self.SYSTEM_PATTERNS):
            if any(re.search(pattern, value) for pattern in self.GENERAL_PATTERNS):
                return "hybrid"
            return "pedagogical"
        if self._has_stem(tokens, self.ACTIVITY_STEMS + self.PLATFORM_STEMS):
            return "pedagogical"
        return "general"

    def is_greeting_only(self, text: str) -> bool:
        """Identifica saudações curtas que não exigem fluxo completo de resposta."""
        value = self._normalize(text)
        return value in {"oi", "ola", "opa", "bom dia", "boa tarde", "boa noite", "e ai"}

    def is_question(self, text: str) -> bool:
        """Identifica perguntas explícitas por pontuação ou padrão de abertura."""
        value = self._normalize(text)
        if "?" in text:
            return True
        starters = (
            "o que",
            "como",
            "qual",
            "quais",
            "quando",
            "onde",
            "por que",
            "porque",
            "me explique",
            "me ajuda",
        )
        return value.startswith(starters)

    def detect_subject(self, text: str) -> str | None:
        """Identifica a disciplina principal citada na mensagem."""
        value = self._normalize(text)
        tokens = self._tokens(text)
        if any(re.search(pattern, value) for pattern in self.MATH_PATTERNS):
            return "Matemática"
        if self._has_stem(tokens, self.MATH_STEMS):
            return "Matemática"
        if any(re.search(pattern, value) for pattern in self.PORTUGUESE_PATTERNS):
            return "Língua Portuguesa"
        if self._has_stem(tokens, self.PORTUGUESE_STEMS):
            return "Língua Portuguesa"
        return None

    def wants_teacher_help(self, text: str) -> bool:
        """Detecta quando o usuário quer encaminhamento para um professor."""
        value = self._normalize(text)
        if any(re.search(pattern, value) for pattern in self.TEACHER_HELP_PATTERNS):
            return True
        return self._has_stem(self._tokens(text), self.TEACHER_HELP_STEMS)

    def detect_support_topic(self, text: str) -> str | None:
        """Identifica temas operacionais para respostas guiadas."""
        value = self._normalize(text)
        tokens = self._tokens(text)
        if any(re.search(pattern, value) for pattern in self.ACTIVITY_PATTERNS):
            return "atividade"
        if self._has_stem(tokens, self.ACTIVITY_STEMS):
            return "atividade"
        if any(re.search(pattern, value) for pattern in self.LIVE_CLASS_PATTERNS):
            return "aula_ao_vivo"
        if self._has_stem(tokens, self.LIVE_CLASS_STEMS):
            return "aula_ao_vivo"
        if any(re.search(pattern, value) for pattern in self.PLATFORM_PATTERNS):
            return "plataforma"
        if self._has_stem(tokens, self.PLATFORM_STEMS):
            return "plataforma"
        return None
