import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import time

st.set_page_config(page_title="Gráfica x Arte", layout="wide")

# Configuração Segura
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
except:
    st.error("Sem chave API.")
    st.stop()

def pdf_to_images(uploaded_file):
    images = []
    file_bytes = uploaded_file.read()
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    for page in doc:
        # Zoom 2.0 para boa resolução
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        img_data = pix.tobytes("jpeg", jpg_quality=85)
        images.append(Image.open(io.BytesIO(img_data)))
    return images

st.title("🎨 Gráfica x Arte (Visual)")
st.warning("Usando Modelo: **Gemini 1.5 Flash** (Estável e Rápido)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Arte Aprovada", type=["pdf", "jpg", "png"])
f2 = c2.file_uploader("Arquivo Gráfica", type=["pdf", "jpg", "png"])

if st.button("🚀 Comparar Visualmente"):
    if f1 and f2:
        with st.spinner("Processando imagens..."):
            # Converte tudo
            imgs1 = pdf_to_images(f1) if f1.name.endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.endswith(".pdf") else [Image.open(f2)]
            
            # Limita a 5 páginas para não demorar
            max_p = min(len(imgs1), len(imgs2), 5)
            
            # Modelo ESTÁVEL (Sem erro 429)
            model = genai.GenerativeModel("models/gemini-1.5-flash")
            
            for i in range(max_p):
                st.markdown(f"### 📄 Página {i+1}")
                col_a, col_b = st.columns(2)
                col_a.image(imgs1[i], caption="Arte Original", use_container_width=True)
                col_b.image(imgs2[i], caption="Gráfica", use_container_width=True)
                
                prompt = """
                Atue como Especialista de Pré-Impressão.
                Compare as duas imagens.
                
                Verifique:
                1. Layout (elementos deslocados).
                2. Fontes (mudança de estilo).
                3. Logotipos e Cores.
                4. Blocos de texto sumidos ou corrompidos.
                
                Se estiver idêntico, responda apenas: "✅ OK".
                Se houver erro, descreva.
                """
                
                try:
                    with st.spinner(f"Analisando Pág {i+1}..."):
                        resp = model.generate_content([prompt, imgs1[i], imgs2[i]])
                        st.success("Análise da IA:")
                        st.write(resp.text)
                        
                        # Pequena pausa para evitar limite de requisições por segundo
                        time.sleep(2)
                        
                except Exception as e:
                    st.error(f"Erro na análise: {e}")
                st.divider()
    else:
        st.warning("Envie os arquivos.")
