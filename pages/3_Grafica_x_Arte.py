import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import time
import os

# ----------------- CONFIGURAÇÃO -----------------
st.set_page_config(
    page_title="Validador Visual (Auto-Detect)",
    page_icon="🎨",
    layout="wide"
)

# ----------------- ESTILOS CSS -----------------
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
            st.error("❌ Sem chave API configurada.")
            return False
        genai.configure(api_key=api_key)
        return True
    except Exception as e:
        st.error(f"Erro na configuração: {e}")
        return False

def get_best_available_model():
    """
    Lista os modelos disponíveis na sua conta e escolhe o melhor para visão.
    Prioridade: Flash > 1.5 Pro > Pro Vision (Antigo)
    """
    try:
        # Pede a lista real para o Google
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        # Ordem de preferência
        preferencias = [
            "gemini-1.5-flash",          # O ideal (Rápido)
            "gemini-1.5-flash-latest",   # Variação
            "gemini-1.5-flash-001",      # Versão congelada
            "gemini-1.5-pro",            # Mais potente (mas mais lento)
            "gemini-pro-vision"          # Antigo (Legacy)
        ]
        
        # 1. Tenta achar o nome exato na lista
        for pref in preferencias:
            for model in available_models:
                if pref in model:
                    return model # Retorna o nome oficial (ex: models/gemini-1.5-flash-001)
        
        # 2. Se não achar nenhum da lista, pega qualquer um que tenha 'vision' ou 'flash'
        for model in available_models:
            if "vision" in model or "flash" in model:
                return model
                
        # 3. Último caso: o primeiro da lista
        if available_models:
            return available_models[0]
            
        return "models/gemini-1.5-flash" # Fallback cego
        
    except Exception as e:
        # Se listar falhar (erro de permissão), tenta o Flash direto
        return "models/gemini-1.5-flash"

def pdf_to_images(uploaded_file):
    images = []
    try:
        file_bytes = uploaded_file.read()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            # Zoom 2.0 para boa resolução
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            img_data = pix.tobytes("jpeg", jpg_quality=85)
            images.append(Image.open(io.BytesIO(img_data)))
        return images
    except Exception as e:
        st.error(f"Erro ao processar PDF: {e}")
        return []

# ----------------- UI PRINCIPAL -----------------
st.title("🎨 Gráfica x Arte (Visual)")

if configure_api():
    # Detecta o modelo automaticamente
    model_name = get_best_available_model()
    st.info(f"🤖 **Motor IA Detectado:** `{model_name}`")
    
    try:
        model = genai.GenerativeModel(model_name)
    except:
        st.warning("Falha ao carregar modelo detectado. Tentando 'gemini-1.5-flash' forçado.")
        model = genai.GenerativeModel("gemini-1.5-flash")

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

                # Limita a 5 páginas para não demorar
                max_p = min(len(imgs1), len(imgs2), 5)
                
                for i in range(max_p):
                    st.markdown(f"### 📄 Página {i+1}")
                    col_a, col_b = st.columns(2)
                    col_a.image(imgs1[i], caption="Arte Original", use_container_width=True)
                    col_b.image(imgs2[i], caption="Gráfica", use_container_width=True)
                    
                    prompt = """
                    Atue como Especialista de Pré-Impressão Gráfica.
                    Compare as duas imagens fornecidas.
                    
                    Verifique RIGOROSAMENTE:
                    1. Layout (elementos deslocados, margens).
                    2. Fontes (mudança de estilo, corrompidas).
                    3. Logotipos e Cores (mudanças visíveis).
                    4. Blocos de texto sumidos ou corrompidos.
                    
                    Se estiver idêntico, responda APENAS: "✅ Visualmente Aprovado".
                    Se houver erro, descreva em tópicos curtos e diretos.
                    """
                    
                    try:
                        with st.spinner(f"Analisando Pág {i+1}..."):
                            # O Gemini aceita [prompt, img1, img2]
                            resp = model.generate_content([prompt, imgs1[i], imgs2[i]])
                            
                            if resp and resp.text:
                                if "✅" in resp.text:
                                    st.success(resp.text)
                                else:
                                    st.error("Divergências Encontradas:")
                                    st.write(resp.text)
                            
                            # Pausa anti-spam de API (Rate Limit)
                            time.sleep(2)
                            
                    except Exception as e:
                        st.error(f"Erro na análise (Pág {i+1}): {e}")
                        if "429" in str(e):
                            st.warning("Limite de velocidade da API atingido. Aguardando...")
                            time.sleep(5)
                    
                    st.divider()
        else:
            st.warning("Envie os arquivos.")
