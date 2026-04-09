# Execution Guard

Protege o executor contra mudancas que possam causar trades nao intencionais.

## Trigger

Ativado quando o usuario pede para alterar:
- `src/execution/executor.py`
- `src/execution/kraken_cli.py`

## Regras

1. O mode padrao DEVE ser "paper" — NAO alterar para "live" sem aprovacao explicita
2. executor.py DEVE validar decision_score.go e risk_approval.approved antes de executar
3. kraken_cli.py usa subprocess com listas (nao strings) — manter para evitar command injection
4. Erros do Kraken CLI devem ser capturados como KrakenCLIError — nao silenciar
5. NAO remover o timeout de 30s do subprocess
6. Apos alteracao: rodar `python -m pytest tests/ -v`
