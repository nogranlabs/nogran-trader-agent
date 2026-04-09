# Decision Scorer Guard

Protege a logica critica do Decision Scorer e seus pesos.

## Trigger

Ativado quando o usuario pede para alterar arquivos em:
- `src/ai/decision_scorer.py`
- `src/infra/config.py` (campos DECISION_THRESHOLD, RISK_PER_TRADE, MIN_REWARD_RISK)

## Regras

1. PEDIR APROVACAO EXPLICITA antes de alterar pesos (MQ 20%, SS 35%, AO 20%, RS 25%)
2. PEDIR APROVACAO EXPLICITA antes de alterar thresholds (DECISION_THRESHOLD=65, MIN_REWARD_RISK=1.5)
3. PEDIR APROVACAO EXPLICITA antes de alterar RISK_PER_TRADE=1%
4. Qualquer mudanca deve manter: hard veto se sub-score < 20
5. Apos alteracao aprovada: rodar `python -m pytest tests/ -v` para confirmar que nada quebrou
