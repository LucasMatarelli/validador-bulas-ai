import time
import google.generativeai as genai
from google.api_core import exceptions

def validar_bula_com_resiliencia(prompt):
    # Lista de modelos em ordem de prioridade
    modelos = [
        "gemini-1.5-pro-latest",  # Modelo Principal (Melhor qualidade)
        "gemini-1.5-flash-latest" # Modelo de Segurança (Rápido e barato)
    ]

    for modelo_nome in modelos:
        try:
            print(f"🔄 Tentando usar modelo: {modelo_nome}...")
            model = genai.GenerativeModel(modelo_nome)
            
            # Tenta gerar o conteúdo
            response = model.generate_content(prompt)
            return response.text

        except exceptions.ResourceExhausted:
            # ERRO 429: Cota esgotada
            print(f"⚠️ Cota do {modelo_nome} esgotada.")
            
            if modelo_nome == modelos[-1]:
                # Se for o último modelo e falhar, espera 30s e tenta de novo o Flash
                print("⏳ Todos os modelos falharam. Aguardando 30 segundos para liberar cota...")
                time.sleep(30)
                return validar_bula_com_resiliencia(prompt) # Recursividade simples
            else:
                # Se não for o último, passa para o próximo modelo do loop imediatamente
                continue

        except exceptions.NotFound:
            # ERRO 404: Nome do modelo errado
            print(f"❌ Erro Crítico: O modelo '{modelo_nome}' não foi encontrado. Verifique a grafia.")
            continue
            
        except Exception as e:
            return f"❌ Erro desconhecido: {str(e)}"

    return "❌ Falha Total: Não foi possível processar após todas as tentativas."
