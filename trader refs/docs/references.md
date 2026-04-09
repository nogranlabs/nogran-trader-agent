# 📚 Referências Técnicas

Este projeto não foi construído como uma adaptação direta de frameworks existentes.
As referências abaixo foram utilizadas como **inspiração para componentes específicos**, mantendo uma arquitetura original e orientada a controle de risco, explicabilidade e robustez.

---

## ⚡ Execution Layer

### freqtrade

* Utilizado como referência para:

  * execução de ordens
  * estrutura de estratégias
  * backtesting

**Decisão:**

* NÃO adotamos a arquitetura completa
* Implementação própria focada em integração com Kraken CLI

---

## 🧠 Feature Engineering

### qlib (Microsoft)

* Inspirou:

  * organização de features
  * separação entre dados brutos e sinais derivados

**Adaptação:**

* Foco em contexto intraday (1m)
* Integração com Price Action e estrutura de mercado

---

## 🛡️ Risk Management

### pyfolio / ffn

* Referência para métricas:

  * Sharpe Ratio
  * Max Drawdown
  * Performance tracking

**Adaptação:**

* Métricas usadas em tempo real (não apenas análise histórica)
* Integração direta com decisão de execução

---

## ⛓️ Smart Contracts / Web3

### OpenZeppelin

* Base para:

  * padrões ERC-721 (identidade do agente)
  * compatibilidade com ERC-8004

**Uso:**

* Estrutura de identidade, assinatura e validação de decisões

---

## 🤖 AI / Decision Systems

### Conceitos gerais de AI Agents

* Inspiração em:

  * sistemas multi-camadas
  * separação entre percepção e decisão

**Decisão:**

* O LLM NÃO executa trades
* Atua apenas como camada interpretativa e de sugestão

---

## 🧩 Princípio Geral

Este sistema segue o princípio:

> “Referências são usadas para fortalecer componentes, não para definir a arquitetura.”

Isso garante:

* originalidade
* controle total do sistema
* vantagem competitiva no hackathon
