import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
from PIL import Image
import io

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Validador Belfar (Auto)", page_icon="💊", layout="wide")

st.markdown("""
<style>
    .stButton>button {width: 100%; background-color: #28a745; color: white;}
    .status-box {padding: 10px; border-radius: 5px; margin-bottom: 10px; font-size: 14px;}
    .success {background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb;}
    .error {background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb;}
</style>
""", unsafe_allow_html=True)

# --- FUNÇÃO INTELIGENTE: DESCOBRIR MODELO ---
def get_best_model(api_key):
    """Consulta a API para saber qual modelo está disponível para esta chave."""
    if not api_key: return None, "Sem chave"
    
    try:
        genai.configure(api_key=api_key)
        # Lista todos os modelos disponíveis para a chave
        available = [m.name for m in genai.list_models()]
        
        # Prioridade: Flash 1.5 -> Pro 1.5 -> Flash 001
        preferencias = [
            'models/gemini-1.5-flash',
            'models/gemini-1.5-flash-latest',
            'models/gemini-1.5-flash-001',
            'models/gemini-1.5-pro',
            'models/gemini-1.5-pro-latest',
            'models/gemini-1.5-pro-001'
        ]
        
        # Tenta achar o melhor modelo que ESTÁ na lista da conta
        for pref in preferencias:
            if pref in available:
                return pref, None # Achou! Retorna o nome exato
        
        # Se não achou os preferidos, pega qualquer um que seja Gemini 1.5
        for model_name in available:
            if 'gemini-1.5' in model_name:
                return model_name, None
                
        return None, f"Nenhum modelo Gemini 1.5 encontrado. Disponíveis: {available}"
        
    except Exception as e:
        return None, str(e)

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
    api_key = st.text_input("Sua Chave Google (AIza...):", type="password")
    
    # Check de conexão imediato
    model_name = None
    if api_key:
        found_model, err = get_best_model(api_key)
        if found_model:
            st.success(f"✅ Conectado! Usando: {found_model.replace('models/', '')}")
            model_name = found_model
        else:
            st.error(f"❌ Erro de conta: {err}")
            
    st.markdown("---")
    modo = st.selectbox("Cenário:", ["1. Referência x BELFAR", "2. Conferência MKT", "3. Gráfica x Arte"])

st.title(f"Validador: {modo}")

# --- UPLOADS ---
inputs_ok = False
if modo == "1. Referência x BELFAR":
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("Ref", type="pdf"); f2 = c2.file_uploader("Belfar", type="pdf")
    if f1 and f2: inputs_ok = True
elif modo == "2. Conferência MKT":
    f1 = st.file_uploader("Arquivo", type="pdf")
    checklist = st.text_area("Checklist", "VENDA SOB PRESCRIÇÃO\nLogo Belfar")
    if f1: inputs_ok = True
elif modo == "3. Gráfica x Arte":
    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("Arte", type="pdf"); f2 = c2.file_uploader("Prova", type="pdf")
    if f1 and f2: inputs_ok = True

# --- EXECUÇÃO ---
if st.button("🚀 INICIAR", disabled=not (inputs_ok and model_name)):
    if not model_name:
        st.error("Não podemos iniciar: Modelo não identificado.")
    else:
        with st.spinner(f"Analisando usando {model_name}..."):
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(model_name)
            
            # Prepara imagens
            imgs = []
            if "MKT" in modo:
                f1.seek(0); imgs = pdf_to_images(f1)
            else:
                f1.seek(0); f2.seek(0); imgs = pdf_to_images(f1) + pdf_to_images(f2)
            
            # Prompt
            prompt = ""
            if "Referência" in modo: prompt = "Compare o texto técnico das primeiras imagens (Ref) com as últimas (Belfar). Aponte divergências."
            elif "MKT" in modo: prompt = f"Verifique visualmente estes itens: {checklist}"
            else: prompt = "Compare visualmente Arte vs Prova. Procure defeitos de impressão."
            
            try:
                res = model.generate_content([prompt] + imgs)
                st.markdown(f'<div class="status-box success">{res.text}</div>', unsafe_allow_html=True)
            except Exception as e:
                st.error(f"Erro na geração: {e}")
