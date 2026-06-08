import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_licitacao_modules.db")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("MOODLE_URL", "https://moodle.local")
os.environ.setdefault("MOODLE_TOKEN", "test-token")
os.environ["CHAT_USE_LANGCHAIN"] = "false"
os.environ["CHAT_NLU_PROVIDER"] = "local"
os.environ["OLLAMA_BASE_URL"] = "http://127.0.0.1:9"

from app.core.database import Base, SessionLocal, engine
from app.main import seed_default_users
from app.models.aluno import Aluno
from app.models.avaliacao import OrigemBancoQuestao
from app.models.formacao import PapelParticipanteFormacao, StatusParticipacaoFormacao, TipoRecursoFormacao
from app.models.gestao import Escola, Trilha, Turma, Curso
from app.models.relacoes import CoordenadorEscola, GestorEscola, ProfessorTurma
from app.models.user import AdminScope, TeacherRole, UserRole, Usuario
from app.services.avaliacao_service import AvaliacaoService
from app.services.formacao_service import FormacaoService


class LicitacaoModulesTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        seed_default_users()
        cls._seed_base()

    @classmethod
    def tearDownClass(cls):
        engine.dispose()

    @classmethod
    def _seed_base(cls):
        db = SessionLocal()
        try:
            admin = db.query(Usuario).filter(Usuario.email == "admin@avajmj.com").one()
            professor = db.query(Usuario).filter(Usuario.email == "professor@avamj.com").one()
            gestor = db.query(Usuario).filter(Usuario.email == "gestor@avamj.com").one()
            coordenador = db.query(Usuario).filter(Usuario.email == "coordenador@avamj.com").one()
            admin.escopo_administrativo = AdminScope.SECRETARIA_SME
            professor.funcao_docente = TeacherRole.PDT

            escola = Escola(nome="Escola Licitacao", ativo=True, endereco="Rua Lic")
            db.add(escola)
            db.commit()
            db.refresh(escola)

            turma = Turma(nome="Turma Lic", ano_escolar=5, escola_id=escola.id, ano_letivo="2026")
            db.add(turma)
            db.commit()
            db.refresh(turma)

            if not db.query(ProfessorTurma).filter_by(professor_id=professor.id, turma_id=turma.id).first():
                db.add(ProfessorTurma(professor_id=professor.id, turma_id=turma.id))
            if not db.query(GestorEscola).filter_by(gestor_id=gestor.id, escola_id=escola.id).first():
                db.add(GestorEscola(gestor_id=gestor.id, escola_id=escola.id))
            if not db.query(CoordenadorEscola).filter_by(coordenador_id=coordenador.id).first():
                db.add(CoordenadorEscola(coordenador_id=coordenador.id, escola_id=escola.id))

            aluno_user = Usuario(nome="Aluno Lic", email="aluno_licitacao@avamj.com", senha_hash="x", role=UserRole.ALUNO, ativo=True)
            db.add(aluno_user)
            db.commit()
            db.refresh(aluno_user)
            db.add(Aluno(usuario_id=aluno_user.id, turma_id=turma.id, ano_escolar=5, nivel_risco="BAIXO"))

            curso = Curso(nome="BNCC Computação")
            db.add(curso)
            db.commit()
            db.refresh(curso)
            trilha = Trilha(nome="Trilha BNCC 1", curso_id=curso.id, ano_escolar=None, ordem=1)
            db.add(trilha)
            db.commit()
            db.refresh(trilha)
            db.commit()

            cls.admin_id = admin.id
            cls.professor_id = professor.id
            cls.gestor_id = gestor.id
            cls.coordenador_id = coordenador.id
            cls.escola_id = escola.id
            cls.turma_id = turma.id
            cls.trilha_id = trilha.id
            cls.aluno_email = aluno_user.email
        finally:
            db.commit()
            db.close()

    def test_fluxo_desempenho_turma_escola_rede(self):
        db = SessionLocal()
        try:
            svc = AvaliacaoService()
            banco_q1 = svc.criar_banco_questao(
                db,
                autor_usuario_id=self.professor_id,
                curso_id=None,
                ano_escolar=5,
                descritor_id=None,
                conteudo="Leitura",
                tipo_questao="multipla_escolha",
                enunciado="Pergunta 1",
                gabarito="A",
                alternativa_a="A",
                alternativa_b="B",
                alternativa_c="C",
                alternativa_d="D",
                alternativa_e="E",
                origem=OrigemBancoQuestao.MANUAL,
                habilidade_saeb="D01",
                codigo_referencia="BQ1",
            )
            banco_q2 = svc.criar_banco_questao(
                db,
                autor_usuario_id=self.professor_id,
                curso_id=None,
                ano_escolar=5,
                descritor_id=None,
                conteudo="Leitura",
                tipo_questao="multipla_escolha",
                enunciado="Pergunta 2",
                gabarito="B",
                alternativa_a="A",
                alternativa_b="B",
                alternativa_c="C",
                alternativa_d="D",
                alternativa_e="E",
                origem=OrigemBancoQuestao.MANUAL,
                habilidade_saeb="D02",
                codigo_referencia="BQ2",
            )
            avaliacao = svc.criar_avaliacao_objetiva(
                db,
                titulo="Avaliação Diagnóstica 5º Ano",
                descricao="Teste de desempenho",
                codigo="AD-2026-01",
                ano_letivo="2026",
                ano_escolar=5,
                criado_por_usuario_id=self.professor_id,
            )
            q1 = svc.anexar_questao_banco(db, avaliacao_id=avaliacao.id, banco_questao_id=banco_q1.id, numero=1)
            _q2 = svc.anexar_questao_banco(db, avaliacao_id=avaliacao.id, banco_questao_id=banco_q2.id, numero=2)
            aplicacao = svc.criar_aplicacao_prova(
                db,
                avaliacao_id=avaliacao.id,
                titulo="Aplicação Turma Lic",
                escopo="turma",
                turma_id=self.turma_id,
                ano_letivo="2026",
                periodo_referencia="1º bimestre",
                criado_por_usuario_id=self.professor_id,
            )
            csv_payload = (
                f"aluno_email;questao_codigo;resposta_marcada\n"
                f"{self.aluno_email};{q1.codigo};A\n"
                f"{self.aluno_email};BQ2;C\n"
            ).encode("utf-8")
            resultado = svc.importar_respostas_csv(
                db,
                aplicacao_id=aplicacao.id,
                csv_bytes=csv_payload,
                arquivo_nome="importacao.csv",
                criado_por_usuario_id=self.admin_id,
            )
            self.assertEqual(resultado["linhas_processadas"], 2)
            resumo = svc.resumo_avaliacao_objetiva(db, avaliacao.id, aplicacao.id)
            self.assertEqual(resumo["total_respostas"], 2)
            self.assertEqual(resumo["total_acertos"], 1)
            self.assertAlmostEqual(resumo["nota_geral"], 5.0, places=1)
            self.assertEqual(len(resumo["por_turma"]), 1)
            consolidado = svc.consolidado_desempenho(db, turma_ids=[self.turma_id], aplicacao_id=aplicacao.id)
            self.assertEqual(consolidado["por_turma"][0]["turma"], "Turma Lic")
            self.assertAlmostEqual(consolidado["por_turma"][0]["nota_media"], 5.0, places=1)
        finally:
            db.close()

    def test_mapa_migracao_e_fontes_externas(self):
        db = SessionLocal()
        try:
            svc = AvaliacaoService()
            mapa = svc.mapa_migracao_legado()
            fontes = svc.estrategia_fontes_externas()
            self.assertTrue(any(item["nome"] == "BancoQuestao" for item in mapa["adaptar"]))
            self.assertTrue(any(item["nome"] == "AplicacaoAvaliacaoInstitucional" for item in mapa["aposentar"]))
            self.assertEqual(fontes["fonte_oficial"], "Banco local do AVA MJ")
            self.assertTrue(any("INEP/SAEB" in item for item in fontes["fontes_complementares"]))
        finally:
            db.close()

    def test_formacao_bncc_status_conclusao(self):
        db = SessionLocal()
        try:
            svc = FormacaoService()
            programa = svc.criar_programa(
                db,
                nome="Formação BNCC Teste",
                descricao="Programa teste",
                publico_alvo="Professores",
            )
            svc.vincular_recurso(
                db,
                programa_id=programa.id,
                tipo_recurso=TipoRecursoFormacao.TRILHA_H5P,
                titulo="Trilha BNCC 1",
                trilha_id=self.trilha_id,
            )
            turma = svc.criar_turma(
                db,
                programa_id=programa.id,
                nome="Turma BNCC A",
                escola_id=self.escola_id,
            )
            participante = svc.inscrever_participante(
                db,
                turma_id=turma.id,
                usuario_id=self.professor_id,
                papel_participante=PapelParticipanteFormacao.PROFESSOR,
            )
            atualizado = svc.atualizar_progresso_participante(
                db,
                participante_id=participante.id,
                carga_horaria_remota_realizada=40,
                carga_horaria_presencial_realizada=40,
                devolutiva="Concluiu com exito.",
            )
            self.assertEqual(str(atualizado.status.value), StatusParticipacaoFormacao.CONCLUIDO.value)
            self.assertTrue(atualizado.certificado_emitido)
        finally:
            db.close()
