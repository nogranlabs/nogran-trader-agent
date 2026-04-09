# Analise da concorrencia (snapshot 2026-04-08)

> Coletado durante o setup ERC-8004 (registro do agente nogran como id 44).
> Fonte: scan direto do contrato `AgentRegistry` em Sepolia.
> **Re-validar antes do freeze 2026-04-11** — numeros mudam diariamente.

---

## Numeros chave

- **Agentes registrados on-chain:** 45 (id 1 a 45 = id 44 e o nogran)
- **Hackathon termina:** 2026-04-12 (4 dias)
- **Estimativa de SUBMISSOES finais:** 15-30 (taxa media de hackathon e ~50% dropouts)
- **Times reais (estimativa):** 25-35 (alguns registram multiplas variantes)

## Lista dos ultimos 9 antes do nogran

| id | name | owner_prefix | Inferencia |
|---|---|---|---|
| 44 | **nogran.trader.agent** | 0xe852... | **NOSSO** |
| 43 | Swiftward Gamma | 0xC5e0... | Variante C de team Swiftward — pesquisa seria |
| 42 | SWIFTWARD_BETA | 0x39ca... | Variante B do mesmo time |
| 41 | HackathonTradingAgent | 0x3d21... | Nome generico, provavel registro abandonado |
| 40 | AlphaTrading | 0x30d0... | Nome generico, provavel junior |
| 39 | ARIA-MASTER | 0x0858... | Nome de produto — possivel vendor |
| 38 | APEX | 0x3398... | Nome generico, indeterminado |
| 37 | Random Trader | 0x7a2F... | Auto-explicativo, baixa ameaca |
| 36 | PalmyraAI | 0xED1e... | Provavel empresa Palmyra/Writer — competitor serio |

## Categorizacao dos competidores

| Categoria | Quantidade estimada | Caracteristica |
|---|---|---|
| **Times serios** | 5-10 | Multiplas variantes, nomes proprios, aparecem cedo no historico |
| **Hobbyists / juniores** | 15-20 | Nomes genericos, registro unico, sem variantes |
| **Abandoned / curiosity** | 10-15 | Registraram cedo, nunca postaram checkpoint |

**Conclusao:** competimos contra **5-10 agentes serios**, nao 44.

## Diferenciais do nogran vs concorrencia conhecida

| Feature | Nogran | Swiftward | PalmyraAI | Outros tipicos |
|---|---|---|---|---|
| Nogran PA KB cross-check | **SIM** (62 setups + 22 hard rules) | improvavel | improvavel | improvavel |
| Hallucination detector estruturado | **SIM** (alarme >=25 pts) | improvavel | improvavel | nao |
| Risk Engine independente do LLM | **SIM** | provavel | provavel | improvavel |
| Pipeline 7-stage com vetos | **SIM** | provavel | provavel | nao |
| Audit trail JSONL completo | **SIM** | possivel | possivel | possivel |
| Backtest engine reproduzivel | **SIM** | provavel | provavel | improvavel |
| Dashboard 8 abas Plotly | **SIM** | possivel | provavel | improvavel |
| ERC-8004 5 contratos integrados | **SIM** | provavel | provavel | so identity |
| **Documentacao de honestidade** (admite limitacoes) | **SIM** (fee-drag finding) | improvavel | improvavel | nao |
| 255 testes + CI 3.10/3.11/3.12 | **SIM** | possivel | possivel | nao |

## O que ranqueia oficialmente (ja documentado em hackathon-criteria.md)

1. **Application of Technology** (peso ~25%)
2. **Presentation** (peso ~25%)
3. **Impact / practical value** (peso ~25%)
4. **Uniqueness & creativity** (peso ~25%)

PLUS leaderboard automatico:
- PnL liquido
- Sharpe ratio
- Drawdown
- Validation score (on-chain)

## Estrategia ofensiva nogran (4 dias)

### Frente 1 — leaderboard automatico
- **PnL/Sharpe:** mock heuristic perde, precisa rodar live com LLM+GPT-4o por 3 dias
- **Drawdown:** Risk Engine ja controla bem (max 8% no backtest)
- **Validation score:** **JA POSTADO** (31/100). Postar de novo a cada 6h com runs mais novos

### Frente 2 — pitch pros juizes
- **Uniqueness:** Nogran PA KB + hallucination detector e killer feature, defender com sangue
- **Presentation:** Streamlit dashboard com 8 abas + video pitch focado em "honest > optimistic"
- **Impact:** Risk Engine independente + hard veto matrix
- **Tech:** 255 testes, CI matrix, Docker 1-comando, ERC-8004 5/5 contratos

### Frente 3 — narrativa diferenciada
**Posicionamento:** "O unico agente do hackathon que admite quando esta errado."

A maioria dos agentes vai esconder limitacoes. Nos publicamos:
- `docs/strategy-fee-drag-finding.md` — admitimos que mock heuristic nao tem alpha
- `docs/feature-gap-audit.md` — auditoria 56 itens, 41 ainda ausentes
- `docs/tech-debt.md` — 14/15 resolvidos, 1 critico restante (exposure manager)
- README com numeros reais do backtest, nao cherry-picked

Juizes serios premiam transparencia. Pitch: **"voces podem confiar no que esse agente diz porque ele tambem diz quando nao sabe."**

## Acoes pendentes pra ganhar

| # | Acao | Prazo | Por que |
|---|---|---|---|
| 1 | Live trading 3 dias (com ou sem LLM) | 04/09-04/12 | Dados reais → PnL real → leaderboard |
| 2 | Periodic checkpoint poster (a cada 6h) | imediato | Mostra que agente esta vivo, nao morto |
| 3 | Video pitch focado em Nogran PA KB + honestidade | 04/11 | Frente 2 |
| 4 | README hackathon-section refinado | 04/10 | Primeira impressao do juiz |
| 5 | Re-rodar este scan na vespera do freeze | 04/11 | Saber quem registrou nos ultimos dias |

---

> "Nao ganhamos por operar mais. Ganhamos por saber quando NAO operar — e por sermos honestos sobre os limites do que sabemos."
