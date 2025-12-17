import streamlit as st
import google.generativeai as genai
from PIL import Image
import fitz  # PyMuPDF
import io
import time
import os

st.set_page_config(page_title="Gráfica x Arte", layout="wide")

# Configuração Segura
try:
    api_key = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
    else:
        st.error("Sem chave API configurada.")
        st.stop()
except Exception as e:
    st.error(f"Erro na configuração: {e}")
    st.stop()

def get_working_model():
    """Tenta encontrar o modelo Flash correto disponível na conta."""
    # Lista de tentativas (do mais novo para o mais antigo)
    candidates = [
        "models/gemini-1.5-flash",
        "models/gemini-1.5-flash-latest",
        "models/gemini-1.5-flash-001",
        "models/gemini-pro-vision"  # Último recurso (mais antigo)
    ]
    
    for model_name in candidates:
        try:
            model = genai.GenerativeModel(model_name)
            # Teste rápido "dummy" para ver se o modelo responde sem erro 404
            # Não gastamos tokens reais aqui, apenas instanciamos
            return model, model_name
        except:
            continue
            
    # Se falhar tudo, retorna o padrão e deixa o erro aparecer na tela
    return genai.GenerativeModel("models/gemini-1.5-flash"), "gemini-1.5-flash"

def pdf_to_images(uploaded_file):
    images = []
    try:
        file_bytes = uploaded_file.read()
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            # Zoom 2.0 para boa resolução
            pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
            img_data = pix.tobytes("jpeg", jpg_quality=85)
            images.append(Image.open(io.BytesIO(img_data)))
        return images
    except Exception as e:
        st.error(f"Erro ao processar PDF: {e}")
        return []

# --- UI ---
st.title("🎨 Gráfica x Arte (Visual)")

# Seleciona o modelo automaticamente
model, model_name = get_working_model()
st.caption(f"🤖 Motor Visual Ativo: **{model_name}**")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Arte Aprovada", type=["pdf", "jpg", "png"])
f2 = c2.file_uploader("Arquivo Gráfica", type=["pdf", "jpg", "png"])

if st.button("🚀 Comparar Visualmente"):
    if f1 and f2:
        with st.spinner("Processando imagens..."):
            # Converte tudo
            imgs1 = pdf_to_images(f1) if f1.name.endswith(".pdf") else [Image.open(f1)]
            imgs2 = pdf_to_images(f2) if f2.name.endswith(".pdf") else [Image.open(f2)]
            
            if not imgs1 or not imgs2:
                st.error("Erro ao carregar imagens.")
                st.stop()

            # Limita a 5 páginas para não demorar
            max_p = min(len(imgs1), len(imgs2), 5)
            
            for i in range(max_p):
                st.markdown(f"### 📄 Página {i+1}")
                col_a, col_b = st.columns(2)
                col_a.image(imgs1[i], caption="Arte Original", use_container_width=True)
                col_b.image(imgs2[i], caption="Gráfica", use_container_width=True)
                
                prompt = """
                Atue como Especialista de Pré-Impressão.
                Compare as duas imagens lado a lado.
                
                Verifique RIGOROSAMENTE:
                1. Layout (elementos deslocados, margens).
                2. Fontes (mudança de estilo, corrompidas).
                3. Logotipos e Cores (mudanças visíveis).
                4. Blocos de texto sumidos ou corrompidos.
                
                Se estiver idêntico, responda APENAS: "✅ Visualmente Aprovado".
                Se houver erro, descreva em tópicos curtos.
                """
                
                try:
                    with st.spinner(f"Analisando Pág {i+1}..."):
                        # O Gemini 1.5 Flash aceita múltiplas imagens no input
                        resp = model.generate_content([prompt, imgs1[i], imgs2[i]])
                        
                        if resp and resp.text:
                            if "✅" in resp.text:
                                st.success(resp.text)
                            else:
                                st.error("Divergências Encontradas:")
                                st.write(resp.text)
                        
                        # Pausa anti-spam de API
                        time.sleep(1.5)
                        
                except Exception as e:
                    st.error(f"Erro na análise (Pág {i+1}): {e}")
                    # Tenta mostrar erro detalhado se for de cota
                    if "429" in str(e):
                        st.warning("Limite de velocidade da API atingido. Aguarde alguns segundos e tente de novo.")
                
                st.divider()
    else:
        st.warning("Envie os arquivos.")
