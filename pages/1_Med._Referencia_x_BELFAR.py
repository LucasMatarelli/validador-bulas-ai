import streamlit as st
from mistralai import Mistral
import google.generativeai as genai
import fitz  # PyMuPDF
import io
import os
from PIL import Image

st.set_page_config(page_title="Ref x BELFAR", layout="wide")

# --- FUNÇÃO BLINDADA: SELETOR DE MODELO ---
def get_best_gemini():
    """Testa qual modelo Gemini está funcionando na sua conta e retorna o primeiro válido."""
    candidates = [
        "models/gemini-1.5-flash-latest",       # Alias mais comum
        "models/gemini-1.5-flash",              # Padrão
        "models/gemini-1.5-flash-001",          # Versionado
        "models/gemini-2.0-flash-lite-preview-02-05", # Lite (Rápido)
        "models/gemini-pro"                     # Fallback antigo
    ]
    for model_name in candidates:
        try:
            return genai.GenerativeModel(model_name)
        except: continue
    return genai.GenerativeModel("gemini-1.5-flash") # Última tentativa

# Configuração de APIs
try:
    if st.secrets.get("GEMINI_API_KEY"):
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    client = Mistral(api_key=st.secrets["MISTRAL_API_KEY"])
except:
    st.error("Configure as chaves GEMINI_API_KEY e MISTRAL_API_KEY no secrets.toml")
    st.stop()

def get_text_from_pdf(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc: text += page.get_text() + "\n"
    
    # Se não tiver texto (escaneado), usa o Gemini Blindado
    if len(text) < 50:
        file.seek(0)
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            img_data = pix.tobytes("jpeg")
            images.append(Image.open(io.BytesIO(img_data)))
        
        try:
            model = get_best_gemini() # <--- USA A FUNÇÃO BLINDADA
            resp = model.generate_content(["Transcreva o texto destas imagens fielmente:", *images])
            return resp.text
        except Exception as e:
            return f"Erro no OCR: {e}"
    return text

st.title("💊 Med. Referência x BELFAR")
st.caption("Comparação de Texto Puro via IA")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Referência (PDF)", type="pdf", key="f1")
f2 = c2.file_uploader("Belfar (PDF)", type="pdf", key="f2")

if st.button("🚀 Iniciar Comparação"):
    if f1 and f2:
        with st.spinner("Extraindo textos (pode usar OCR se necessário)..."):
            t1 = get_text_from_pdf(f1)
            t2 = get_text_from_pdf(f2)
        
        with st.spinner("🌪️ Mistral analisando divergências..."):
            prompt = f"""
            Você é um Auditor Farmacêutico RÍGIDO.
            Compare o texto REF com o texto CAND (Belfar).
            
            REGRAS:
            1. Liste APENAS as divergências de conteúdo (palavras erradas, números trocados, frases faltantes).
            2. Ignore formatação e quebras de linha.
            3. Se houver erro, mostre: "Na Referência diz X, no Belfar diz Y".
            
            --- REF ---
            {t1[:20000]}
            
            --- CAND ---
            {t2[:20000]}
            """
            
            try:
                resp = client.chat.complete(
                    model="mistral-small-latest",
                    messages=[{"role": "user", "content": prompt}]
                )
                st.success("Relatório de Divergências:")
                st.markdown(resp.choices[0].message.content)
            except Exception as e:
                st.error(f"Erro na IA: {e}")
    else:
        st.warning("Envie os dois arquivos.")
