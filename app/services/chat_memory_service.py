from app.repositories.chat_repository import ChatRepository


class ChatMemoryService:
    def __init__(self, chat_repository: ChatRepository):
        self.chat_repository = chat_repository

    def get_memory_summary(self, session_id: str) -> str:
        memory = self.chat_repository.get_memory(session_id)
        return memory.summary_text if memory else ""

    def maybe_update_memory(self, session_id: str, full_history: list, every_n: int = 8) -> None:
        if not full_history or len(full_history) % every_n != 0:
            return

        summarized_lines = []
        for item in full_history[-12:]:
            prefix = "Usuario" if item.sender == "user" else "Assistente"
            text = item.message_text.replace("\n", " ").strip()
            summarized_lines.append(f"{prefix}: {text[:250]}")

        summary = "Resumo da conversa ate aqui:\n" + "\n".join(summarized_lines)
        self.chat_repository.upsert_memory(session_id=session_id, summary_text=summary)
