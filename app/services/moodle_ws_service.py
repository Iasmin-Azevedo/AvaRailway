"""Cliente mínimo do webservice Moodle (JSON)."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

import requests

from app.core.config import settings

logger = logging.getLogger("ava_mj_backend.moodle_ws")

# Curso “site” padrão do Moodle (página inicial); normalmente não é formação.
MOODLE_SITE_COURSE_ID_SKIP = 1


class MoodleWsService:
    @staticmethod
    def _extract_course_image_url(row: dict[str, Any], base_url: str) -> str | None:
        direct = (row.get("courseimage") or "").strip()
        if direct:
            if direct.startswith("http://") or direct.startswith("https://"):
                return direct
            if direct.startswith("/"):
                return f"{base_url}{direct}"
            return f"{base_url}/{direct}"

        overview = row.get("overviewfiles")
        if not isinstance(overview, list):
            return None
        for item in overview:
            if not isinstance(item, dict):
                continue
            file_url = (item.get("fileurl") or "").strip()
            if not file_url:
                continue
            if file_url.startswith("http://") or file_url.startswith("https://"):
                return file_url
            if file_url.startswith("/"):
                return f"{base_url}{file_url}"
            return f"{base_url}/{file_url}"
        return None

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

    def _rest_get(self, wsfunction: str, extra_params: dict[str, Any], timeout: int = 30) -> Any:
        base = (settings.MOODLE_URL or "").rstrip("/")
        token = (settings.MOODLE_TOKEN or "").strip()
        if not base or not token:
            raise RuntimeError("MOODLE_URL ou MOODLE_TOKEN não configurados")
        url = f"{base}/webservice/rest/server.php"
        params: dict[str, Any] = {
            "wstoken": token,
            "wsfunction": wsfunction,
            "moodlewsrestformat": "json",
        }
        params.update(extra_params)
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and data.get("exception"):
            logger.warning("Moodle retornou erro (%s): %s", wsfunction, data.get("message"))
            raise RuntimeError(data.get("message") or "Resposta de erro do Moodle")
        return data

    @staticmethod
    def _with_ws_token(url: str, token: str) -> str:
        parsed = urlsplit(url)
        q = dict(parse_qsl(parsed.query, keep_blank_values=True))
        q["token"] = token
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(q), parsed.fragment))

    @staticmethod
    def _to_webservice_pluginfile(url: str, base_url: str) -> str:
        parsed = urlsplit(url)
        base = urlsplit(base_url)
        if parsed.netloc and base.netloc and parsed.netloc != base.netloc:
            return url
        path = parsed.path or ""
        if "/webservice/pluginfile.php/" in path:
            return url
        if "/pluginfile.php/" in path:
            path = path.replace("/pluginfile.php/", "/webservice/pluginfile.php/", 1)
        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment))

    def fetch_file_content(
        self, file_url: str, timeout: int = 20
    ) -> tuple[bytes, str]:
        base = (settings.MOODLE_URL or "").rstrip("/")
        token = (settings.MOODLE_TOKEN or "").strip()
        if not base or not token:
            raise RuntimeError("MOODLE_URL ou MOODLE_TOKEN não configurados")
        raw = (file_url or "").strip()
        if not raw:
            raise RuntimeError("URL de arquivo Moodle ausente")
        if raw.startswith("/"):
            raw = f"{base}{raw}"
        elif not raw.startswith("http://") and not raw.startswith("https://"):
            raw = f"{base}/{raw.lstrip('/')}"
        candidates = [
            self._with_ws_token(raw, token),
            self._with_ws_token(self._to_webservice_pluginfile(raw, base), token),
        ]
        tried: set[str] = set()
        last_exc: Exception | None = None
        for candidate in candidates:
            if candidate in tried:
                continue
            tried.add(candidate)
            try:
                resp = requests.get(candidate, timeout=timeout, allow_redirects=True)
                resp.raise_for_status()
                ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                if not ctype.startswith("image/"):
                    continue
                if not resp.content:
                    continue
                return resp.content, ctype
            except Exception as exc:
                last_exc = exc
                continue
        if last_exc:
            raise last_exc
        raise RuntimeError("Resposta do Moodle não retornou imagem válida")

    def _augment_images_from_courses_by_field(self, rows: list[dict[str, Any]]) -> None:
        ids = [r["moodle_course_id"] for r in rows if r.get("moodle_course_id")]
        if not ids:
            return
        base = (settings.MOODLE_URL or "").rstrip("/")
        chunks = [ids[i : i + 50] for i in range(0, len(ids), 50)]
        id_to_image: dict[int, str] = {}
        for chunk in chunks:
            data = self._rest_get(
                "core_course_get_courses_by_field",
                {"field": "ids", "value": ",".join(str(cid) for cid in chunk)},
                timeout=30,
            )
            courses = data.get("courses", []) if isinstance(data, dict) else []
            for c in courses:
                if not isinstance(c, dict):
                    continue
                cid = c.get("id")
                if cid is None:
                    continue
                img = self._extract_course_image_url(c, base)
                if img:
                    id_to_image[int(cid)] = img
        if not id_to_image:
            return
        for row in rows:
            cid = row.get("moodle_course_id")
            if cid in id_to_image:
                row["image_url"] = id_to_image[cid]

    def fetch_courses_for_catalog(self, timeout: int = 45) -> list[dict[str, Any]]:
        """
        Lista cursos visíveis ao token (core_course_get_courses).
        Exclui o curso site padrão (id=1).
        """
        base = (settings.MOODLE_URL or "").rstrip("/")
        data = self._rest_get("core_course_get_courses", {}, timeout=timeout)
        if not isinstance(data, list):
            return []
        out: list[dict[str, Any]] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            cid = row.get("id")
            if cid is None:
                continue
            cid_int = int(cid)
            if cid_int == MOODLE_SITE_COURSE_ID_SKIP:
                continue
            vis = row.get("visible")
            visible = True if vis is None else bool(int(vis)) if str(vis).isdigit() else bool(vis)
            cat = row.get("categoryid")
            out.append(
                {
                    "moodle_course_id": cid_int,
                    "fullname": (row.get("fullname") or row.get("shortname") or f"Curso {cid_int}")[:255],
                    "shortname": (row.get("shortname") or "")[:100],
                    "image_url": self._extract_course_image_url(row, base),
                    "category_id": int(cat) if cat is not None and str(cat).lstrip("-").isdigit() else None,
                    "visible": visible,
                }
            )
        # Fallback: algumas instalações não retornam imagem em core_course_get_courses.
        # Quando permitido no token/serviço, tentamos completar via get_courses_by_field.
        if out and not any(r.get("image_url") for r in out):
            try:
                self._augment_images_from_courses_by_field(out)
            except Exception as exc:
                logger.info("Sem acesso a imagens via core_course_get_courses_by_field: %s", exc)
        return out

    def try_enrol_user_as_student(
        self,
        moodle_course_id: int,
        moodle_user_id: int,
        role_id: int | None = None,
        timeout: int = 20,
    ) -> bool:
        """
        Inscrição manual como aluno. Não lança se o Moodle recusar (ex.: já inscrito);
        regista em log e devolve False.
        """
        rid = role_id if role_id is not None else settings.MOODLE_STUDENT_ROLE_ID
        params = {
            "enrolments[0][roleid]": rid,
            "enrolments[0][userid]": moodle_user_id,
            "enrolments[0][courseid]": moodle_course_id,
            "enrolments[0][timestart]": 0,
            "enrolments[0][timeend]": 0,
            "enrolments[0][suspend]": 0,
        }
        try:
            data = self._rest_get("enrol_manual_enrol_users", params, timeout=timeout)
            if data is None:
                return True
            if data == [] or data == {}:
                return True
            if isinstance(data, dict) and data.get("exception"):
                logger.info(
                    "Moodle enrol_manual (curso=%s user=%s): %s",
                    moodle_course_id,
                    moodle_user_id,
                    data.get("message"),
                )
                return False
            return True
        except Exception as exc:
            logger.warning(
                "Falha enrol_manual_enrol_users curso=%s moodle_user=%s: %s",
                moodle_course_id,
                moodle_user_id,
                exc,
            )
            return False
