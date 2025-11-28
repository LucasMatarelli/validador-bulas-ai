import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
from PIL import Image
import io
import time

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Validador Belfar (Final)", page_icon="💊", layout="wide")

st.markdown("""
<style>
    .stButton>button {width: 100%; background-color: #0068c9; color: white;}
    .success-box {padding: 15px; background-color: #d4edda; border-radius: 5px; border: 1px solid #c3e6cb;}
    .error-box {padding: 15px; background-color: #f8d7da; border-radius: 5px; border: 1px solid #f5c6cb;}
</style>
""", unsafe_allow_html=True)

# --- FUNÇÃO DE INTELIGÊNCIA ROBUSTA ---
def try_gemini_generation(api_key, system_prompt, user_prompt, images):
    """
    Tenta gerar resposta usando múltiplos modelos em sequência.
    Se o Flash falhar, tenta o Pro, etc.
    """
    if not api_key:
        return "⚠️ Chave API não configurada."

    genai.configure(api_key=api_key)
    
    # Lista de modelos para tentar (do mais rápido para o mais forte)
    modelos_para_tentar = [
        'gemini-1.5-flash',       # Tentativa 1: O padrão rápido
        'gemini-1.5-flash-001',   # Tentativa 2: Versão congelada
        'gemini-1.5-pro',         # Tentativa 3: O mais potente
        'gemini-1.5-pro-001'      # Tentativa 4: Pro congelado
    ]
    
    ultimo_erro = ""

    for nome_modelo in modelos_para_tentar:
        try:
            model = genai.GenerativeModel(nome_modelo, system_instruction=system_prompt)
            content = [user_prompt] + images
            
            # Tenta gerar
            response = model.generate_content(content)
            return response.text # Se der certo, retorna e sai do loop
            
        except Exception as e:
            # Se der erro, guarda a mensagem e tenta o próximo
            ultimo_erro = str(e)
            continue
            
    return f"❌ Falha em todos os modelos. Erro final: {ultimo_erro}"

def pdf_to_images(uploaded_file):
    if not uploaded_file: return []
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
        return images
    except: return []

# --- INTERFACE ---
with st.sidebar:
    st.header("⚙️ Configuração")
    api_key = st.text_input("Cole sua Google API Key:", type="password")
    st.markdown("---")
    modo = st.selectbox("Selecione o Cenário:", [
        "1. Referência x BELFAR",
        "2. Conferência MKT",
        "3. Gráfica x Arte"
    ])
    st.info("Sistema operando com redundância de modelos (Flash/Pro).")

st.title(f"Validador: {modo}")

# --- LÓGICA DE UPLOAD ---
inputs_ok = False
if modo == "1. Referência x BELFAR":
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("Bula Referência", type="pdf")
    f2 = c2.file_uploader("Bula Belfar", type="pdf")
    if f1 and f2: inputs_ok = True

elif modo == "2. Conferência MKT":
    f1 = st.file_uploader("Arquivo MKT", type="pdf")
    checklist = st.text_area("Itens Obrigatórios:", "VENDA SOB PRESCRIÇÃO\nLogo Belfar\nFarm. Resp.")
    if f1: inputs_ok = True

elif modo == "3. Gráfica x Arte":
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("Arte Final", type="pdf")
    f2 = c2.file_uploader("Prova Gráfica", type="pdf")
    if f1 and f2: inputs_ok = True

# --- BOTÃO E EXECUÇÃO ---
if st.button("🚀 INICIAR ANÁLISE", disabled=not inputs_ok):
    with st.spinner("Analisando documentos... (Testando modelos disponíveis)"):
        
        # Preparação das imagens
        imgs = []
        if modo == "2. Conferência MKT":
            f1.seek(0)
            imgs = pdf_to_images(f1)
        else:
            f1.seek(0); f2.seek(0)
            imgs = pdf_to_images(f1) + pdf_to_images(f2)
            
        # Definição dos Prompts
        sys_msg = "Você é um Especialista em Farmácia e Regulação."
        user_msg = ""
        
        if "Referência" in modo:
            user_msg = "Compare o texto técnico das primeiras imagens (Referência) com as últimas (Belfar). Liste APENAS divergências de posologia, concentração ou contraindicação."
        elif "MKT" in modo:
            user_msg = f"Verifique visualmente se estes itens estão no documento: {checklist}"
        else:
            user_msg = "Compare visualmente Arte vs Prova Gráfica. Procure erros de impressão, manchas ou cortes de texto."

        # CHAMADA DA FUNÇÃO BLINDADA
        resultado = try_gemini_generation(api_key, sys_msg, user_msg, imgs)
        
        st.markdown("### Resultado da Análise")
        if "❌" in resultado:
            st.error(resultado)
        else:
            st.markdown(f'<div class="success-box">{resultado}</div>', unsafe_allow_html=True)
