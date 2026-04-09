# Verificacao do Pipeline

Verifica a integridade do pipeline de trading sem executar trades.

## Passos

1. Verificar que todos os imports em src/main.py resolvem:
 - Rodar: `cd src && python -c "from main import *"` (deve importar sem erro)
2. Verificar que .env.example tem todas as variaveis usadas em Config:
 - Ler src/infra/config.py e comparar os getenv com .env.example
3. Verificar que data/chunks/ tem os 6 layers esperados (layer0..layer5)
4. Verificar que LLM/ tem os 2 workflows JSON
5. Verificar que logs/decisions/ existe
6. Reportar: OK ou lista de problemas encontrados
