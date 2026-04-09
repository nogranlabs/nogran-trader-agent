# Hackathon: AI Trading Agents (lablab.ai + Kraken + Surge)

> Documento de referencia. Consultar SEMPRE que tiver duvida sobre o que move o ranking.
> Fontes: https://lablab.ai/ai-hackathons/ai-trading-agents e https://lablab.ai/ai-hackathons/ai-trading-agents-erc-8004
> Coletado: 2026-04-08. WebFetch direto retorna 403; info via WebSearch.
> **Atualizado: 2026-04-09** — adicionada secao 12 (regras gerais lablab.ai: MIT + original work + third-party disclosure).

---

## 1. Janela e prazo

- **Inicio:** 2026-03-30
- **Fim:** 2026-04-12 (deadline de submissao)
- **Hoje:** 2026-04-08 -> restam **4 dias uteis ate o freeze**
- Estado nogran agora: dev branch, 190 testes, tech-debt 14/15, CI 3.10/3.11/3.12 verde, Phase 8 nao iniciada

## 2. Premio

- **Pool total:** $55,000
- Distribuido via **Surge** ($SURGE tokens) + **Kraken**
- Premios sao depositados em contas de trading dos vencedores (nao em fiat livre)

## 3. Estrutura: 2 challenges

O hackathon tem **2 challenges paralelos**. Time pode entrar em 1 ou nos 2; submissao combinada e elegivel pra premio dos 2.

| Challenge | Foco | O que avalia |
|---|---|---|
| **Kraken Challenge** | Agente autonomo via Kraken CLI | risk-adjusted PnL + drawdown + validation |
| **ERC-8004 Challenge** | Trustless trading com ERC-8004 (Identity + Reputation + Validation Registry) | TradeIntent assinado, Risk Router, attestations on-chain |

**Estrategia nogran:** entrar nos **2** simultaneamente. Ja temos Kraken CLI wrapper + ERC-8004 contracts em Config (`AGENT_REGISTRY`, `RISK_ROUTER`, `REPUTATION_REGISTRY`, `VALIDATION_REGISTRY`, `HACKATHON_VAULT`). Submissao combinada -> elegivel a premio duplo.

## 4. Criterios de juiz (4 dimensoes, peso aparente igual)

1. **Application of Technology** — quao bem os modelos/tools estao integrados
2. **Presentation** — clareza e efetividade do pitch
3. **Impact & practical value** — aplicabilidade real
4. **Uniqueness & creativity** — diferencial e inovacao

## 5. Leaderboard (ranking automatico)

Tracked durante o periodo:
- **PnL liquido** (com fees Kraken: 0.26% taker)
- **Sharpe ratio**
- **Max drawdown**
- **Validation score** (postado no Validation Registry on-chain)

**Regra explicita do site:**
> "Rankings are based on risk-adjusted profitability, drawdown control, and validation quality, **NOT just raw PnL**."

**Implicacao:** ganhar PnL alto com DD alto perde pra PnL menor com Sharpe alto + DD controlado. Validation quality e o desempate.

## 6. Componentes tecnicos exigidos

### Kraken Challenge
- **Kraken CLI** como execution layer (paper trading aceito, ja usamos)
- AI-native command-line: `kraken paper buy/sell/balance/pnl/reset`, `kraken market ohlc/ticker`
- Sem requisito de capital real

### ERC-8004 Challenge
- **AgentRegistry** (ERC-721) — identidade do agente
- **EIP-712 typed signatures** — assinar TradeIntent antes da execucao
- **Risk Router contract** — enforce position size, max leverage, whitelisted markets, daily loss limits
- **ReputationRegistry** — feedback on-chain
- **ValidationRegistry** — validators postam scores
- Eventos on-chain pra cada trade e checkpoint
- Endereco Sepolia ja em `src/infra/config.py:60-65`:
 - `AGENT_REGISTRY = 0x97b07dDc405B0c28B17559aFFE63BdB3632d0ca3`
 - `HACKATHON_VAULT = 0x0E7CD8ef9743FEcf94f9103033a044caBD45fC90`
 - `RISK_ROUTER = 0xd6A6952545FF6E6E6681c2d15C59f9EB8F40FdBC`
 - `REPUTATION_REGISTRY = 0x423a9904e39537a9997fbaF0f220d79D7d545763`
 - `VALIDATION_REGISTRY = 0x92bF63E5C7Ac6980f237a7164Ab413BE226187F1`

## 7. Submissao — entregaveis

- **Codigo** (repo publico — ja temos `nogran-trader-agent` publico, dataset Nogran PA no privado)
- **Video pitch** (postado em X/Twitter, taggar `@lablabai` e `@Surgexyz_`)
- **Submissao no portal lablab** com descricao do projeto
- **Demo executavel** (Docker recomendado — ja temos `docker compose up`)

## 8. O que move RANKING vs o que move JUIZ

| Item | Move ranking? | Move juiz? |
|---|---|---|
| Sharpe ratio alto | SIM (direto) | SIM (Application of Tech) |
| Max DD baixo | SIM (direto) | SIM (Impact) |
| Validation score on-chain | SIM (direto) | SIM (Application of Tech) |
| Nogran PA KB + hallucination detector | NAO (nao e metrica) | SIM (Uniqueness — KILLER) |
| Decision Score 0-100 + 4 sub-scores auditaveis | NAO | SIM (Application of Tech) |
| Dashboard Streamlit + Thinking tab | NAO | SIM (Presentation) |
| 190 testes + CI | NAO | SIM (Application of Tech) |
| Risk Engine independente do LLM | NAO direto | SIM (Uniqueness + Impact) |
| ERC-8004 5 contratos integrados | NAO direto | SIM (Application of Tech) |
| Multi-cenario / H/L counter / trail stop | NAO em 4 dias | NAO (juiz nao olha codigo profundo) |

**Lei do hackathon:** otimizar o que move RANKING + ter narrativa que move JUIZ. Cuidado em over-engineering que so move "code quality" (juiz nao audita 200 testes).

## 9. Concorrencia conhecida

- Multi-agent LLM consensus (Analyst + Risk Guardian + Executor) com 3-way voting — **diferencial deles:** consenso. **Nosso diferencial vs eles:** Nogran PA KB cross-check (evidencia, nao opiniao) + Risk Engine determinista (nao depende de LLM consensus que pode ter alucinacao coletiva).

## 10. Riscos e bloqueadores

- **Validation Registry post**: precisamos confirmar formato esperado (assinatura, payload). Se nao tiver doc clara, postar score simples (PnL + Sharpe + DD em JSON assinado EIP-712).
- **Dados historicos Kraken**: ccxt rate limit em 1m/30d; fallback 7d.
- **Site lablab bloqueia WebFetch (403)**: re-checar criterio manualmente antes do freeze.
- **LLM nao roda no juiz**: backtest tem que funcionar SEM LLM vivo (usar `probabilities_kb` direto como fallback).

## 11. Quando re-consultar este doc

- Antes de iniciar qualquer fase nova
- Quando duvidar se feature X "vale a pena" pro hackathon
- Antes de gravar o pitch
- Antes do freeze 2026-04-11

---

## 12. Regras gerais lablab.ai (CRITICAL — descoberto 2026-04-09)

Confirmado em 2 buscas independentes (WebSearch — site continua bloqueando WebFetch direto, 403). As regras padrao lablab.ai aplicam a TODOS os hackathons da plataforma, incluindo este, "unless specified otherwise":

### 12.1 Licenca e propriedade

> **"All submissions by participants must be original work, open source, and compliant with the MIT License unless specified otherwise."**

**Tres requisitos cumulativos:**
1. **Original work** — codigo nao pode ser derivacao de material copyright protegido sem licenca/permissao
2. **Open source** — o codigo da submissao precisa estar publicamente acessivel
3. **MIT License** — licenca padrao da submissao (MIT permissive); ou justificar outra licenca

### 12.2 Disclosure de terceiros

> **"If a project uses third-party code, models, or services, they must be clearly disclosed in the submission."**

Vendor code (FinRL, pyfolio, ffn, openzeppelin), APIs externas (OpenAI, Kraken), modelos (GPT-4o), etc — todos devem aparecer numa secao "Third-Party" na submissao.

### 12.3 Implicacoes diretas pra nogran-trader-agent

| Item | Status | Acao requerida |
|---|---|---|
| Repo `nogran-trader-agent` precisa ser publico | Pendente — atualmente privado em github.com/nogranlabs | Tornar publico antes do freeze |
| Repo precisa ter licenca MIT | LICENSE arquivo nao existe ainda | Criar `LICENSE` com texto MIT |
| Conteudo Brooks/Wiley historico | **VIOLACAO** — histori git tem blobs antigos com `data/probabilities/al_brooks_probabilities.json` (62 setups + book_refs page_pdf), `src/strategy/brooks_retriever.py` (BrooksChunk com Wiley refs), `n8n/*.json` (system prompt "trained on Al Brooks' methodology — Wiley"), commit messages "Brooks-structural / Brooks-pure" | Limpar historico via filter-repo OU criar repo novo a partir do working tree atual |
| `trader refs/` (FinRL, pyfolio, ffn, openzeppelin vendored) | Disclosure pendente | Adicionar `THIRD_PARTY.md` ou secao no README com lista de licencas |
| `src/prepare_knowledge.py` | Ja movido pro repo dataset privado + purgado do historico em 2026-04-09 (filter-repo) | OK |
| Working tree atual (Brooks/Wiley refs) | Limpo em 2026-04-09 (cleanup commits a3d413d..1414b3d) | OK — 386/386 tests verdes |

### 12.4 Risco copyright se NAO limpar historico

- Wiley pode emitir DMCA takedown apos repo virar publico (clones automatizados detectam reproducao verbatim)
- Discord/Twitter da submissao pode ser usado como prova de violacao
- "MIT-licensed" + "derivado de Wiley" = inconsistencia legal direta (juiz pode descredenciar)
- GitHub mantem cache de blobs orfaos por ~90 dias mesmo apos force-push — limpeza completa exige criar repo novo

### 12.5 Recomendacao operacional

**Antes do freeze 2026-04-11**, escolher 1 das 2 abordagens:

| Abordagem | Custo | Seguranca |
|---|---|---|
| **A. `git filter-repo --replace-text` + `--invert-paths`** sobre repo atual | Medio. Mantem repo existente, blame, stars, etc. | Media — filter-repo pode falhar em casos edge; ja perdemos trabalho 1x com isso |
| **B. Repo novo** — `git init` em diretorio limpo, copia working tree atual, commit unico "initial public release", arquiva repo antigo (privado) | Medio. Perde blame e historico de sprint. | Maxima — historico do zero, sem residuos |

**Default sugerido: B**, pelo custo equivalente e seguranca maior. O blame de 4 dias de sprint nao vale o risco legal.

### 12.6 LICENSE file ausente

Criar `LICENSE` na raiz com texto MIT padrao. Modelo:
```
MIT License

Copyright (c) 2026 Mateus Magri / nogran labs

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction...
```
(Texto completo: https://opensource.org/license/mit)

---

## Sources (research 2026-04-09)

- [AI Trading Agents | Lablab.ai](https://lablab.ai/ai-hackathons/ai-trading-agents) — pagina principal (bloqueada via WebFetch, info via WebSearch)
- [AI Trading Agents with ERC-8004 | Lablab.ai](https://lablab.ai/ai-hackathons/ai-trading-agents-erc-8004) — challenge ERC-8004 paralelo
- [Kraken Targets AI-Driven Trading Growth With Developer Hackathon — TipRanks](https://www.tipranks.com/news/private-companies/kraken-targets-ai-driven-trading-growth-with-developer-hackathon) — anuncio Kraken
- [Lablab.ai Guide](https://lablab.ai/guide) — guia geral de submissao

