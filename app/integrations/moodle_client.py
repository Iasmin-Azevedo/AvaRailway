import time

import requests

from app.core.config import settings


class MoodleClient:
    _contents_cache: tuple[float, list[dict]] | None = None

    def __init__(self):
        self.base_url = settings.MOODLE_URL.rstrip("/")
        self.token = settings.MOODLE_TOKEN

    def enviar_nota(self, email_aluno: str, nota: float):
        print(f"[Moodle] Enviando nota {nota} para {email_aluno}...")
        return True

    def _request(self, wsfunction: str, **params):
        response = requests.get(
            f"{self.base_url}/webservice/rest/server.php",
            params={
                "wstoken": self.token,
                "moodlewsrestformat": "json",
                "wsfunction": wsfunction,
                **params,
            },
            timeout=8,
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("exception"):
            raise RuntimeError(data.get("message", "Falha ao consultar o Moodle"))
        return data

    def fetch_learning_content(self) -> list[dict]:
        now = time.time()
        if self._contents_cache and now - self._contents_cache[0] < 300:
            return self._contents_cache[1]

        if not self.token or "seu-token" in self.token.lower():
            return []

        try:
            courses = self._request("core_course_get_courses")
        except Exception:
            return []

        contents = []
        for course in courses[:5]:
            course_id = course.get("id")
            if not course_id:
                continue
            try:
                sections = self._request("core_course_get_contents", courseid=course_id)
            except Exception:
                continue
            for section in sections[:5]:
                for module in section.get("modules", [])[:10]:
                    contents.append(
                        {
                            "course": course.get("fullname") or course.get("shortname") or f"Curso {course_id}",
                            "section": section.get("name") or "Secao",
                            "title": module.get("name") or "Conteudo",
                            "description": module.get("description", "") or "",
                            "modname": module.get("modname", "recurso"),
                            "url": module.get("url") or "",
                        }
                    )

        self._contents_cache = (now, contents)
        return contents
