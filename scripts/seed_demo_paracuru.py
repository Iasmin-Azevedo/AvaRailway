#!/usr/bin/env python3
"""Popula dados de demonstração PoC Paracuru (idempotente).

Uso (na raiz do projeto):
  python scripts/seed_demo_paracuru.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import SessionLocal
from app.main import seed_default_courses, seed_default_users
from app.models.aluno import Aluno
from app.models.avaliacao import OrigemBancoQuestao
from app.models.formacao import PapelParticipanteFormacao, StatusParticipacaoFormacao, TipoRecursoFormacao
from app.models.gestao import Curso, Escola, Trilha, Turma
from app.models.relacoes import CoordenadorEscola, GestorEscola, ProfessorTurma
from app.models.user import AdminScope, TeacherRole, UserRole, Usuario
from app.repositories.user_repository import UserRepository
from app.schemas.user_schema import UserCreate
from app.services.avaliacao_institucional_service import AvaliacaoInstitucionalService
from app.services.avaliacao_service import AvaliacaoService
from app.services.formacao_service import FormacaoService

ESCOLA_NOME = "EMEF PoC Paracuru"
TURMA_NOME = "5º Ano A — PoC"
AVALIACAO_CODIGO = "POC-PARACURU-2026"
APLICACAO_TITULO = "Prova inicial — PoC Paracuru"
PROGRAMA_BNCC = "Formação BNCC Computação — PoC Paracuru"
CICLO_SEMESTRAL = "Avaliação semestral 2026.1 — PoC"


def _get_or_create_user(db, *, nome: str, email: str, role: UserRole, **kwargs) -> Usuario:
    repo = UserRepository()
    u = repo.get_by_email(db, email)
    if u:
        repo.update(db, id=u.id, nome=nome, email=email, senha="123456", role=role, ativo=True, **kwargs)
        db.refresh(u)
        return u
    u = repo.create(
        db,
        UserCreate(nome=nome, email=email, senha="123456", role=role, **kwargs),
    )
    return u


def seed_paracuru() -> dict:
    seed_default_courses()
    seed_default_users()
    db = SessionLocal()
    summary: dict = {}
    try:
        admin = db.query(Usuario).filter(Usuario.email == "admin@avajmj.com").one()
        admin.escopo_administrativo = AdminScope.SECRETARIA_SME
        professor = db.query(Usuario).filter(Usuario.email == "professor@avamj.com").one()
        professor.funcao_docente = TeacherRole.PDT
        gestor = db.query(Usuario).filter(Usuario.email == "gestor@avamj.com").one()
        coordenador = db.query(Usuario).filter(Usuario.email == "coordenador@avamj.com").one()

        escola = db.query(Escola).filter(Escola.nome == ESCOLA_NOME).first()
        if not escola:
            escola = Escola(nome=ESCOLA_NOME, ativo=True, endereco="Paracuru — CE")
            db.add(escola)
            db.flush()
        summary["escola_id"] = escola.id

        turma = (
            db.query(Turma)
            .filter(Turma.nome == TURMA_NOME, Turma.escola_id == escola.id)
            .first()
        )
        if not turma:
            turma = Turma(nome=TURMA_NOME, ano_escolar=5, escola_id=escola.id, ano_letivo="2026")
            db.add(turma)
            db.flush()
        summary["turma_id"] = turma.id

        for rel, gid, eid in (
            (ProfessorTurma, professor.id, turma.id),
        ):
            if not db.query(rel).filter_by(professor_id=gid, turma_id=eid).first():
                db.add(rel(professor_id=gid, turma_id=eid))
        if not db.query(GestorEscola).filter_by(gestor_id=gestor.id, escola_id=escola.id).first():
            db.add(GestorEscola(gestor_id=gestor.id, escola_id=escola.id))
        ce = db.query(CoordenadorEscola).filter_by(coordenador_id=coordenador.id).first()
        if ce:
            ce.escola_id = escola.id
        else:
            db.add(CoordenadorEscola(coordenador_id=coordenador.id, escola_id=escola.id))

        alunos_demo = [
            ("Aluno Mj Connect Edu", "aluno@avamj.com"),
            ("Aluno PoC 2", "aluno_poc2@avamj.com"),
            ("Aluno PoC 3", "aluno_poc3@avamj.com"),
            ("Aluno PoC 4", "aluno_poc4@avamj.com"),
        ]
        aluno_ids: list[int] = []
        for nome, email in alunos_demo:
            u = _get_or_create_user(db, nome=nome, email=email, role=UserRole.ALUNO)
            aluno = db.query(Aluno).filter(Aluno.usuario_id == u.id).first()
            if not aluno:
                aluno = Aluno(usuario_id=u.id, turma_id=turma.id, ano_escolar=5, nivel_risco="BAIXO")
                db.add(aluno)
                db.flush()
            else:
                aluno.turma_id = turma.id
            aluno_ids.append(aluno.id)
        summary["alunos"] = len(aluno_ids)

        av_svc = AvaliacaoService()
        from app.models.avaliacao import Avaliacao

        avaliacao = db.query(Avaliacao).filter(Avaliacao.codigo == AVALIACAO_CODIGO).first()
        if not avaliacao:
            avaliacao = av_svc.criar_avaliacao_objetiva(
                db,
                titulo="Prova de Matemática — PoC Paracuru",
                descricao="Avaliação diagnóstica para demonstração",
                codigo=AVALIACAO_CODIGO,
                ano_letivo="2026",
                ano_escolar=5,
                criado_por_usuario_id=professor.id,
            )
            gabaritos = ["A", "B", "B", "B"]
            for i, g in enumerate(gabaritos, start=1):
                bq = av_svc.criar_banco_questao(
                    db,
                    autor_usuario_id=professor.id,
                    curso_id=None,
                    ano_escolar=5,
                    descritor_id=None,
                    conteudo="Matemática",
                    tipo_questao="multipla_escolha",
                    enunciado=f"Questão {i} — PoC",
                    gabarito=g,
                    alternativa_a="A",
                    alternativa_b="B",
                    alternativa_c="C",
                    alternativa_d="D",
                    alternativa_e="E",
                    origem=OrigemBancoQuestao.MANUAL,
                    habilidade_saeb=f"D0{i}",
                    codigo_referencia=f"POC-Q{i}",
                )
                av_svc.anexar_questao_banco(db, avaliacao_id=avaliacao.id, banco_questao_id=bq.id, numero=i)
        summary["avaliacao_id"] = avaliacao.id

        from app.models.avaliacao import AplicacaoProva

        aplicacao = (
            db.query(AplicacaoProva)
            .filter(AplicacaoProva.titulo == APLICACAO_TITULO, AplicacaoProva.avaliacao_id == avaliacao.id)
            .first()
        )
        if not aplicacao:
            aplicacao = av_svc.criar_aplicacao_prova(
                db,
                avaliacao_id=avaliacao.id,
                titulo=APLICACAO_TITULO,
                escopo="turma",
                turma_id=turma.id,
                ano_letivo="2026",
                periodo_referencia="1º bimestre",
                criado_por_usuario_id=professor.id,
            )
        summary["aplicacao_id"] = aplicacao.id

        from app.models.avaliacao import ParticipacaoAplicacaoProva

        participacoes = (
            db.query(ParticipacaoAplicacaoProva)
            .filter(ParticipacaoAplicacaoProva.aplicacao_id == aplicacao.id)
            .order_by(ParticipacaoAplicacaoProva.id.asc())
            .all()
        )
        summary["participacoes"] = [p.id for p in participacoes]

        if participacoes:
            from app.models.avaliacao import Questao

            questoes = (
                db.query(Questao)
                .filter(Questao.avaliacao_id == avaliacao.id)
                .order_by(Questao.numero.asc())
                .all()
            )
            linhas = ["aluno_email;questao_codigo;resposta_marcada"]
            for p in participacoes[:1]:
                aluno = db.query(Aluno).filter(Aluno.id == p.aluno_id).first()
                usuario = db.query(Usuario).filter(Usuario.id == aluno.usuario_id).first() if aluno else None
                if not usuario:
                    continue
                for q in questoes:
                    marcada = "B" if q.numero and q.numero > 1 else "B"
                    cod = q.codigo or f"POC-Q{q.numero}"
                    linhas.append(f"{usuario.email};{cod};{marcada}")
            if len(linhas) > 1:
                csv_body = "\n".join(linhas).encode("utf-8-sig")
                av_svc.importar_respostas_csv(
                    db,
                    aplicacao_id=aplicacao.id,
                    csv_bytes=csv_body,
                    arquivo_nome="seed_poc_paracuru.csv",
                    criado_por_usuario_id=admin.id,
                )
                summary["notas_importadas"] = True

        curso = db.query(Curso).filter(Curso.nome == "BNCC Computação").first()
        if not curso:
            curso = Curso(nome="BNCC Computação")
            db.add(curso)
            db.flush()
        trilha = db.query(Trilha).filter(Trilha.nome == "Trilha BNCC PoC").first()
        if not trilha:
            trilha = Trilha(nome="Trilha BNCC PoC", curso_id=curso.id, ordem=1)
            db.add(trilha)
            db.flush()

        form_svc = FormacaoService()
        from app.models.formacao import ProgramaFormacaoBNCC

        programa = db.query(ProgramaFormacaoBNCC).filter(ProgramaFormacaoBNCC.nome == PROGRAMA_BNCC).first()
        if not programa:
            programa = form_svc.criar_programa(
                db,
                nome=PROGRAMA_BNCC,
                descricao="Programa demonstração Paracuru",
                publico_alvo="Professores e gestores",
            )
            form_svc.vincular_recurso(
                db,
                programa_id=programa.id,
                tipo_recurso=TipoRecursoFormacao.TRILHA_H5P,
                titulo="Trilha BNCC PoC",
                trilha_id=trilha.id,
            )
            turma_bncc = form_svc.criar_turma(
                db,
                programa_id=programa.id,
                nome="Turma BNCC PoC",
                escola_id=escola.id,
            )
            participante = form_svc.inscrever_participante(
                db,
                turma_id=turma_bncc.id,
                usuario_id=professor.id,
                papel_participante=PapelParticipanteFormacao.PROFESSOR,
            )
            form_svc.atualizar_progresso_participante(
                db,
                participante_id=participante.id,
                carga_horaria_remota_realizada=40,
                carga_horaria_presencial_realizada=40,
                devolutiva="Concluiu a formação PoC com êxito.",
            )
            summary["formacao_certificado"] = participante.certificado_emitido
        summary["programa_bncc_id"] = programa.id if programa else None

        inst_svc = AvaliacaoInstitucionalService()
        from app.models.avaliacao import CicloAvaliacaoSemestral

        ciclo = db.query(CicloAvaliacaoSemestral).filter(CicloAvaliacaoSemestral.titulo == CICLO_SEMESTRAL).first()
        if not ciclo:
            ciclo = inst_svc.criar_ciclo(
                db,
                titulo=CICLO_SEMESTRAL,
                ano_letivo="2026",
                semestre="1",
                criado_por_usuario_id=admin.id,
            )
            inst = inst_svc.criar_instrumento(
                db,
                nome="Instrumento gestor — PoC",
                perfil="gestor",
                ciclo_id=ciclo.id,
            )
            inst_svc.criar_criterio(db, instrumento_id=inst.id, titulo="Liderança pedagógica", peso=1.0)
            summary["ciclo_semestral_id"] = ciclo.id

        db.commit()
        return summary
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    s = seed_paracuru()
    print("Seed PoC Paracuru concluído:")
    for k, v in s.items():
        print(f"  {k}: {v}")
    print("\nAcesse: /admin/correcao-gabaritos?aplicacao_id=", s.get("aplicacao_id"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
