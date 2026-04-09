# LLM Schema Guard

Protege a compatibilidade entre o workflow LLM e o signal parser.

## Trigger

Ativado quando o usuario pede para alterar:
- `LLM/nogran-trader-agent-LLM.json` (workflow principal)
- `src/strategy/signal_parser.py` (parser de resposta)
- `src/strategy/fact_builder.py` (input para LLM)

## Regras

1. Se alterar o JSON de resposta no LLM: verificar que signal_parser.py consegue parsear o novo formato
2. Se alterar signal_parser.py: verificar que os campos esperados existem no workflow LLM (node Validador)
3. Se alterar fact_builder.py: verificar que o formato do "fato matematico" eh compativel com o prompt do Nogran PA AI Agent no LLM
4. Campos obrigatorios na resposta LLM: acao, confianca, tipo_dia, always_in, setup, qualidade_signal_bar, entry_price, stop_loss, take_profit, raciocinio, camada_decisiva
5. Fatos para LLM sao SEMPRE em portugues
