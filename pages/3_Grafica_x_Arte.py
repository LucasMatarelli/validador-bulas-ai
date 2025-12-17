import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import time
import os

# ----------------- CONFIGURAÇÃO -----------------
st.set_page_config(
    page_title="Validador Visual (Gemini Lite)",
    page_icon="🎨",
    layout="wide"
)

# ----------------- ESTILOS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; font-size: 16px; }
</style>
""", unsafe_allow_html=True)

# ----------------- FUNÇÕES DE BACKEND -----------------

def configure_api():
    try:
        api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            st.error("❌ Sem chave API.")
            return False
        genai.configure(api_key=api_key)
        return True
    except Exception as e:
        st.error(f"Erro config: {e}")
        return False

def pdf_to_images(uploaded_file):
    images = []
    try:
        file_bytes = uploaded_file.read()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            # Zoom 2.0 = Qualidade suficiente para leitura sem travar
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            img_data = pix.tobytes("jpeg", jpg_quality=85)
            images.append(Image.open(io.BytesIO(img_data)))
        return images
    except Exception as e:
        st.error(f"Erro PDF: {e}")
        return []

# ----------------- UI PRINCIPAL -----------------
st.title("🎨 Gráfica x Arte (Visual)")

if configure_api():
    # USANDO O MODELO LITE MAIS RECENTE DA SUA LISTA
    MODEL_NAME = "models/gemini-2.0-flash-lite-preview-02-05"
    
    st.info(f"🤖 Motor Visual Ativo: `{MODEL_NAME}`")
    
    # Instancia o modelo Lite
    try:
        model = genai.GenerativeModel(MODEL_NAME)
    except:
        st.warning(f"O modelo {MODEL_NAME} falhou. Tentando genérico...")
        model = genai.GenerativeModel("models/gemini-2.0-flash-lite-preview")

    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("Arte Aprovada", type=["pdf", "jpg", "png"], key="f1")
    f2 = c2.file_uploader("Arquivo Gráfica", type=["pdf", "jpg", "png"], key="f2")

    if st.button("🚀 Comparar Visualmente"):
        if f1 and f2:
            with st.spinner("Processando imagens..."):
                # Converte tudo
                imgs1 = pdf_to_images(f1) if f1.name.lower().endswith(".pdf") else [Image.open(f1)]
                imgs2 = pdf_to_images(f2) if f2.name.lower().endswith(".pdf") else [Image.open(f2)]
                
                if not imgs1 or not imgs2:
                    st.error("Erro ao carregar imagens.")
                    st.stop()

                # Limita a 5 páginas
                max_p = min(len(imgs1), len(imgs2), 5)
                
                for i in range(max_p):
                    st.markdown(f"### 📄 Página {i+1}")
                    col_a, col_b = st.columns(2)
                    col_a.image(imgs1[i], caption="Arte Original", use_container_width=True)
                    col_b.image(imgs2[i], caption="Gráfica", use_container_width=True)
                    
                    prompt = """
                    Atue como Auditor de Qualidade Gráfica.
                    Compare as duas imagens.
                    
                    VERIFIQUE:
                    1. Layout e Diagramação (deslocamentos).
                    2. Fontes (trocas ou corrupção).
                    3. Logotipos e Cores.
                    4. Textos (blocos faltando ou sobrando).
                    
                    RESULTADO:
                    - Se idêntico: "✅ Visualmente Aprovado".
                    - Se houver erro: Liste os erros com detalhes.
                    """
                    
                    try:
                        with st.spinner(f"Analisando Pág {i+1}..."):
                            # Gera resposta
                            resp = model.generate_content([prompt, imgs1[i], imgs2[i]])
                            
                            if resp and resp.text:
                                if "✅" in resp.text:
                                    st.success(resp.text)
                                else:
                                    st.error("Divergências:")
                                    st.write(resp.text)
                            
                            # Pausa obrigatória para modelos Preview/Lite (evitar 429)
                            time.sleep(5)
                            
                    except Exception as e:
                        st.error(f"Erro na análise: {e}")
                        if "429" in str(e):
                            st.warning("⚠️ Limite de velocidade (Cota Gratuita). Aguardando 10s...")
                            time.sleep(10)
                    
                    st.divider()
        else:
            st.warning("Envie os arquivos.")
