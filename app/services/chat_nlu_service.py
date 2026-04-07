import httpx

from app.core.config import settings
from app.services.chat_router_service import ChatRouterService


class ChatNLUService:
    """Faz entendimento inicial da mensagem com provedor externo opcional e fallback local."""

    def __init__(self, router_service: ChatRouterService):
        self.router_service = router_service

    async def analyze(self, text: str) -> dict:
        local = self._local_analysis(text)
        provider = settings.CHAT_NLU_PROVIDER.lower().strip()
        if provider != "wit_ai" or not settings.WIT_AI_TOKEN:
            return local

        try:
            external = await self._analyze_with_wit(text)
            merged = {**local, **{k: v for k, v in external.items() if v not in (None, "", [])}}
            if not merged.get("subject"):
                merged["subject"] = local.get("subject")
            if not merged.get("message_type"):
                merged["message_type"] = local.get("message_type")
            merged["provider"] = "wit_ai"
            return merged
        except Exception:
            return local

    def _local_analysis(self, text: str) -> dict:
        return {
            "provider": "local",
            "message_type": self.router_service.classify(text),
            "subject": self.router_service.detect_subject(text),
            "is_greeting_only": self.router_service.is_greeting_only(text),
            "is_question": self.router_service.is_question(text),
            "wants_teacher_help": self.router_service.wants_teacher_help(text),
            "confidence": 0.6,
        }

    async def _analyze_with_wit(self, text: str) -> dict:
        headers = {"Authorization": f"Bearer {settings.WIT_AI_TOKEN}"}
        params = {"v": settings.WIT_AI_API_VERSION, "q": text}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{settings.WIT_AI_BASE_URL}/message", params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()

        intent_name = None
        confidence = 0.0
        intents = payload.get("intents") or []
        if intents:
            intent_name = intents[0].get("name")
            confidence = float(intents[0].get("confidence") or 0.0)

        subject = self._extract_subject(payload)
        wants_teacher_help = self._infer_teacher_help(intent_name, payload, text)
        message_type = self._infer_message_type(intent_name, text)

        return {
            "provider": "wit_ai",
            "message_type": message_type,
            "subject": subject,
            "is_greeting_only": intent_name in {"greeting", "saudacao"} or self.router_service.is_greeting_only(text),
            "is_question": self.router_service.is_question(text),
            "wants_teacher_help": wants_teacher_help,
            "confidence": confidence,
            "intent": intent_name,
        }

    def _extract_subject(self, payload: dict) -> str | None:
        entities = payload.get("entities") or {}
        candidates = []
        for key, values in entities.items():
            if not isinstance(values, list):
                continue
            if "disciplina" in key.lower() or "materia" in key.lower() or "subject" in key.lower():
                candidates.extend(item.get("value") for item in values if isinstance(item, dict))

        for candidate in candidates:
            if not candidate:
                continue
            normalized = str(candidate).strip().lower()
            if "mat" in normalized:
                return "Matemática"
            if "port" in normalized or "lingua" in normalized:
                return "Língua Portuguesa"
        return None

    def _infer_teacher_help(self, intent_name: str | None, payload: dict, text: str) -> bool:
        if intent_name in {"teacher_help", "falar_com_professor", "solicitar_professor"}:
            return True
        traits = payload.get("traits") or {}
        if any("professor" in key.lower() for key in traits.keys()):
            return True
        return self.router_service.wants_teacher_help(text)

    def _infer_message_type(self, intent_name: str | None, text: str) -> str:
        if intent_name in {"teacher_help", "falar_com_professor", "solicitar_professor"}:
            return "pedagogical"
        if intent_name in {"institutional", "dashboard", "gestao"}:
            return "institutional"
        if intent_name in {"pedagogical", "question", "duvida", "content_help"}:
            return "pedagogical"
        return self.router_service.classify(text)
