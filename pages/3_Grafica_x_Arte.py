import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import time
import os

# ----------------- CONFIGURAÇÃO -----------------
st.set_page_config(
    page_title="Validador Visual (Auto-Scan)",
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

def get_best_model_from_list():
    """
    VARRE a lista de modelos disponíveis na sua conta e pega o melhor disponível.
    Não adivinha nomes. Pega o real.
    """
    try:
        st.toast("Listando modelos disponíveis...", icon="🔍")
        
        # Pede a lista oficial para o Google
        all_models = list(genai.list_models())
        
        # Filtra apenas os que geram conteúdo (texto/imagem)
        usable_models = [m for m in all_models if 'generateContent' in m.supported_generation_methods]
        
        # LISTA DE PREFERÊNCIA (Do melhor para o "pior")
        # O código vai procurar nesta ordem dentro da lista que você tem acesso
        preference_keywords = [
            "gemini-1.5-flash",  # Rápido e bom para visão
            "gemini-2.0-flash",  # Novo (se tiver)
            "gemini-1.5-pro",    # Mais inteligente (mas mais lento)
            "gemini-pro-vision", # Antigo
            "gemini-1.0-pro"     # Básico
        ]
        
        selected_model = None
        
        # Tenta achar o melhor match
        for keyword in preference_keywords:
            for m in usable_models:
                if keyword in m.name:
                    selected_model = m.name
                    break
            if selected_model: break
            
        # Se não achou nenhum da preferência, pega o primeiro da lista que seja Gemini
        if not selected_model:
            for m in usable_models:
                if "gemini" in m.name:
                    selected_model = m.name
                    break
        
        if selected_model:
            return selected_model
        else:
            return "models/gemini-1.5-flash" # Fallback final
            
    except Exception as e:
        st.error(f"Erro ao listar modelos: {e}")
        return "models/gemini-1.5-flash"

def pdf_to_images(uploaded_file):
    images = []
    try:
        file_bytes = uploaded_file.read()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            # Zoom 2.0 = Boa qualidade sem estourar memória
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            img_data = pix.tobytes("jpeg", jpg_quality=85)
            images.append(Image.open(io.BytesIO(img_data)))
        return images
    except Exception as e:
        st.error(f"Erro PDF: {e}")
        return []

# ----------------- UI PRINCIPAL -----------------
st.title("🎨 Gráfica x Arte (Scanner de IA)")

if configure_api():
    # Detecta o modelo REAL disponível na sua conta
    with st.spinner("Procurando melhor IA disponível na sua conta..."):
        MODEL_NAME = get_best_model_from_list()
    
    st.info(f"🤖 **IA Selecionada Automaticamente:** `{MODEL_NAME}`")
    
    # Instancia
    try:
        model = genai.GenerativeModel(MODEL_NAME)
    except Exception as e:
        st.error(f"Erro fatal ao carregar {MODEL_NAME}: {e}")
        st.stop()

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
                        with st.spinner(f"Analisando Pág {i+1} com {MODEL_NAME}..."):
                            # Gera resposta
                            resp = model.generate_content([prompt, imgs1[i], imgs2[i]])
                            
                            if resp and resp.text:
                                if "✅" in resp.text:
                                    st.success(resp.text)
                                else:
                                    st.error("Divergências:")
                                    st.write(resp.text)
                            
                            # Pausa para evitar erro 429
                            time.sleep(3)
                            
                    except Exception as e:
                        st.error(f"Erro na análise: {e}")
                        if "429" in str(e):
                            st.warning("⚠️ Limite de velocidade. Aguardando 5s...")
                            time.sleep(5)
                    
                    st.divider()
        else:
            st.warning("Envie os arquivos.")
