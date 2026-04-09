# Pre-Filter / Session Guard

Protege o filtro de qualidade de mercado e os modos de sessao.

## Trigger

Ativado quando o usuario pede para alterar:
- `src/market/pre_filter.py`

## Regras

1. MQ veto threshold (MQ < 30 bloqueia trade) NAO pode ser removido sem aprovacao
2. Session modes (AGGRESSIVE/CONSERVATIVE/OBSERVATION) seguem horarios UTC definidos em Config
3. OBSERVATION mode NAO deve permitir trades — eh o circuit breaker temporal
4. CONSERVATIVE mode permite apenas setups de alta qualidade (Config.CONSERVATIVE_SETUPS)
5. Sizing multipliers por sessao devem respeitar: AGGRESSIVE=1.0, CONSERVATIVE=0.6
6. Apos alteracao: rodar `python -m pytest tests/ -v`
