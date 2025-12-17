import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import time

st.set_page_config(page_title="Visual (Auto-Hunter)", layout="wide")

# ----------------- CAÇADOR DE MODELOS (A LÓGICA DE OURO) -----------------
def hunt_for_flash_model():
    """
    Conecta na API, baixa a lista de 54 modelos e pega o PRIMEIRO
    que for da família Flash e suporte visão.
    """
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k]

    if not valid_keys:
        return None, None, "Sem chaves configuradas."

    for api_key in valid_keys:
        try:
            genai.configure(api_key=api_key)
            
            # Pede a lista REAL para o Google
            all_models = list(genai.list_models())
            
            # Filtra apenas os que geram conteúdo
            candidates = []
            for m in all_models:
                if 'generateContent' in m.supported_generation_methods:
                    candidates.append(m.name)
            
            # ESTRATÉGIA DE CAÇA:
            # Procura qualquer coisa que pareça com Flash 1.5
            for name in candidates:
                if "flash" in name.lower() and "1.5" in name and "8b" not in name:
                    return api_key, name, None # ACHAMOS O NOME CORRETO!
            
            # Se não achar Flash, tenta o Pro 1.5
            for name in candidates:
                if "pro" in name.lower() and "1.5" in name:
                    return api_key, name, None
            
            # Se não achar nada, pega o primeiro da lista
            if candidates:
                return api_key, candidates[0], None
                
        except Exception as e:
            continue

    return None, None, "Não foi possível encontrar um modelo compatível na lista."

# ----------------- UI -----------------
st.title("🎨 Gráfica x Arte (Auto-Hunter)")

# Executa a caça imediatamente
with st.spinner("🔍 Analisando os 54 modelos da sua conta..."):
    found_key, found_model_name, err = hunt_for_flash_model()

if found_key and found_model_name:
    st.success(f"🎯 Modelo Encontrado e Ativado: **{found_model_name}**")
    genai.configure(api_key=found_key)
    model = genai.GenerativeModel(found_model_name)
else:
    st.error(f"❌ Falha: {err}")
    st.stop()

# ----------------- UTILITÁRIOS -----------------
def pdf_to_images(uploaded_file):
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            images.append(Image.open(io.BytesIO(pix.tobytes("jpeg"))))
        return images
    except: return []

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Arte", type=["pdf", "jpg", "png"], key="f1")
f2 = c2.file_uploader("Gráfica", type=["pdf", "jpg", "png"], key="f2")

if st.button("🚀 Comparar Visualmente"):
    if f1 and f2:
        with st.spinner(f"Processando com {found_model_name}..."):
            imgs1 = pdf_to_images(f1) if f1.name.endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.endswith(".pdf") else [Image.open(f2)]
            
            max_p = min(len(imgs1), len(imgs2), 5)
            
            for i in range(max_p):
                st.markdown(f"### 📄 Página {i+1}")
                colA, colB = st.columns(2)
                colA.image(imgs1[i], use_container_width=True)
                colB.image(imgs2[i], use_container_width=True)
                
                try:
                    resp = model.generate_content([
                        "Atue como auditor gráfico. Compare as duas imagens. Se idêntico: '✅ Aprovado'. Se erro: Liste.",
                        imgs1[i], imgs2[i]
                    ])
                    
                    if "✅" in resp.text: st.success(resp.text)
                    else: st.error(resp.text)
                    
                    time.sleep(4)
                except Exception as e:
                    st.error(f"Erro: {e}")
                    if "429" in str(e): time.sleep(10)
                st.divider()
    else:
        st.warning("Envie os arquivos.")
