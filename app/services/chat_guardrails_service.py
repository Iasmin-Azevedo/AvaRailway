import re
import unicodedata


class ChatGuardrailsService:
    """Aplica regras de segurança e moderação sobre mensagens do chat."""

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
            r"\bme matar\b",
            r"\bquero morrer\b",
            r"\bcomo me matar\b",
            r"\bcomo suicidar\b",
            r"\bsexo com menor\b",
            r"\bpornografia infantil\b",
            r"\bexplorar menor\b",
            r"\broubar senha\b",
            r"\binvadir\b.*\b(conta|sistema|servidor)\b",
        ]
        self.mutation_patterns = [
            r"\balter(ar|e)\b.*\b(senha|usuario|perfil|permiss[aã]o|nota|dados|configurac[aã]o)\b",
            r"\bmud(ar|e)\b.*\b(senha|usuario|perfil|permiss[aã]o|nota|dados|configurac[aã]o)\b",
            r"\bpromov(a|er)\b.*\b(admin|administrador|gestor|coordenador|professor)\b",
            r"\bd[eê] permiss[aã]o\b",
            r"\bliber(ar|e)\b.*\b(acesso|permiss[aã]o)\b",
            r"\bapagu(e|ar)\b.*\b(dados|usuario|prova|historico|registro)\b",
            r"\bexclu(a|ir)\b.*\b(dados|usuario|prova|historico|registro)\b",
            r"\breset(ar|e)\b.*\b(senha|usuario|sistema)\b",
            r"\bdesativ(ar|e)\b.*\b(seguranca|log|auditoria)\b",
            r"\binativ(ar|e)\b.*\b(usuario|auditoria|seguranca)\b",
            r"\badicion(ar|e)\b.*\b(permiss[aã]o|acesso)\b",
            r"\bremov(a|er)\b.*\b(permiss[aã]o|acesso|restric[aã]o)\b",
        ]
        self.safe_reply = (
            "Não posso ajudar com ofensas, palavrões, discriminação ou qualquer conteúdo que fira "
            "a dignidade humana. Se você quiser, posso reformular sua pergunta de forma respeitosa "
            "e ajudar no tema permitido."
        )
        self.protected_reply = (
            "Não posso ajudar com pedido de violência, autoagressão, exploração sexual, invasão, "
            "roubo de acesso ou qualquer conteúdo perigoso. Se a situação for acadêmica ou preventiva, "
            "posso explicar o tema de forma segura e educativa."
        )
        self.mutation_reply = (
            "Não posso executar, orientar ou autorizar alterações operacionais no sistema por conversa, "
            "como mudança de permissão, senha, perfil, configuração, nota ou exclusão de dados. "
            "Se houver necessidade real, isso deve ser feito pelos fluxos administrativos e técnicos apropriados."
        )

    def _normalize(self, text: str) -> str:
        value = unicodedata.normalize("NFKD", text.lower().strip())
        return "".join(ch for ch in value if not unicodedata.combining(ch))

    def has_blocked_content(self, text: str) -> bool:
        """Detecta conteúdo ofensivo, discriminatório ou perigoso."""
        normalized = self._normalize(text)
        return any(re.search(pattern, normalized) for pattern in self.blocked_patterns)

    def requests_system_mutation(self, text: str) -> bool:
        """Detecta tentativas de alterar dados, permissões ou configurações do sistema."""
        normalized = self._normalize(text)
        return any(re.search(pattern, normalized) for pattern in self.mutation_patterns)

    def get_violation_response(self, text: str) -> tuple[str, str] | None:
        """Retorna a ação e a resposta de bloqueio quando houver violação."""
        if self.has_blocked_content(text):
            return (
                "blocked_offense",
                "Essa mensagem foi bloqueada. Aqui, o chat precisa manter respeito, sem xingamentos, ofensas, discriminação ou conteúdo que fira os direitos humanos. Se quiser, reformule sua pergunta de forma respeitosa que eu continuo te ajudando.",
            )
        if self.requests_system_mutation(text):
            return ("blocked_system_mutation", self.mutation_reply)
        return None

    def sanitize_assistant_message(self, text: str) -> str:
        """Garante que a resposta do assistente siga as mesmas regras de segurança."""
        if self.has_blocked_content(text):
            normalized = self._normalize(text)
            if any(keyword in normalized for keyword in ["matar", "morrer", "invadir", "menor", "senha"]):
                return self.protected_reply
            return self.safe_reply
        if self.requests_system_mutation(text):
            return self.mutation_reply
        return text
