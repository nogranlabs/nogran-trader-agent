# Executar Testes

Roda os testes do projeto e reporta resultados.

## Passos

1. Rodar: `python -m pytest tests/ -v` (a partir da raiz do projeto)
2. Se falhar, analisar o erro e reportar causa raiz
3. NAO corrigir testes automaticamente — reportar o problema ao usuario
4. Se o usuario pedir pra criar novos testes, colocar em tests/ seguindo o padrao existente (pytest + parametrize com gabaritos JSON)
