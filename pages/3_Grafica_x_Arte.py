import streamlit as st
import google.generativeai as genai
import requests

st.set_page_config(page_title="Relatório Forense de Chaves", layout="wide")

st.title("🕵️ Diagnóstico Forense de API")
st.markdown("""
Este painel testa a saúde das suas chaves diretamente nos servidores do Google.
Ele vai revelar se o problema é **Bloqueio (403)**, **Não Encontrado (404)** ou **Cota (429)**.
""")

# --- INFORMAÇÕES DE COTA (Sua Pergunta) ---
with st.expander("📊 QUAIS SÃO OS MEUS LIMITES DIÁRIOS? (Plano Gratuito)", expanded=True):
    st.markdown("""
    Se você usa o **Google AI Studio (Free Tier)**, seus limites para o **Gemini 1.5 Flash** são:
    
    * **15 Requisições por Minuto (RPM)** (Velocidade)
    * **1.500 Requisições por Dia (RPD)** (Volume)
    * **1 Milhão de Tokens por Minuto (TPM)** (Tamanho do texto)
    
    *Se você exceder 15 RPM, recebe erro 429. Se exceder 1.500 no dia, a chave para até amanhã.*
    """)

# --- FUNÇÃO DE TESTE REAL ---
def testar_chave_bruta(nome_chave, api_key):
    if not api_key:
        st.warning(f"⚠️ {nome_chave}: Não configurada no secrets.toml")
        return

    st.markdown(f"### Testando: `{nome_chave}`")
    st.write(f"🔑 Final da chave: `...{api_key[-4:]}`")
    
    genai.configure(api_key=api_key)
    
    # 1. TESTE DE LISTAGEM (Permissão Básica)
    st.write("1️⃣ Tentando listar modelos permitidos...")
    try:
        modelos = list(genai.list_models())
        nomes = [m.name for m in modelos]
        st.success(f"✅ Conexão OK! A conta tem acesso a {len(nomes)} modelos.")
    except Exception as e:
        err = str(e)
        if "403" in err:
            st.error("❌ ERRO 403 (PROIBIDO): A API 'Generative Language' não está ativada neste projeto do Google Cloud.")
            st.markdown("[👉 Clique aqui para ativar a API no Google Console](https://console.cloud.google.com/apis/library/generativelanguage.googleapis.com)")
        elif "400" in err:
            st.error("❌ ERRO 400 (INVÁLIDO): A chave API está incorreta ou mal formatada.")
        else:
            st.error(f"❌ Falha na Listagem: {err}")
            
    # 2. TESTE DE GERAÇÃO (Vida ou Morte)
    st.write("2️⃣ Tentando gerar 'Oi' com Gemini 1.5 Flash...")
    try:
        model = genai.GenerativeModel("models/gemini-1.5-flash")
        resp = model.generate_content("Oi")
        st.success("✅ GERAÇÃO BEM SUCEDIDA! O modelo respondeu.")
        st.balloons()
    except Exception as e:
        err = str(e)
        if "404" in err:
            st.error("❌ ERRO 404 (NÃO ENCONTRADO): O modelo 'gemini-1.5-flash' não existe para esta chave. Sua chave pode ser do Vertex AI (Empresarial) em vez do AI Studio.")
        elif "429" in err:
            st.warning("⚠️ ERRO 429 (COTA): A chave funciona, mas você estourou o limite de hoje.")
        else:
            st.error(f"❌ Erro Fatal na Geração: {err}")

    st.divider()

# --- BOTÃO DE AÇÃO ---
if st.button("🚨 RODAR DIAGNÓSTICO AGORA"):
    k1 = st.secrets.get("GEMINI_API_KEY")
    k2 = st.secrets.get("GEMINI_API_KEY2")
    
    testar_chave_bruta("GEMINI_API_KEY", k1)
    testar_chave_bruta("GEMINI_API_KEY2", k2)
