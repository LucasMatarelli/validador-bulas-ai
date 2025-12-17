import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz
import io
import time

st.set_page_config(page_title="Visual (Dual Key)", layout="wide")

# ----------------- FUNÇÃO BLINDADA (ROTAÇÃO) -----------------
def try_generate_vision(model_name, inputs):
    """Tenta Chave 1 -> Falha -> Tenta Chave 2"""
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k]
    
    if not valid_keys: raise Exception("Sem chaves configuradas.")
    
    last_err = None
    for key in valid_keys:
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel(model_name)
            return model.generate_content(inputs)
        except Exception as e:
            last_err = e
            continue # Tenta a próxima chave silenciosamente
    raise last_err

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

st.title("🎨 Gráfica x Arte (Gemini Lite)")
st.caption("Modelo: gemini-2.0-flash-lite-preview-02-05 | Multi-Key Support")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Arte", type=["pdf", "jpg", "png"], key="f1")
f2 = c2.file_uploader("Gráfica", type=["pdf", "jpg", "png"], key="f2")

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
                Compare as duas imagens (Pré-impressão).
                Verifique: Layout, Fontes, Cores, Textos.
                Se idêntico: "✅ Aprovado". Senão, liste erros.
                """
                
                try:
                    # USA A FUNÇÃO DE ROTAÇÃO
                    resp = try_generate_vision(
                        "models/gemini-2.0-flash-lite-preview-02-05",
                        [prompt, imgs1[i], imgs2[i]]
                    )
                    
                    if "✅" in resp.text: st.success(resp.text)
                    else: st.error(resp.text)
                    
                    time.sleep(2) # Pausa leve
                    
                except Exception as e:
                    st.error(f"Erro (Todas as chaves esgotadas): {e}")
                
                st.divider()
    else:
        st.warning("Envie os arquivos.")
