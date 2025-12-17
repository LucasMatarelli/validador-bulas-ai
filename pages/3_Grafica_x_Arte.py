import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import time

st.set_page_config(page_title="Visual (Scanner)", layout="wide")

# ----------------- FUNÇÃO DE DESCOBERTA REAL -----------------
def find_working_model_and_key():
    """
    1. Testa as chaves API.
    2. Pergunta ao Google: 'Quais modelos eu tenho?'.
    3. Retorna o primeiro modelo 'Flash' da lista que suporta visão.
    """
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k]

    if not valid_keys:
        return None, None, "Sem chaves configuradas."

    for api_key in valid_keys:
        try:
            genai.configure(api_key=api_key)
            
            # Pede a lista oficial para a API (O PULO DO GATO)
            all_models = list(genai.list_models())
            
            # Filtra modelos que existem, suportam conteúdo e são Flash (Rápido/Vision)
            # Evita 'gemini-1.0' que não lê imagem e 'exp' que tem cota zero
            valid_models = []
            for m in all_models:
                name = m.name
                methods = m.supported_generation_methods
                
                if 'generateContent' in methods:
                    # Prioridade: Flash 1.5 (Estável)
                    if 'gemini-1.5-flash' in name and 'exp' not in name and '8b' not in name:
                        valid_models.insert(0, name) # Coloca no topo
                    # Fallback: Pro 1.5
                    elif 'gemini-1.5-pro' in name and 'exp' not in name:
                        valid_models.append(name)
            
            if valid_models:
                # Retorna a chave que funcionou e o nome oficial do modelo
                return api_key, valid_models[0], None
                
        except Exception as e:
            continue # Tenta a próxima chave

    return None, None, "Não foi possível listar modelos em nenhuma chave."

# ----------------- UI -----------------
st.title("🎨 Gráfica x Arte (Varredura Automática)")

# Executa a descoberta no início
found_key, found_model_name, error_msg = find_working_model_and_key()

if found_key and found_model_name:
    st.success(f"🔌 Conectado: **{found_model_name}**")
    # Configura globalmente com a chave vencedora
    genai.configure(api_key=found_key)
    model = genai.GenerativeModel(found_model_name)
else:
    st.error(f"❌ Falha Fatal: {error_msg}")
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
        with st.spinner("Processando..."):
            imgs1 = pdf_to_images(f1) if f1.name.lower().endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.lower().endswith(".pdf") else [Image.open(f2)]
            
            max_p = min(len(imgs1), len(imgs2), 5)
            
            for i in range(max_p):
                st.markdown(f"### 📄 Página {i+1}")
                col_a, col_b = st.columns(2)
                col_a.image(imgs1[i], caption="Arte", use_container_width=True)
                col_b.image(imgs2[i], caption="Gráfica", use_container_width=True)
                
                prompt = """
                Atue como Auditor Gráfico.
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
                    
                    # Pausa anti-cota (429)
                    time.sleep(5)
                    
                except Exception as e:
                    st.error(f"Erro na execução: {e}")
                    if "429" in str(e): time.sleep(10)
                
                st.divider()
    else:
        st.warning("Envie os arquivos.")
