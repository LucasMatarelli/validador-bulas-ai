import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import time
import os

st.set_page_config(page_title="Visual (Auto-Discovery)", layout="wide")

# ----------------- FUNÇÃO DE AUTO-DESCOBERTA -----------------
def get_available_vision_model(api_key):
    """
    Em vez de adivinhar, LISTA os modelos disponíveis na conta
    e escolhe o melhor compatível com visão.
    """
    genai.configure(api_key=api_key)
    try:
        # Pede a lista oficial para o Google
        all_models = list(genai.list_models())
        
        # Filtra apenas os que geram conteúdo
        candidates = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
        
        # 1. Prioridade: Flash 1.5 (Estável)
        for m in candidates:
            if "gemini-1.5-flash" in m and "exp" not in m and "8b" not in m:
                return m # Ex: models/gemini-1.5-flash-001
        
        # 2. Prioridade: Pro 1.5 (Se Flash não existir)
        for m in candidates:
            if "gemini-1.5-pro" in m and "exp" not in m:
                return m
                
        # 3. Prioridade: Legacy (Gemini Pro Vision)
        for m in candidates:
            if "gemini-pro-vision" in m:
                return m
        
        # 4. Se não achar nada específico, pega o primeiro da lista
        if candidates:
            return candidates[0]
            
    except Exception as e:
        print(f"Erro ao listar modelos: {e}")
        
    # Último recurso se a listagem falhar
    return "models/gemini-1.5-flash"

# ----------------- FUNÇÃO DE GERAÇÃO ROBUSTA -----------------
def generate_vision_content(prompt, img_objects):
    keys = [st.secrets.get("GEMINI_API_KEY"), st.secrets.get("GEMINI_API_KEY2")]
    valid_keys = [k for k in keys if k]

    if not valid_keys:
        raise Exception("Sem chaves API configuradas.")

    last_error = None

    for key in valid_keys:
        try:
            # 1. Descobre o modelo exato que essa chave aceita
            model_name = get_available_vision_model(key)
            
            # 2. Configura e Instancia
            genai.configure(api_key=key)
            model = genai.GenerativeModel(model_name)
            
            # 3. Tenta gerar
            response = model.generate_content([prompt, *img_objects])
            return response, model_name
            
        except Exception as e:
            last_error = e
            # Se for erro de cota (429) ou não encontrado (404), tenta a próxima chave
            continue
            
    raise last_error

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

# ----------------- UI -----------------
st.title("🎨 Gráfica x Arte (Auto-Discovery)")
st.caption("Motor: Detecção automática do modelo disponível na sua conta.")

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
                Atue como Auditor de Pré-Impressão.
                Compare visualmente as duas imagens.
                
                VERIFIQUE:
                1. Layout e Diagramação.
                2. Fontes e Textos.
                3. Logotipos e Cores.
                
                Se idêntico: Responda "✅ Aprovado".
                Se erro: Liste os erros.
                """
                
                try:
                    with st.spinner("IA Analisando..."):
                        # Chama a função inteligente
                        resp, used_model = generate_vision_content(prompt, [imgs1[i], imgs2[i]])
                        
                        # Mostra qual modelo foi usado (para você saber)
                        if i == 0:
                            st.toast(f"Conectado em: {used_model}", icon="🤖")
                        
                        if "✅" in resp.text:
                            st.success(resp.text)
                        else:
                            st.error(resp.text)
                        
                        time.sleep(4) # Pausa de segurança
                        
                except Exception as e:
                    st.error(f"Erro Fatal: {e}")
                    st.warning("Dica: Verifique se suas chaves API têm a API 'Generative Language' ativada no Google Cloud Console.")
                
                st.divider()
    else:
        st.warning("Envie os arquivos.")
