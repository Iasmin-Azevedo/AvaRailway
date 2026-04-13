"""Testes do catálogo Moodle e atribuições pelo gestor (serviço + WS mockado)."""

import os
import unittest
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_moodle_assignment.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("MOODLE_URL", "https://moodle.local")
os.environ.setdefault("MOODLE_TOKEN", "test-token")
os.environ.setdefault("MOODLE_AUTO_ENROL_ON_ASSIGN", "false")
os.environ["CHAT_USE_LANGCHAIN"] = "false"
os.environ["CHAT_NLU_PROVIDER"] = "local"
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:9"

from app.core.database import Base, SessionLocal, engine
from app.main import seed_default_users
from app.models.gestao import Escola, Turma
from app.models.moodle_gestao import GestorProfessorMoodleCourse, MoodleCourseCatalog
from app.models.relacoes import GestorEscola, ProfessorTurma
from app.models.user import UserRole, Usuario
from app.repositories.user_repository import UserRepository
from app.schemas.user_schema import UserCreate
from app.core.config import settings
from app.services import moodle_assignment_service as mas
from app.services.moodle_ws_service import MoodleWsService


class MoodleAssignmentServiceTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        seed_default_users()
        cls._seed_escolas_e_vinculos()

    @classmethod
    def tearDownClass(cls):
        engine.dispose()

    @classmethod
    def _seed_escolas_e_vinculos(cls):
        db = SessionLocal()
        try:
            escola_a = Escola(nome="Escola A Moodle", ativo=True, endereco="Rua A")
            escola_b = Escola(nome="Escola B Moodle", ativo=True, endereco="Rua B")
            db.add_all([escola_a, escola_b])
            db.commit()
            db.refresh(escola_a)
            db.refresh(escola_b)

            turma_a = Turma(nome="Turma A", ano_escolar=5, escola_id=escola_a.id, ano_letivo="2026")
            turma_b = Turma(nome="Turma B", ano_escolar=5, escola_id=escola_b.id, ano_letivo="2026")
            db.add_all([turma_a, turma_b])
            db.commit()
            db.refresh(turma_a)
            db.refresh(turma_b)

            professor = db.query(Usuario).filter(Usuario.email == "professor@avamj.com").one()
            gestor = db.query(Usuario).filter(Usuario.email == "gestor@avamj.com").one()

            repo = UserRepository()
            prof_b = repo.get_by_email(db, "professor_b@avamj.com")
            if not prof_b:
                prof_b = repo.create(
                    db,
                    UserCreate(
                        nome="Professor Só B",
                        email="professor_b@avamj.com",
                        senha="123456",
                        role=UserRole.PROFESSOR,
                    ),
                )

            if not db.query(ProfessorTurma).filter_by(professor_id=professor.id, turma_id=turma_a.id).first():
                db.add(ProfessorTurma(professor_id=professor.id, turma_id=turma_a.id))
            if not db.query(ProfessorTurma).filter_by(professor_id=prof_b.id, turma_id=turma_b.id).first():
                db.add(ProfessorTurma(professor_id=prof_b.id, turma_id=turma_b.id))

            if not db.query(GestorEscola).filter_by(gestor_id=gestor.id, escola_id=escola_a.id).first():
                db.add(GestorEscola(gestor_id=gestor.id, escola_id=escola_a.id))

            db.commit()

            cls._escola_a_id = escola_a.id
            cls._escola_b_id = escola_b.id
            cls._gestor_id = gestor.id
            cls._professor_a_id = professor.id
            cls._professor_b_id = prof_b.id
            cls._course_moodle_id = 42
        finally:
            db.close()

    def setUp(self):
        db = SessionLocal()
        try:
            db.query(GestorProfessorMoodleCourse).delete()
            db.query(MoodleCourseCatalog).delete()
            db.commit()
        finally:
            db.close()

    def _catalog_row(self, db, mid: int | None = None):
        mid = mid or self._course_moodle_id
        row = MoodleCourseCatalog(
            moodle_course_id=mid,
            fullname="Curso teste",
            shortname="CT",
            image_url="https://moodle.local/pluginfile.php/10/course/overviewfiles/capa.png",
            category_id=1,
            visible=True,
        )
        db.add(row)
        db.commit()
        return row

    @patch.object(MoodleWsService, "fetch_courses_for_catalog")
    def test_sync_catalog_upserts(self, mock_fetch):
        mock_fetch.return_value = [
            {
                "moodle_course_id": 10,
                "fullname": "Um",
                "shortname": "u1",
                "image_url": "https://moodle.local/pluginfile.php/10/course/overviewfiles/banner.png",
                "category_id": 2,
                "visible": True,
            },
            {
                "moodle_course_id": 11,
                "fullname": "Dois",
                "shortname": "d2",
                "category_id": None,
                "visible": False,
            },
        ]
        db = SessionLocal()
        try:
            n, err = mas.sync_catalog_from_moodle(db)
            self.assertIsNone(err)
            self.assertEqual(n, 2)
            c10 = db.query(MoodleCourseCatalog).filter_by(moodle_course_id=10).one()
            self.assertEqual(c10.fullname, "Um")
            self.assertIn("pluginfile.php", c10.image_url or "")
            mock_fetch.return_value = [
                {
                    "moodle_course_id": 10,
                    "fullname": "Um atualizado",
                    "shortname": "u1",
                    "image_url": "https://moodle.local/pluginfile.php/10/course/overviewfiles/banner-v2.png",
                    "category_id": 2,
                    "visible": True,
                },
            ]
            n2, err2 = mas.sync_catalog_from_moodle(db)
            self.assertIsNone(err2)
            self.assertEqual(n2, 1)
            db.refresh(c10)
            self.assertEqual(c10.fullname, "Um atualizado")
            self.assertIn("banner-v2", c10.image_url or "")
        finally:
            db.close()

    @patch.object(MoodleWsService, "fetch_courses_for_catalog", side_effect=RuntimeError("timeout"))
    def test_sync_catalog_returns_error_on_ws_failure(self, _mock):
        db = SessionLocal()
        try:
            n, err = mas.sync_catalog_from_moodle(db)
            self.assertEqual(n, 0)
            self.assertIn("timeout", err or "")
        finally:
            db.close()

    def test_catalog_never_synced(self):
        db = SessionLocal()
        try:
            self.assertTrue(mas.catalog_never_synced(db))
            self._catalog_row(db)
            self.assertFalse(mas.catalog_never_synced(db))
        finally:
            db.close()

    def test_create_assignment_requires_catalog(self):
        db = SessionLocal()
        try:
            gestor = db.get(Usuario, self._gestor_id)
            ok, msg = mas.create_assignment(
                db,
                gestor=gestor,
                professor_usuario_id=self._professor_a_id,
                moodle_course_id=99,
            )
            self.assertFalse(ok)
            self.assertIn("catálogo", msg.lower())
        finally:
            db.close()

    def test_create_assignment_out_of_scope_professor(self):
        db = SessionLocal()
        try:
            self._catalog_row(db)
            gestor = db.get(Usuario, self._gestor_id)
            ok, msg = mas.create_assignment(
                db,
                gestor=gestor,
                professor_usuario_id=self._professor_b_id,
                moodle_course_id=self._course_moodle_id,
            )
            self.assertFalse(ok)
            self.assertIn("âmbito", msg.lower())
        finally:
            db.close()

    def test_create_list_revoke_flow(self):
        db = SessionLocal()
        try:
            self._catalog_row(db)
            gestor = db.get(Usuario, self._gestor_id)
            ok, msg = mas.create_assignment(
                db,
                gestor=gestor,
                professor_usuario_id=self._professor_a_id,
                moodle_course_id=self._course_moodle_id,
            )
            self.assertTrue(ok)
            self.assertEqual(msg, "")

            listed = mas.list_assignments_for_professor(db, self._professor_a_id)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["id"], self._course_moodle_id)
            self.assertEqual(listed[0]["fullname"], "Curso teste")
            self.assertIn("pluginfile.php", listed[0]["image_url"])

            ok2, msg2 = mas.create_assignment(
                db,
                gestor=gestor,
                professor_usuario_id=self._professor_a_id,
                moodle_course_id=self._course_moodle_id,
            )
            self.assertFalse(ok2)
            self.assertIn("já existe", msg2.lower())

            asg = db.query(GestorProfessorMoodleCourse).one()
            ok3, msg3 = mas.revoke_assignment(db, gestor=gestor, assignment_id=asg.id)
            self.assertTrue(ok3)
            self.assertEqual(len(mas.list_assignments_for_professor(db, self._professor_a_id)), 0)

            ok4, _ = mas.create_assignment(
                db,
                gestor=gestor,
                professor_usuario_id=self._professor_a_id,
                moodle_course_id=self._course_moodle_id,
            )
            self.assertTrue(ok4)
            self.assertEqual(len(mas.list_assignments_for_professor(db, self._professor_a_id)), 1)
        finally:
            db.close()

    @patch.object(MoodleWsService, "try_enrol_user_as_student")
    def test_auto_enrol_called_when_enabled(self, mock_enrol):
        prev = settings.MOODLE_AUTO_ENROL_ON_ASSIGN
        db = SessionLocal()
        try:
            settings.MOODLE_AUTO_ENROL_ON_ASSIGN = True
            self._catalog_row(db)
            prof = db.get(Usuario, self._professor_a_id)
            prof.moodle_user_id = "777"
            db.commit()

            gestor = db.get(Usuario, self._gestor_id)
            ok, _ = mas.create_assignment(
                db,
                gestor=gestor,
                professor_usuario_id=self._professor_a_id,
                moodle_course_id=self._course_moodle_id,
            )
            self.assertTrue(ok)
            mock_enrol.assert_called_once()
            args, _kwargs = mock_enrol.call_args
            self.assertEqual(args[0], self._course_moodle_id)
            self.assertEqual(args[1], 777)
        finally:
            settings.MOODLE_AUTO_ENROL_ON_ASSIGN = prev
            db.close()

    def test_moodle_file_url_receives_token(self):
        url = "https://moodle.local/pluginfile.php/10/course/overviewfiles/capa.png?forcedownload=1"
        signed = MoodleWsService._with_ws_token(url, "abc123")
        parsed = urlparse(signed)
        q = parse_qs(parsed.query)
        self.assertEqual(q.get("forcedownload"), ["1"])
        self.assertEqual(q.get("token"), ["abc123"])


if __name__ == "__main__":
    unittest.main()
