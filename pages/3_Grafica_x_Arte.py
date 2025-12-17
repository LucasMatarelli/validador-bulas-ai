import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import time
import os

# ----------------- CONFIGURAÇÃO -----------------
st.set_page_config(
    page_title="Validador Visual (Blindado)",
    page_icon="🎨",
    layout="wide"
)

# ----------------- ESTILOS -----------------
st.markdown("""
<style>
    header[data-testid="stHeader"] { display: none !important; }
    .main .block-container { padding-top: 20px !important; }
    .stButton>button { width: 100%; background-color: #55a68e; color: white; font-weight: bold; border-radius: 10px; height: 55px; font-size: 16px; }
    .status-box { padding: 10px; border-radius: 5px; background-color: #e3f2fd; border: 1px solid #90caf9; color: #0d47a1; margin-bottom: 15px; }
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
            # Zoom 2.0 = Qualidade suficiente
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            img_data = pix.tobytes("jpeg", jpg_quality=85)
            images.append(Image.open(io.BytesIO(img_data)))
        return images
    except Exception as e:
        st.error(f"Erro PDF: {e}")
        return []

def generate_with_retry(model, prompt, images, max_retries=3):
    """
    Tenta gerar a resposta. Se der erro 429 (Cota), espera e tenta de novo.
    """
    for attempt in range(max_retries):
        try:
            return model.generate_content([prompt, *images])
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "quota" in error_str.lower():
                wait_time = (attempt + 1) * 5  # Espera 5s, 10s, 15s...
                st.warning(f"⚠️ Tráfego alto no Google (Erro 429). Tentando novamente em {wait_time}s... (Tentativa {attempt+1}/{max_retries})")
                time.sleep(wait_time)
            else:
                raise e # Se for outro erro, para tudo.
    return None

# ----------------- UI PRINCIPAL -----------------
st.title("🎨 Gráfica x Arte (Visual)")

if configure_api():
    # DEFINIÇÃO FIXA DO MODELO ESTÁVEL
    # Usamos o alias genérico que o Google redireciona para a versão estável atual
    MODEL_NAME = "models/gemini-1.5-flash"
    
    st.markdown(f"""
    <div class='status-box'>
        🤖 <b>Motor Ativo:</b> <code>{MODEL_NAME}</code><br>
        🛡️ <b>Proteção Anti-Erro 429:</b> Ativada (Retry Automático)
    </div>
    """, unsafe_allow_html=True)
    
    try:
        model = genai.GenerativeModel(MODEL_NAME)
    except:
        st.error("Falha ao instanciar modelo. Verifique sua API Key.")
        st.stop()

    c1, c2 = st.columns(2)
    f1 = c1.file_uploader("Arte Aprovada", type=["pdf", "jpg", "png"], key="f1")
    f2 = c2.file_uploader("Arquivo Gráfica", type=["pdf", "jpg", "png"], key="f2")

    if st.button("🚀 Comparar Visualmente"):
        if f1 and f2:
            with st.spinner("Processando imagens..."):
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
                    Atue como Auditor Gráfico. Compare as duas imagens.
                    
                    VERIFIQUE:
                    1. Layout (posições, margens).
                    2. Fontes (estilo, tamanho).
                    3. Logotipos e Cores.
                    4. Textos (faltando/sobrando).
                    
                    RESPOSTA:
                    - Se idêntico: "✅ Visualmente Aprovado".
                    - Se houver erro: Liste com detalhes.
                    """
                    
                    try:
                        with st.spinner(f"Analisando Pág {i+1}..."):
                            # Chama a função com Retry Automático
                            resp = generate_with_retry(model, prompt, [imgs1[i], imgs2[i]])
                            
                            if resp and resp.text:
                                if "✅" in resp.text:
                                    st.success(resp.text)
                                else:
                                    st.error("Divergências:")
                                    st.write(resp.text)
                            else:
                                st.error("Falha ao obter resposta após várias tentativas.")
                            
                            # Pausa extra de segurança entre páginas
                            time.sleep(2)
                            
                    except Exception as e:
                        st.error(f"Erro fatal na página {i+1}: {e}")
                    
                    st.divider()
        else:
            st.warning("Envie os arquivos.")
