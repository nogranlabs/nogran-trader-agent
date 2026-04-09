# Compliance / ERC-8004 Guard

Protege a integracao on-chain e o audit trail.

## Trigger

Ativado quando o usuario pede para alterar:
- `src/compliance/erc8004_onchain.py`
- `src/compliance/decision_logger.py`
- `src/compliance/abis/*.json`

## Regras

1. NAO logar private keys, assinaturas EIP-712, ou dados criptograficos em mensagens de erro
2. Enderecos de contratos (Sepolia) so podem ser alterados se os ABIs correspondentes forem atualizados
3. decision_logger.py deve sempre gravar JSONL com timestamp ISO — formato eh contrato com o dashboard
4. Se alterar formato do JSONL: verificar que dashboard/app.py consegue parsear
5. Apos alteracao: verificar que imports em main.py continuam resolvendo
