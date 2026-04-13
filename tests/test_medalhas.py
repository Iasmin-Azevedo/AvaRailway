"""Testes do fluxo de medalhas e dashboard completo do professor."""

import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_medalhas.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("MOODLE_URL", "https://moodle.local")
os.environ.setdefault("MOODLE_TOKEN", "test-token")
os.environ["CHAT_USE_LANGCHAIN"] = "false"
os.environ["CHAT_NLU_PROVIDER"] = "local"
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:9"

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.security import criar_token_acesso
from app.main import app, seed_default_medal_types, seed_default_users
from app.models.aluno import Aluno
from app.models.gestao import Escola, Turma
from app.models.medalhas import AlunoMedalha, MedalhaTipo, ProfessorMedalhaEnvio
from app.models.relacoes import ProfessorTurma
from app.models.user import UserRole, Usuario
from app.repositories.user_repository import UserRepository
from app.schemas.user_schema import UserCreate
from app.services.medalha_service import MedalhaService


class MedalhasFlowTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        seed_default_users()
        seed_default_medal_types()
        cls._seed_base_relations()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        engine.dispose()

    @classmethod
    def _seed_base_relations(cls):
        db = SessionLocal()
        try:
            repo = UserRepository()
            professor = db.query(Usuario).filter(Usuario.email == "professor@avamj.com").one()

            escola = Escola(nome="Escola Medalhas", ativo=True, endereco="Rua Medalha")
            db.add(escola)
            db.commit()
            db.refresh(escola)

            turma = Turma(nome="Turma Medalhas", ano_escolar=5, escola_id=escola.id, ano_letivo="2026")
            turma_extra = Turma(nome="Turma Fora Escopo", ano_escolar=5, escola_id=escola.id, ano_letivo="2026")
            db.add_all([turma, turma_extra])
            db.commit()
            db.refresh(turma)
            db.refresh(turma_extra)

            if not db.query(ProfessorTurma).filter_by(professor_id=professor.id, turma_id=turma.id).first():
                db.add(ProfessorTurma(professor_id=professor.id, turma_id=turma.id))
                db.commit()

            aluno_a_user = repo.get_by_email(db, "aluno_a@avamj.com")
            if not aluno_a_user:
                aluno_a_user = repo.create(
                    db,
                    UserCreate(
                        nome="Aluno A Medalhas",
                        email="aluno_a@avamj.com",
                        senha="123456",
                        role=UserRole.ALUNO,
                    ),
                )
            aluno_b_user = repo.get_by_email(db, "aluno_b@avamj.com")
            if not aluno_b_user:
                aluno_b_user = repo.create(
                    db,
                    UserCreate(
                        nome="Aluno B Medalhas",
                        email="aluno_b@avamj.com",
                        senha="123456",
                        role=UserRole.ALUNO,
                    ),
                )
            aluno_fora_user = repo.get_by_email(db, "aluno_fora@avamj.com")
            if not aluno_fora_user:
                aluno_fora_user = repo.create(
                    db,
                    UserCreate(
                        nome="Aluno Fora Escopo",
                        email="aluno_fora@avamj.com",
                        senha="123456",
                        role=UserRole.ALUNO,
                    ),
                )

            for user_id, turma_id in (
                (aluno_a_user.id, turma.id),
                (aluno_b_user.id, turma.id),
                (aluno_fora_user.id, turma_extra.id),
            ):
                row = db.query(Aluno).filter(Aluno.usuario_id == user_id).one_or_none()
                if not row:
                    db.add(Aluno(usuario_id=user_id, turma_id=turma_id, ano_escolar=5, nivel_risco="BAIXO"))
                else:
                    row.turma_id = turma_id
            db.commit()

            cls.professor_id = professor.id
            cls.turma_id = turma.id
            cls.turma_extra_id = turma_extra.id
            cls.aluno_a_id = db.query(Aluno).filter(Aluno.usuario_id == aluno_a_user.id).one().id
            cls.aluno_fora_id = db.query(Aluno).filter(Aluno.usuario_id == aluno_fora_user.id).one().id
        finally:
            db.close()

    def setUp(self):
        db = SessionLocal()
        try:
            db.query(AlunoMedalha).delete()
            db.query(ProfessorMedalhaEnvio).delete()
            db.commit()
        finally:
            db.close()

    def _first_medalha_tipo_id(self) -> int:
        db = SessionLocal()
        try:
            tipo = db.query(MedalhaTipo).filter(MedalhaTipo.ativo.is_(True)).order_by(MedalhaTipo.ordem).first()
            return tipo.id
        finally:
            db.close()

    def test_enviar_medalha_para_turma(self):
        db = SessionLocal()
        try:
            ok, msg, total = MedalhaService().enviar_medalha(
                db,
                professor_usuario_id=self.professor_id,
                medalha_tipo_id=self._first_medalha_tipo_id(),
                turma_ids_alvo=[self.turma_id],
                aluno_id=None,
                mensagem="Parabéns turma!",
            )
            self.assertTrue(ok)
            self.assertEqual(msg, "")
            self.assertEqual(total, 2)
            qtd = db.query(AlunoMedalha).count()
            self.assertEqual(qtd, 2)
        finally:
            db.close()

    def test_enviar_medalha_individual_fora_do_escopo_falha(self):
        db = SessionLocal()
        try:
            ok, msg, total = MedalhaService().enviar_medalha(
                db,
                professor_usuario_id=self.professor_id,
                medalha_tipo_id=self._first_medalha_tipo_id(),
                turma_ids_alvo=[self.turma_id],
                aluno_id=self.aluno_fora_id,
                mensagem="Tentativa fora do escopo",
            )
            self.assertFalse(ok)
            self.assertIn("Nenhum aluno elegível", msg)
            self.assertEqual(total, 0)
        finally:
            db.close()

    def test_dashboard_resumo_e_mural_aluno(self):
        db = SessionLocal()
        try:
            svc = MedalhaService()
            ok, _msg, _total = svc.enviar_medalha(
                db,
                professor_usuario_id=self.professor_id,
                medalha_tipo_id=self._first_medalha_tipo_id(),
                turma_ids_alvo=[self.turma_id],
                aluno_id=None,
                mensagem="Ótima participação",
            )
            self.assertTrue(ok)
            resumo = svc.dashboard_completo_professor(
                db, professor_usuario_id=self.professor_id, turma_ids=[self.turma_id]
            )
            self.assertEqual(resumo["totais"]["envios"], 1)
            self.assertEqual(resumo["totais"]["medalhas"], 2)
            self.assertGreaterEqual(len(resumo["ranking_alunos"]), 1)

            mural = svc.list_mural_aluno(db, self.aluno_a_id, limit=6)
            self.assertGreaterEqual(len(mural), 1)
        finally:
            db.close()

    def test_rotas_dashboard_completo_e_envio(self):
        token = criar_token_acesso({"sub": "professor@avamj.com"})
        self.client.cookies.set(settings.ACCESS_COOKIE_NAME, token)

        resp_page = self.client.get(f"/professor/dashboard-completo?turma_id={self.turma_id}")
        self.assertEqual(resp_page.status_code, 200)
        self.assertIn("Dashboard Completo", resp_page.text)

        resp_send = self.client.post(
            f"/professor/medalhas/enviar?turma_id={self.turma_id}",
            data={
                "medalha_tipo_id": str(self._first_medalha_tipo_id()),
                "alvo": "aluno",
                "aluno_id": str(self.aluno_a_id),
                "mensagem": "Destaque individual",
            },
            follow_redirects=False,
        )
        self.assertEqual(resp_send.status_code, 303)
        self.assertIn("ok=medalha_", resp_send.headers.get("location", ""))


if __name__ == "__main__":
    unittest.main()
