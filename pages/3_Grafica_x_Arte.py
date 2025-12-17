import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import time

st.set_page_config(page_title="Visual (Força Bruta)", layout="wide")

# ----------------- CONFIGURAÇÃO ROBUSTA -----------------
# Lista de todos os nomes possíveis para o Gemini Flash
KNOWN_MODELS = [
    "models/gemini-1.5-flash",          # Padrão
    "models/gemini-1.5-flash-001",      # Versão Congelada (Geralmente a que salva)
    "models/gemini-1.5-flash-002",      # Versão Nova
    "models/gemini-1.5-flash-latest",   # Alias
    "models/gemini-1.5-flash-8b",       # Versão Leve
    "gemini-1.5-flash"                  # Nome Curto
]

def get_working_config():
    """
    Testa cada chave com cada modelo até achar um par que funcione.
    Não usa list_models (que está bloqueado na sua conta).
    """
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k]

    if not valid_keys:
        return None, None, "Sem chaves configuradas."

    # Teste de conexão rápido
    for api_key in valid_keys:
        genai.configure(api_key=api_key)
        
        for model_name in KNOWN_MODELS:
            try:
                # Tenta instanciar
                model = genai.GenerativeModel(model_name)
                # Tenta uma geração 'dummy' leve só para ver se a rota existe (evita erro 404 depois)
                # Isso gasta o mínimo de token possível
                model.generate_content("oi") 
                
                return api_key, model_name, None # SUCESSO!
            except Exception:
                continue # Tenta o próximo nome

    return None, None, "Nenhum modelo Gemini Flash funcionou nas suas chaves."

# ----------------- UI -----------------
st.title("🎨 Gráfica x Arte (Conexão Direta)")

# Executa a busca no carregamento da página
with st.spinner("Buscando rota de API válida..."):
    found_key, found_model, err = get_working_config()

if found_key and found_model:
    st.success(f"🔌 Conectado via: **{found_model}**")
    genai.configure(api_key=found_key)
    model = genai.GenerativeModel(found_model)
else:
    st.error(f"❌ Erro Fatal: {err}")
    st.info("Dica: Verifique se a API 'Generative Language' está ativada no Google Cloud Console.")
    st.stop()

# ----------------- UTILITÁRIOS -----------------
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

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Arte Aprovada", type=["pdf", "jpg", "png"], key="f1")
f2 = c2.file_uploader("Arquivo Gráfica", type=["pdf", "jpg", "png"], key="f2")

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
                Atue como Auditor de Qualidade Gráfica.
                Compare visualmente as duas imagens.
                
                VERIFIQUE:
                1. Layout e Diagramação.
                2. Fontes e Textos.
                3. Logotipos e Cores.
                
                Se idêntico: Responda "✅ Aprovado".
                Se erro: Liste os erros.
                """
                
                try:
                    resp = model.generate_content([prompt, imgs1[i], imgs2[i]])
                    if "✅" in resp.text: st.success(resp.text)
                    else: st.error(resp.text)
                    
                    time.sleep(4) # Pausa anti-cota
                    
                except Exception as e:
                    st.error(f"Erro na execução: {e}")
                    if "429" in str(e): 
                        st.warning("Aguardando cota...")
                        time.sleep(10)
                
                st.divider()
    else:
        st.warning("Envie os arquivos.")
