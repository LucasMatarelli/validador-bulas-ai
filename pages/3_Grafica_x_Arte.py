import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import time

st.set_page_config(page_title="Visual (High Quota)", layout="wide")

# ----------------- CAÇADOR COM PRIORIDADE DE COTA -----------------
def hunt_for_stable_flash_model():
    """
    Baixa a lista de modelos da conta e escolhe o melhor para VISÃO.
    PRIORIDADE ABSOLUTA: Família 1.5 Flash (Cota Alta).
    EVITA: Família 2.0/2.5 (Cota Baixa).
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
            
            # Filtra apenas modelos que geram conteúdo
            candidates = [m.name for m in all_models if 'generateContent' in m.supported_generation_methods]
            
            # --- LÓGICA DE FILTRAGEM INTELIGENTE ---
            
            # 1. Tenta achar o 1.5 Flash ESPECÍFICO (O rei da cota)
            # Procura por variações: gemini-1.5-flash-001, gemini-1.5-flash-002, etc.
            for name in candidates:
                if "gemini-1.5-flash" in name and "8b" not in name and "exp" not in name:
                    return api_key, name, None

            # 2. Se não achar, tenta o 1.5 Pro (Mais lento, mas boa cota)
            for name in candidates:
                if "gemini-1.5-pro" in name and "exp" not in name:
                    return api_key, name, None
            
            # 3. Só em último caso pega os modelos novos (2.0/2.5) que têm pouca cota
            for name in candidates:
                if "flash" in name and ("2.0" in name or "2.5" in name):
                    return api_key, name, None
            
            # 4. Desespero: Pega o primeiro da lista
            if candidates:
                return api_key, candidates[0], None
                
        except Exception as e:
            continue

    return None, None, "Não foi possível encontrar nenhum modelo compatível."

# ----------------- UI -----------------
st.title("🎨 Gráfica x Arte (Cota Otimizada)")

# Executa a caça focada no 1.5
with st.spinner("🔍 Buscando modelo Gemini 1.5 (Alta Cota)..."):
    found_key, found_model_name, err = hunt_for_stable_flash_model()

if found_key and found_model_name:
    # Mostra qual modelo foi escolhido para você conferir
    if "1.5" in found_model_name:
        st.success(f"✅ Conectado ao modelo estável: **{found_model_name}**")
    else:
        st.warning(f"⚠️ Atenção: Apenas modelos novos encontrados (**{found_model_name}**). Cota pode ser baixa.")
        
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
                
                prompt = """
                Atue como auditor gráfico. Compare as duas imagens.
                Se idêntico: '✅ Aprovado'. Se erro: Liste.
                """
                
                try:
                    resp = model.generate_content([prompt, imgs1[i], imgs2[i]])
                    if "✅" in resp.text: st.success(resp.text)
                    else: st.error(resp.text)
                    
                    # Pausa de 4s é suficiente para o modelo 1.5
                    time.sleep(4)
                except Exception as e:
                    st.error(f"Erro: {e}")
                    if "429" in str(e): time.sleep(10)
                st.divider()
    else:
        st.warning("Envie os arquivos.")
