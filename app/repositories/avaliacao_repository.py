from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.avaliacao import (
    AplicacaoProva,
    AplicacaoAvaliacaoInstitucional,
    Avaliacao,
    BancoQuestao,
    CicloAvaliacaoSemestral,
    CriterioAvaliacaoInstitucional,
    InstrumentoAvaliacaoInstitucional,
    LoteImportacaoGabarito,
    ParticipacaoAplicacaoProva,
    Questao,
)
from app.models.resposta import RespostaAluno, RespostaAvaliacaoInstitucional


class AvaliacaoRepository:
    def get_avaliacao(self, db: Session, avaliacao_id: int):
        return db.query(Avaliacao).filter(Avaliacao.id == avaliacao_id).first()

    def update_avaliacao(
        self,
        db: Session,
        *,
        avaliacao_id: int,
        titulo: str,
        descricao: str | None,
        ano_letivo: str | None,
        curso_id: int | None,
        trilha_id: int | None,
        ano_escolar: int | None,
    ) -> Avaliacao | None:
        obj = self.get_avaliacao(db, avaliacao_id)
        if not obj:
            return None
        obj.titulo = titulo
        obj.descricao = descricao
        obj.codigo = None
        obj.ano_letivo = ano_letivo
        obj.curso_id = curso_id
        obj.trilha_id = trilha_id
        obj.ano_escolar = ano_escolar
        db.commit()
        db.refresh(obj)
        return obj

    def replace_questoes_da_avaliacao(
        self,
        db: Session,
        *,
        avaliacao_id: int,
        banco_questoes: list[BancoQuestao],
    ) -> list[Questao]:
        db.query(Questao).filter(Questao.avaliacao_id == avaliacao_id).delete()
        db.commit()
        novas: list[Questao] = []
        for index, banco_questao in enumerate(banco_questoes, start=1):
            obj = self.create_questao_from_bank(
                db,
                avaliacao_id=avaliacao_id,
                banco_questao=banco_questao,
                numero=index,
                peso=1.0,
                disciplina=getattr(getattr(banco_questao, "curso", None), "nome", None),
                codigo=None,
            )
            novas.append(obj)
        return novas

    def delete_avaliacao(self, db: Session, avaliacao_id: int) -> bool:
        obj = self.get_avaliacao(db, avaliacao_id)
        if not obj:
            return False
        db.delete(obj)
        db.commit()
        return True

    def get_aplicacao_prova(self, db: Session, aplicacao_id: int) -> AplicacaoProva | None:
        return db.query(AplicacaoProva).filter(AplicacaoProva.id == aplicacao_id).first()

    def get_banco_questao(self, db: Session, banco_questao_id: int) -> BancoQuestao | None:
        return db.query(BancoQuestao).filter(BancoQuestao.id == banco_questao_id).first()

    def salvar_resposta(
        self,
        db: Session,
        aluno_id: int,
        avaliacao_id: int,
        questao_id: int,
        marcada: str,
        correta: bool,
        *,
        aplicacao_id: int | None = None,
        participacao_id: int | None = None,
        pontuacao: float | None = None,
    ):
        resposta = RespostaAluno(
            aluno_id=aluno_id,
            avaliacao_id=avaliacao_id,
            aplicacao_id=aplicacao_id,
            participacao_id=participacao_id,
            questao_id=questao_id,
            resposta_marcada=marcada,
            acertou=correta,
            pontuacao=pontuacao,
        )
        db.add(resposta)
        db.commit()
        return resposta

    def create_banco_questao(
        self,
        db: Session,
        *,
        autor_usuario_id: int | None,
        curso_id: int | None,
        ano_escolar: int | None,
        descritor_id: int | None,
        conteudo: str | None,
        tipo_questao: str,
        origem,
        enunciado: str,
        alternativa_a: str,
        alternativa_b: str,
        alternativa_c: str,
        alternativa_d: str,
        alternativa_e: str,
        gabarito: str,
        habilidade_saeb: str | None,
        codigo_referencia: str | None,
        observacoes: str | None,
    ) -> BancoQuestao:
        obj = BancoQuestao(
            autor_usuario_id=autor_usuario_id,
            curso_id=curso_id,
            ano_escolar=ano_escolar,
            descritor_id=descritor_id,
            conteudo=conteudo,
            tipo_questao=tipo_questao,
            origem=origem,
            enunciado=enunciado,
            alternativa_a=alternativa_a,
            alternativa_b=alternativa_b,
            alternativa_c=alternativa_c,
            alternativa_d=alternativa_d,
            alternativa_e=alternativa_e,
            gabarito=gabarito,
            habilidade_saeb=habilidade_saeb,
            codigo_referencia=codigo_referencia,
            observacoes=observacoes,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def update_banco_questao(
        self,
        db: Session,
        *,
        banco_questao_id: int,
        curso_id: int | None,
        ano_escolar: int | None,
        descritor_id: int | None,
        conteudo: str | None,
        tipo_questao: str,
        enunciado: str,
        alternativa_a: str,
        alternativa_b: str,
        alternativa_c: str,
        alternativa_d: str,
        alternativa_e: str,
        gabarito: str,
        habilidade_saeb: str | None,
        observacoes: str | None,
    ) -> BancoQuestao | None:
        obj = self.get_banco_questao(db, banco_questao_id)
        if not obj:
            return None
        obj.curso_id = curso_id
        obj.ano_escolar = ano_escolar
        obj.descritor_id = descritor_id
        obj.conteudo = conteudo
        obj.tipo_questao = tipo_questao
        obj.enunciado = enunciado
        obj.alternativa_a = alternativa_a
        obj.alternativa_b = alternativa_b
        obj.alternativa_c = alternativa_c
        obj.alternativa_d = alternativa_d
        obj.alternativa_e = alternativa_e
        obj.gabarito = gabarito
        obj.habilidade_saeb = habilidade_saeb
        obj.observacoes = observacoes
        db.commit()
        db.refresh(obj)
        return obj

    def soft_delete_banco_questao(self, db: Session, banco_questao_id: int) -> bool:
        obj = self.get_banco_questao(db, banco_questao_id)
        if not obj:
            return False
        obj.ativo = False
        db.commit()
        return True

    def create_questao_from_bank(
        self,
        db: Session,
        *,
        avaliacao_id: int,
        banco_questao: BancoQuestao,
        numero: int | None,
        peso: float,
        disciplina: str | None,
        codigo: str | None,
    ) -> Questao:
        obj = Questao(
            avaliacao_id=avaliacao_id,
            banco_questao_id=banco_questao.id,
            codigo=codigo or banco_questao.codigo_referencia,
            numero=numero,
            curso_id=banco_questao.curso_id,
            ano_escolar=banco_questao.ano_escolar,
            descritor_id=banco_questao.descritor_id,
            conteudo=banco_questao.conteudo,
            tipo_questao=banco_questao.tipo_questao,
            origem=getattr(banco_questao.origem, "value", banco_questao.origem),
            enunciado=banco_questao.enunciado,
            alternativa_a=banco_questao.alternativa_a,
            alternativa_b=banco_questao.alternativa_b,
            alternativa_c=banco_questao.alternativa_c,
            alternativa_d=banco_questao.alternativa_d,
            alternativa_e=banco_questao.alternativa_e,
            gabarito=banco_questao.gabarito,
            habilidade_saeb=banco_questao.habilidade_saeb,
            disciplina=disciplina,
            peso=peso,
            ativa=True,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def create_aplicacao_prova(
        self,
        db: Session,
        *,
        avaliacao_id: int,
        titulo: str | None,
        escopo: str,
        ano_letivo: str | None,
        periodo_referencia: str | None,
        turma_id: int | None,
        escola_id: int | None,
        status,
        data_aplicacao,
        observacoes: str | None,
        criado_por_usuario_id: int | None,
    ) -> AplicacaoProva:
        obj = AplicacaoProva(
            avaliacao_id=avaliacao_id,
            titulo=titulo,
            escopo=escopo,
            ano_letivo=ano_letivo,
            periodo_referencia=periodo_referencia,
            turma_id=turma_id,
            escola_id=escola_id,
            status=status,
            data_aplicacao=data_aplicacao,
            observacoes=observacoes,
            criado_por_usuario_id=criado_por_usuario_id,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def get_or_create_participacao(
        self,
        db: Session,
        *,
        aplicacao_id: int,
        aluno_id: int,
        turma_id_snapshot: int | None,
        escola_id_snapshot: int | None,
    ) -> ParticipacaoAplicacaoProva:
        item = (
            db.query(ParticipacaoAplicacaoProva)
            .filter(
                ParticipacaoAplicacaoProva.aplicacao_id == aplicacao_id,
                ParticipacaoAplicacaoProva.aluno_id == aluno_id,
            )
            .first()
        )
        if item:
            return item
        item = ParticipacaoAplicacaoProva(
            aplicacao_id=aplicacao_id,
            aluno_id=aluno_id,
            turma_id_snapshot=turma_id_snapshot,
            escola_id_snapshot=escola_id_snapshot,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def atualizar_participacao(
        self,
        db: Session,
        *,
        participacao_id: int,
        total_questoes: int,
        total_acertos: int,
        nota: float,
    ) -> ParticipacaoAplicacaoProva | None:
        item = (
            db.query(ParticipacaoAplicacaoProva)
            .filter(ParticipacaoAplicacaoProva.id == participacao_id)
            .first()
        )
        if not item:
            return None
        item.presente = total_questoes > 0
        item.total_questoes = total_questoes
        item.total_acertos = total_acertos
        item.nota = nota
        item.processado_em = datetime.utcnow()
        db.flush()
        return item

    def upsert_resposta_importada(
        self,
        db: Session,
        *,
        aluno_id: int,
        avaliacao_id: int,
        aplicacao_id: int | None,
        participacao_id: int | None,
        questao_id: int,
        marcada: str,
        correta: bool,
        pontuacao: float,
        lote_importacao_id: int | None,
    ) -> RespostaAluno:
        resposta = (
            db.query(RespostaAluno)
            .filter(
                RespostaAluno.aluno_id == aluno_id,
                RespostaAluno.avaliacao_id == avaliacao_id,
                RespostaAluno.aplicacao_id == aplicacao_id,
                RespostaAluno.questao_id == questao_id,
            )
            .first()
        )
        if not resposta:
            resposta = RespostaAluno(
                aluno_id=aluno_id,
                avaliacao_id=avaliacao_id,
                aplicacao_id=aplicacao_id,
                participacao_id=participacao_id,
                questao_id=questao_id,
            )
            db.add(resposta)
        resposta.aplicacao_id = aplicacao_id
        resposta.participacao_id = participacao_id
        resposta.resposta_marcada = marcada
        resposta.acertou = correta
        resposta.pontuacao = pontuacao
        resposta.lote_importacao_id = lote_importacao_id
        db.flush()
        return resposta

    def create_ciclo(
        self,
        db: Session,
        *,
        titulo: str,
        ano_letivo: str,
        semestre: str,
        status,
        data_inicio=None,
        data_fim=None,
        criado_por_usuario_id: int | None = None,
    ) -> CicloAvaliacaoSemestral:
        obj = CicloAvaliacaoSemestral(
            titulo=titulo,
            ano_letivo=ano_letivo,
            semestre=semestre,
            status=status,
            data_inicio=data_inicio,
            data_fim=data_fim,
            criado_por_usuario_id=criado_por_usuario_id,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def create_instrumento(
        self,
        db: Session,
        *,
        nome: str,
        descricao: str | None,
        perfil_avaliado,
        ciclo_id: int | None,
    ) -> InstrumentoAvaliacaoInstitucional:
        obj = InstrumentoAvaliacaoInstitucional(
            nome=nome,
            descricao=descricao,
            perfil_avaliado=perfil_avaliado,
            ciclo_id=ciclo_id,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def create_criterio(
        self,
        db: Session,
        *,
        instrumento_id: int,
        titulo: str,
        descricao: str | None,
        peso: float,
    ) -> CriterioAvaliacaoInstitucional:
        ordem = (
            db.query(CriterioAvaliacaoInstitucional)
            .filter(CriterioAvaliacaoInstitucional.instrumento_id == instrumento_id)
            .count()
        )
        obj = CriterioAvaliacaoInstitucional(
            instrumento_id=instrumento_id,
            titulo=titulo,
            descricao=descricao,
            peso=peso,
            ordem=ordem,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def create_aplicacao_institucional(
        self,
        db: Session,
        *,
        ciclo_id: int,
        instrumento_id: int,
        escola_id: int | None,
        avaliado_usuario_id: int,
        respondente_usuario_id: int | None,
        observacoes: str | None,
    ) -> AplicacaoAvaliacaoInstitucional:
        obj = AplicacaoAvaliacaoInstitucional(
            ciclo_id=ciclo_id,
            instrumento_id=instrumento_id,
            escola_id=escola_id,
            avaliado_usuario_id=avaliado_usuario_id,
            respondente_usuario_id=respondente_usuario_id,
            observacoes=observacoes,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    def replace_respostas_institucionais(
        self,
        db: Session,
        *,
        aplicacao_id: int,
        respostas: list[dict],
    ) -> list[RespostaAvaliacaoInstitucional]:
        db.query(RespostaAvaliacaoInstitucional).filter(
            RespostaAvaliacaoInstitucional.aplicacao_id == aplicacao_id
        ).delete()
        items: list[RespostaAvaliacaoInstitucional] = []
        for row in respostas:
            item = RespostaAvaliacaoInstitucional(
                aplicacao_id=aplicacao_id,
                criterio_id=row["criterio_id"],
                nota=row["nota"],
                comentario=row.get("comentario"),
            )
            db.add(item)
            items.append(item)
        db.commit()
        return items

    def create_lote_importacao(
        self,
        db: Session,
        *,
        avaliacao_id: int,
        aplicacao_id: int | None,
        arquivo_nome: str,
        criado_por_usuario_id: int | None,
        linhas_processadas: int,
        linhas_com_erro: int,
        resumo_processamento: str | None,
    ) -> LoteImportacaoGabarito:
        obj = LoteImportacaoGabarito(
            avaliacao_id=avaliacao_id,
            aplicacao_id=aplicacao_id,
            arquivo_nome=arquivo_nome,
            criado_por_usuario_id=criado_por_usuario_id,
            linhas_processadas=linhas_processadas,
            linhas_com_erro=linhas_com_erro,
            resumo_processamento=resumo_processamento,
        )
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj