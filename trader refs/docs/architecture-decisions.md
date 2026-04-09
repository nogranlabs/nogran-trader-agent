# 🧠 Decisões Arquiteturais

Este documento descreve as principais decisões que guiam o design do sistema.

---

## 🤖 LLM NÃO EXECUTA TRADES

**Decisão:**
O LLM é utilizado apenas para sugerir interpretações e cenários.

**Motivação:**

* evitar alucinações
* garantir controle determinístico
* permitir validação independente

---

## 🛡️ MULTI-LAYER VALIDATION

Pipeline de decisão:

1. Pre-filter (antes do LLM)
2. LLM (interpretação)
3. AI Overlay (ajuste)
4. Risk Engine (decisão final)

**Motivação:**

* proteção de capital
* redundância
* robustez contra erros

---

## 🧮 DECISION SCORING SYSTEM

Cada decisão recebe uma pontuação (0–100):

* Strategy Score (LLM)
* Pre-filter Score
* AI Overlay Score
* Risk Score
* Market Quality Score

**Motivação:**

* explicabilidade
* comparação entre trades
* base para reputação (ERC-8004)

---

## 🔁 LEARNING LOOP CONTROLADO

O sistema se adapta com base em performance:

* ajuste de thresholds
* controle de frequência de trades
* adaptação de risco

**Motivação:**

* melhorar performance ao longo do tempo
* evitar overfitting ou comportamento instável

---

## 🧱 ARQUITETURA HEXAGONAL

Separação clara entre:

* domínio
* infraestrutura
* adapters

**Motivação:**

* testabilidade
* flexibilidade
* facilidade de evolução

---

## 📊 RAG TOP-DOWN

Pipeline estruturado em múltiplas camadas:

* contexto macro → micro
* isolamento de informações

**Motivação:**

* reduzir ruído
* evitar confusão do LLM
* aumentar qualidade das decisões

---

## ⚠️ RISK ENGINE COMO AUTORIDADE FINAL

Nenhuma operação é executada sem aprovação do Risk Engine.

**Motivação:**

* proteção de capital
* alinhamento com métricas de risk-adjusted return
* conformidade com ERC-8004

---

## 🧩 PRINCÍPIO CENTRAL

> “O sistema assume que a IA pode estar errada e exige validação antes de arriscar capital.”

Isso define toda a arquitetura.
