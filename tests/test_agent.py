import json

import pytest
import requests


# Função simulada para chamar sua IA (Ajuste para a sua realidade)
def chamar_agente_ia(dados_mercado):
    """
    Aqui você faria um POST para o Webhook do LLM ou chamaria o LangChain.
    Exemplo: 
    response = requests.post("URL_DO_SEU_LLM_PROVIDER", json=dados_mercado)
    return response.json()
    """
    
    # Simulação de uma resposta perfeita da IA para fins de demonstração
    return {
        "acao": "COMPRAR",
        "raciocinio": "O mercado fez uma perna A de baixa, tentou subir na perna B (High 1), caiu para a perna C e agora a barra atual rompeu a máxima anterior, acionando o setup High 2. Ação executada com sucesso."
    }

def carregar_gabaritos():
    with open("tests/gabaritos_pa.json", encoding="utf-8") as f:
        return json.load(f)

# O teste mágico começa aqui
@pytest.mark.parametrize("teste", carregar_gabaritos())
def test_raciocinio_do_agente(teste):
    print(f"\n🧪 Executando Teste: {teste['id_teste']}")
    
    # 1. Envia os dados simulados (Mock) para a IA
    dados_para_ia = {
        "mensagem": "Analise as seguintes barras e tome uma decisão.",
        "barras": teste["dados_mock_ohlcv"]
    }
    
    # 2. Recebe a resposta do Agente
    resposta_ia = chamar_agente_ia(dados_para_ia)
    
    # 3. ASSERÇÕES (O Tribunal do Nogran PA)
    
    # Verifica se a IA tomou a decisão certa (COMPRAR, VENDER, AGUARDAR)
    assert resposta_ia["acao"] == teste["gabarito_acao"], \
        f"❌ FALHA: A IA decidiu {resposta_ia['acao']}, mas o gabarito era {teste['gabarito_acao']}"
        
    # Verifica se a IA usou o raciocínio certo (ex: mencionou "High 2" ou "H2")
    # Isso garante que ela não acertou por sorte, mas sim porque acessou o RAG corretamente
    assert teste["gabarito_motivo_chave"].lower() in resposta_ia["raciocinio"].lower(), \
        f"❌ FALHA DE ALUCINAÇÃO: A IA tomou a ação certa, mas pelo motivo errado. Raciocínio da IA: {resposta_ia['raciocinio']}"
        
    print("✅ TESTE PASSOU: A IA operou exatamente como o Nogran PA!")

if __name__ == "__main__":
    # Para rodar manualmente no terminal
    testes = carregar_gabaritos()
    for t in testes:
        test_raciocinio_do_agente(t)