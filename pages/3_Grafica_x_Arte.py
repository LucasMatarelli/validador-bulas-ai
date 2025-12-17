import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import time
import os

st.set_page_config(page_title="Validador Visual", page_icon="🎨", layout="wide")

# --- ESTILOS ---
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; }
</style>
""", unsafe_allow_html=True)

# --- BACKEND BLINDADO ---
def configure_api():
    try:
        api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            st.error("❌ Sem GEMINI_API_KEY.")
            return False
        genai.configure(api_key=api_key)
        return True
    except: return False

def get_working_visual_model():
    """
    Retorna o melhor modelo visual disponível, testando um por um.
    Evita erros 404 e 429 procurando o melhor candidato.
    """
    # Ordem de preferência: Lite (Rápido) -> Latest -> Stable -> Pro
    candidates = [
        "models/gemini-2.0-flash-lite-preview-02-05", # O mais rápido atual
        "models/gemini-1.5-flash-latest",             # O mais atualizado
        "models/gemini-1.5-flash-001",                # O mais compatível
        "models/gemini-1.5-flash"                     # O padrão
    ]
    
    for model_name in candidates:
        try:
            # Tenta instanciar para ver se não dá 404 na sua conta
            model = genai.GenerativeModel(model_name)
            return model, model_name
        except:
            continue
            
    # Se tudo falhar, retorna o Flash padrão
    return genai.GenerativeModel("models/gemini-1.5-flash"), "gemini-1.5-flash"

def pdf_to_images(uploaded_file):
    images = []
    try:
        file_bytes = uploaded_file.read()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            img_data = pix.tobytes("jpeg", jpg_quality=85)
            images.append(Image.open(io.BytesIO(img_data)))
        return images
    except: return []

# --- UI ---
st.title("🎨 Gráfica x Arte (Auto-Detect)")

if configure_api():
    # Detecta o modelo que funciona NA SUA CONTA
    model, model_name = get_working_visual_model()
    st.info(f"🤖 Motor Visual Ativo: `{model_name}`")

    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("Arte Original", type=["pdf", "jpg", "png"], key="f1")
    f2 = c2.file_uploader("Gráfica (Impressão)", type=["pdf", "jpg", "png"], key="f2")

    if st.button("🚀 Comparar Visualmente"):
        if f1 and f2:
            with st.spinner("Processando imagens..."):
                imgs1 = pdf_to_images(f1) if f1.name.lower().endswith(".pdf") else [Image.open(f1)]
                imgs2 = pdf_to_images(f2) if f2.name.lower().endswith(".pdf") else [Image.open(f2)]
                
                max_p = min(len(imgs1), len(imgs2), 5)
                
                for i in range(max_p):
                    st.markdown(f"### 📄 Página {i+1}")
                    col_a, col_b = st.columns(2)
                    col_a.image(imgs1[i], caption="Arte", use_container_width=True)
                    col_b.image(imgs2[i], caption="Gráfica", use_container_width=True)
                    
                    prompt = """
                    Atue como Especialista de Pré-Impressão. Compare as duas imagens.
                    
                    VERIFIQUE RIGOROSAMENTE:
                    1. Layout (deslocamentos).
                    2. Fontes (trocas/corrupção).
                    3. Logotipos e Cores.
                    4. Textos (faltando/sobrando).
                    
                    Se idêntico: "✅ Aprovado".
                    Se erro: Liste com detalhes.
                    """
                    
                    try:
                        resp = model.generate_content([prompt, imgs1[i], imgs2[i]])
                        
                        if resp and resp.text:
                            if "✅" in resp.text: st.success(resp.text)
                            else: st.error(resp.text)
                        
                        # Pausa para evitar cota
                        time.sleep(3)
                        
                    except Exception as e:
                        st.error(f"Erro: {e}")
                        if "429" in str(e): 
                            st.warning("Aguardando cota...")
                            time.sleep(5)
                    
                    st.divider()
        else:
            st.warning("Envie os arquivos.")
