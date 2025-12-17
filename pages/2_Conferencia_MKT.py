import streamlit as st
import google.generativeai as genai
from mistralai import Mistral
import fitz
import io
from PIL import Image

st.set_page_config(page_title="Conferência MKT", layout="wide")

try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    mistral_client = Mistral(api_key=st.secrets["MISTRAL_API_KEY"])
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
        model = genai.GenerativeModel("models/gemini-1.5-flash")
        resp = model.generate_content(["OCR fiel:", *images])
        return resp.text
    return text

st.title("📋 Conferência MKT (Regras & Ortografia)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Referência (ANVISA)", type="pdf")
f2 = c2.file_uploader("Arte MKT", type="pdf")

if st.button("🚀 Validar MKT"):
    if f1 and f2:
        with st.spinner("Lendo arquivos..."):
            t1 = get_text_from_pdf(f1)
            t2 = get_text_from_pdf(f2)
            
        with st.spinner("🤖 Mistral validando regras..."):
            prompt = f"""
            Atue como Revisor de Marketing Farmacêutico.
            Analise o Texto da ARTE MKT em comparação com a ANVISA.
            
            Verifique:
            1. ERROS DE PORTUGUÊS (Acentos, digitação).
            2. SEÇÕES FALTANTES (Compare com a referência).
            3. INFORMAÇÕES CRÍTICAS (Posologia, Cuidados).
            
            --- ANVISA ---
            {t1[:15000]}
            
            --- ARTE MKT ---
            {t2[:15000]}
            """
            
            resp = mistral_client.chat.complete(
                model="mistral-large-latest",
                messages=[{"role": "user", "content": prompt}]
            )
            
            st.info("Relatório de Validação")
            st.markdown(resp.choices[0].message.content)
