import re
import unicodedata


class ChatGuardrailsService:
    def __init__(self):
        self.blocked_patterns = [
            r"\bporra\b",
            r"\bcaralho\b",
            r"\bmerda\b",
            r"\bidiota\b",
            r"\bburro\b",
            r"\botario\b",
            r"\bdesgraca\b",
            r"\bmacaco\b",
            r"\bpreto imundo\b",
            r"\bviado\b",
            r"\bsapat[aã]o\b",
            r"\bnazista\b",
            r"\bhitler\b",
            r"\bestupro\b",
            r"\bgenocidio\b",
            r"\bexterminar\b",
            r"\bmatar\b.*\b(gay|negro|preto|mulher|judeu|trans)\b",
            r"\bodio\b.*\b(gay|negro|preto|mulher|judeu|trans)\b",
        ]
        self.safe_reply = (
            "Nao posso ajudar com ofensas, palavroes, discriminacao ou qualquer conteudo que fira "
            "a dignidade humana. Se voce quiser, posso reformular sua pergunta de forma respeitosa "
            "e ajudar no tema permitido."
        )

    def _normalize(self, text: str) -> str:
        value = unicodedata.normalize("NFKD", text.lower().strip())
        return "".join(ch for ch in value if not unicodedata.combining(ch))

    def has_blocked_content(self, text: str) -> bool:
        normalized = self._normalize(text)
        return any(re.search(pattern, normalized) for pattern in self.blocked_patterns)

    def ensure_user_message_allowed(self, text: str) -> None:
        if self.has_blocked_content(text):
            raise ValueError(
                "Nao posso processar mensagens com palavroes, ofensas, discriminacao "
                "ou conteudo que viole direitos humanos."
            )

    def sanitize_assistant_message(self, text: str) -> str:
        if self.has_blocked_content(text):
            return self.safe_reply
        return text
