import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import time

st.set_page_config(page_title="Visual (Blindado)", layout="wide")

# ----------------- FUNÇÃO DE ROTAÇÃO DE CHAVES -----------------
def try_generate_vision(prompt, img_objects):
    """
    Tenta usar a Chave 1 com Gemini 1.5 Flash.
    Se der erro (429/Cota), troca para Chave 2 automaticamente.
    """
    # Lista de chaves
    keys = [
        st.secrets.get("GEMINI_API_KEY"),
        st.secrets.get("GEMINI_API_KEY2")
    ]
    # Filtra chaves vazias
    valid_keys = [k for k in keys if k]

    if not valid_keys:
        raise Exception("Nenhuma chave API configurada no secrets.toml")

    last_error = None

    # O MODELO QUE FUNCIONA (O 2.0-lite está com cota zero na sua conta)
    SAFE_MODEL = "models/gemini-1.5-flash"

    for i, key in enumerate(valid_keys):
        try:
            # Tenta configurar a chave atual
            genai.configure(api_key=key)
            model = genai.GenerativeModel(SAFE_MODEL)
            
            # Tenta gerar
            response = model.generate_content([prompt, *img_objects])
            return response
            
        except Exception as e:
            last_error = e
            # Se der erro de cota (429), tenta a próxima chave do loop
            if "429" in str(e) or "404" in str(e):
                continue
            else:
                # Se for outro erro, continua tentando também
                continue
    
    # Se sair do loop, todas as chaves falharam
    raise last_error

# ----------------- UTILITÁRIOS -----------------
def pdf_to_images(uploaded_file):
    images = []
    try:
        file_bytes = uploaded_file.read()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            # Zoom 2.0 é o equilíbrio ideal para o Gemini 1.5
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            img_data = pix.tobytes("jpeg", jpg_quality=85)
            images.append(Image.open(io.BytesIO(img_data)))
        return images
    except: return []

# ----------------- UI -----------------
st.title("🎨 Gráfica x Arte (Gemini 1.5 Flash)")
st.caption("Motor: models/gemini-1.5-flash | Sistema Multi-Key Ativo")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Arte", type=["pdf", "jpg", "png"], key="f1")
f2 = c2.file_uploader("Gráfica", type=["pdf", "jpg", "png"], key="f2")

if st.button("🚀 Comparar Visualmente"):
    if f1 and f2:
        with st.spinner("Processando imagens..."):
            imgs1 = pdf_to_images(f1) if f1.name.lower().endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.lower().endswith(".pdf") else [Image.open(f2)]
            
            # Limita páginas para economizar a cota
            max_p = min(len(imgs1), len(imgs2), 5)
            
            for i in range(max_p):
                st.markdown(f"### 📄 Página {i+1}")
                col_a, col_b = st.columns(2)
                col_a.image(imgs1[i], caption="Arte", use_container_width=True)
                col_b.image(imgs2[i], caption="Gráfica", use_container_width=True)
                
                prompt = """
                Atue como Especialista de Pré-Impressão.
                Compare visualmente as duas imagens.
                
                VERIFIQUE:
                1. Layout (deslocamentos).
                2. Fontes (trocas ou quebras).
                3. Logotipos e Cores.
                4. Textos (blocos sumidos).
                
                Se idêntico: Responda apenas "✅ Aprovado".
                Se houver erro: Liste os erros.
                """
                
                try:
                    # Chama a função que troca de chave sozinha
                    resp = try_generate_vision(prompt, [imgs1[i], imgs2[i]])
                    
                    if "✅" in resp.text:
                        st.success(resp.text)
                    else:
                        st.error(resp.text)
                    
                    # Pausa de segurança (obrigatória para conta free)
                    time.sleep(4)
                    
                except Exception as e:
                    st.error(f"Erro Crítico (Todas as chaves falharam): {e}")
                
                st.divider()
    else:
        st.warning("Envie os arquivos.")
