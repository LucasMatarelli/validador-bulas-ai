import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import os

# ----------------- CONFIGURAÇÃO -----------------
st.set_page_config(
    page_title="Validador Visual (Gráfica)",
    page_icon="🎨",
    layout="wide"
)

st.title("🎨 Validador Visual: Gráfica x Arte")
st.markdown("Comparação visual usando **Gemini 2.0 Flash Lite Preview** (Rápido e Preciso).")

# ----------------- FUNÇÕES BACKEND -----------------
def get_gemini_model():
    """Tenta pegar o modelo mais rápido e novo primeiro."""
    api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None, "Sem Chave API"
    
    genai.configure(api_key=api_key)
    
    # LISTA DE MODELOS PREFERENCIAIS (Do seu prompt)
    # A lógica aqui é: Tenta o mais rápido/novo (Lite 2.0). Se der erro, cai pro Flash 1.5.
    
    try:
        # Tenta instanciar o Lite Preview primeiro (Super Rápido)
        model = genai.GenerativeModel("models/gemini-2.0-flash-lite-preview-02-05")
        return model, "⚡ Gemini 2.0 Flash Lite"
    except:
        try:
            # Fallback seguro (Tanque de Guerra)
            model = genai.GenerativeModel("models/gemini-1.5-flash")
            return model, "🛡️ Gemini 1.5 Flash (Fallback)"
        except Exception as e:
            return None, str(e)

def pdf_to_images(uploaded_file):
    """Converte PDF em imagens (1 imagem por página)."""
    if not uploaded_file: return []
    images = []
    try:
        file_bytes = uploaded_file.read()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            # Zoom de 2.0 é suficiente para ler textos pequenos sem ficar pesado
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            img_data = pix.tobytes("jpeg", jpg_quality=90)
            images.append(Image.open(io.BytesIO(img_data)))
        doc.close()
    except Exception as e:
        st.error(f"Erro ao converter PDF: {e}")
    return images

# ----------------- INTERFACE -----------------
col1, col2 = st.columns(2)
with col1:
    st.subheader("🖼️ Arte Aprovada (Ref)")
    f1 = st.file_uploader("Upload Arte (PDF/JPG)", type=["pdf", "jpg", "png"], key="art")
with col2:
    st.subheader("🖨️ Arquivo Gráfica (Cand)")
    f2 = st.file_uploader("Upload Gráfica (PDF/JPG)", type=["pdf", "jpg", "png"], key="print")

if st.button("🚀 Iniciar Conferência Visual"):
    if f1 and f2:
        model, model_name = get_gemini_model()
        if not model:
            st.error(f"Erro na API Gemini: {model_name}")
            st.stop()
            
        with st.spinner(f"Processando imagens com {model_name}..."):
            # Converte tudo para imagem
            imgs_ref = pdf_to_images(f1) if f1.name.lower().endswith(".pdf") else [Image.open(f1)]
            imgs_cand = pdf_to_images(f2) if f2.name.lower().endswith(".pdf") else [Image.open(f2)]
            
            # Limita a comparação para não estourar tokens se o PDF for gigante
            max_pages = min(len(imgs_ref), len(imgs_cand), 5)
            
            st.info(f"Analisando as primeiras {max_pages} páginas/imagens...")
            
            for i in range(max_pages):
                st.markdown(f"### 📄 Página {i+1}")
                c_img1, c_img2 = st.columns(2)
                c_img1.image(imgs_ref[i], caption="Arte Original", use_container_width=True)
                c_img2.image(imgs_cand[i], caption="Arquivo Gráfica", use_container_width=True)
                
                # Prompt Visual
                prompt = """
                Atue como um Especialista em Pré-Impressão Gráfica.
                Compare a imagem da ESQUERDA (Arte Original) com a da DIREITA (Arquivo Gráfica).
                
                Verifique RIGOROSAMENTE:
                1. Layout: Algo mudou de lugar?
                2. Fontes: As fontes parecem ter sido trocadas ou corrompidas?
                3. Logotipos: Estão presentes e na posição certa?
                4. Cores: Há alguma mudança drástica de cor?
                5. Textos: Há blocos de texto faltando ou sobrando?
                
                Se estiver tudo OK, diga apenas: "✅ Aprovado visualmente."
                Se houver erro, liste com bullet points ❌.
                """
                
                try:
                    response = model.generate_content([prompt, imgs_ref[i], imgs_cand[i]])
                    st.success("Relatório da IA:")
                    st.markdown(response.text)
                except Exception as e:
                    st.error(f"Erro na análise da página {i+1}: {e}")
                
                st.divider()
    else:
        st.warning("Por favor, faça o upload dos dois arquivos.")
