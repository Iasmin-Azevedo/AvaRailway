# Validação OCR em lote — PoC Paracuru

**Data da validação:** 2026-05-27 (atualizado)  
**Critério mínimo PoC:** ≥10 folhas no lote; QR em 100% das folhas base; taxa média de leitura ≥85% no lote ampliado.

## Resultado consolidado

| Métrica | Valor |
|---------|-------|
| Folhas no lote ampliado | **28** (4 scans reais + 24 variantes de stress) |
| Folhas base (scans reais) | 4 — QR OK **100%**, leitura **100%** |
| Taxa média de leitura (lote 28) | **~95,5%** |
| Status | **Aprovado para demonstração** |

## Folhas base (scans reais)

| Arquivo | Participação | Respostas | Taxa |
|---------|--------------|-----------|------|
| Group_241 | #19 | Q1–Q4: C | 100% |
| Group_243 | #20 | Q1–Q4: B | 100% |
| Group_244 | #21 | Q1–Q4: B | 100% |
| Group_245 | #19 | Q1–Q4: B | 100% |

## Lote ampliado (stress)

Variantes geradas a partir das 4 folhas base (brilho, contraste, autocontrast, rotação leve) para simular condições de foto/impressão variadas. Algumas variantes extremas podem falhar em 1 questão — usar **preview manual** na demo.

## Como reproduzir

```bash
# Gerar variantes (opcional, primeira vez)
python scripts/gerar_fixtures_ocr_lote.py

# Validar lote
python scripts/validar_ocr_lote.py --n-questoes 4 --json-out docs/OCR_VALIDACAO_LOTE_POC.json tests/fixtures/ocr/Group_*.png

# Testes automatizados
python -m pytest tests/test_ocr_lote_poc.py -q
```

## Contingência na demo

1. Preferir folhas **base** ou PDF recém-gerado pelo sistema.
2. Se alternativa não vier marcada no preview, **ajustar nos botões A–E** antes de confirmar.
3. Fallback: **Importar CSV** na tela de correção + modelo CSV.
4. Foto nítida, QR visível, sem sombra forte.

## Congelamento

Não alterar `gabarito_layout.py` nem limiares OCR após validação sem rerodar o lote.

## Artefato JSON

[`OCR_VALIDACAO_LOTE_POC.json`](./OCR_VALIDACAO_LOTE_POC.json)
