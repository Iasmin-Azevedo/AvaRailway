import requests
from app.core.config import settings

class MoodleClient:
    def __init__(self):
        self.base_url = settings.MOODLE_URL
        self.token = settings.MOODLE_TOKEN

    def enviar_nota(self, email_aluno: str, nota: float):
        # Simulação de envio
        print(f"📡 [Moodle] Enviando nota {nota} para {email_aluno}...")
        return True