import streamlit as st
from mistralai import Mistral
import google.generativeai as genai
import fitz
import io
import os
from PIL import Image

st.set_page_config(page_title="Conferência MKT", layout="wide")

# --- FUNÇÃO BLINDADA ---
def get_best_gemini():
    candidates = [
        "models/gemini-1.5-flash-latest",
        "models/gemini-1.5-flash",
        "models/gemini-1.5-flash-001",
        "models/gemini-2.0-flash-lite-preview-02-05",
        "models/gemini-pro"
    ]
    for model_name in candidates:
        try:
            return genai.GenerativeModel(model_name)
        except: continue
    return genai.GenerativeModel("gemini-1.5-flash")

try:
    if st.secrets.get("GEMINI_API_KEY"):
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    client = Mistral(api_key=st.secrets["MISTRAL_API_KEY"])
except:
    st.error("Configure as chaves API.")
    st.stop()

def get_text_from_pdf(file):
    doc = fitz.open(stream=file.read(), filetype="pdf")
    text = ""
    for page in doc: text += page.get_text() + "\n"
    
    if len(text) < 50:
        file.seek(0)
        images = []
        for page in doc:
            pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5))
            img_data = pix.tobytes("jpeg")
            images.append(Image.open(io.BytesIO(img_data)))
        try:
            model = get_best_gemini() # <--- USA FUNÇÃO BLINDADA
            resp = model.generate_content(["OCR fiel:", *images])
            return resp.text
        except: return ""
    return text

st.title("📋 Conferência MKT (Regras)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Bula Anvisa (Regra)", type="pdf", key="mkt1")
f2 = c2.file_uploader("Arte Marketing (Análise)", type="pdf", key="mkt2")

if st.button("🚀 Validar Regras"):
    if f1 and f2:
        with st.spinner("Processando..."):
            t1 = get_text_from_pdf(f1)
            t2 = get_text_from_pdf(f2)
            
            prompt = f"""
            Atue como Revisor de Marketing Farmacêutico.
            Verifique se a ARTE DE MARKETING respeita o conteúdo da BULA ANVISA.
            
            Verifique:
            1. Ortografia e Gramática na Arte.
            2. Se alguma contraindicação importante foi omitida na Arte.
            3. Se a Posologia está igual à Bula.
            
            --- BULA ANVISA ---
            {t1[:15000]}
            
            --- ARTE MKT ---
            {t2[:15000]}
            """
            
            try:
                resp = client.chat.complete(
                    model="mistral-small-latest",
                    messages=[{"role": "user", "content": prompt}]
                )
                st.info("Relatório de Conformidade:")
                st.markdown(resp.choices[0].message.content)
            except Exception as e:
                st.error(f"Erro: {e}")
