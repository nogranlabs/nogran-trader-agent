# Risk Engine Guard

Protege o Risk Engine contra alteracoes que comprometam controle de risco.

## Trigger

Ativado quando o usuario pede para alterar arquivos em:
- `src/risk/drawdown_controller.py`
- `src/risk/exposure_manager.py`
- `src/risk/position_sizer.py`
- `src/risk/metrics.py`

## Regras

1. O Risk Engine NUNCA depende do LLM — toda logica eh deterministica
2. Circuit breaker em drawdown > 8% NAO pode ser removido ou relaxado sem aprovacao
3. Bandas de drawdown: NORMAL <3%, DEFENSIVE 3-5%, MINIMUM 5-8%, CIRCUIT_BREAKER >8%
4. MAX_TRADES_PER_HOUR=4 e COOLDOWN_CANDLES=2 sao limites de seguranca
5. Position sizing deve sempre respeitar RISK_PER_TRADE (1% do capital)
6. Apos alteracao aprovada: rodar `python -m pytest tests/ -v`
