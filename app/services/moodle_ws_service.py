"""Cliente mínimo do webservice Moodle (JSON)."""

from __future__ import annotations

import logging
from typing import Any

import requests

from app.core.config import settings

logger = logging.getLogger("ava_mj_backend.moodle_ws")


class MoodleWsService:
    def list_user_courses(self, moodle_user_id: int, timeout: int = 12) -> list[dict[str, Any]]:
        base = (settings.MOODLE_URL or "").rstrip("/")
        token = (settings.MOODLE_TOKEN or "").strip()
        if not base or not token:
            raise RuntimeError("MOODLE_URL ou MOODLE_TOKEN não configurados")

        url = f"{base}/webservice/rest/server.php"
        params = {
            "wstoken": token,
            "wsfunction": "core_enrol_get_users_courses",
            "moodlewsrestformat": "json",
            "userid": moodle_user_id,
        }
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            logger.warning("Falha Moodle WS: %s", exc)
            raise

        if isinstance(data, dict) and data.get("exception"):
            logger.warning("Moodle retornou erro: %s", data.get("message"))
            raise RuntimeError("Resposta de erro do Moodle")

        if not isinstance(data, list):
            return []

        out: list[dict[str, Any]] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            cid = row.get("id")
            if cid is None:
                continue
            out.append(
                {
                    "id": int(cid),
                    "fullname": (row.get("fullname") or row.get("shortname") or f"Curso {cid}")[:200],
                    "shortname": (row.get("shortname") or "")[:80],
                }
            )
        return out
