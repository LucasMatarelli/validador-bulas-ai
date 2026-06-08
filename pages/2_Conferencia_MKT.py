import streamlit as st
import fitz
import re
import unicodedata
from difflib import SequenceMatcher

def clean_text(text):
    text = unicodedata.normalize('NFKD', text)
    return re.sub(r'[^\w\-]', '', text).lower().strip()

def extract_text(uploaded_file):
    doc = fitz.open("pdf", uploaded_file.getvalue())
    text_list = []
    for page in doc:
        # Extrai o texto ignorando a posição visual, apenas a ordem de leitura
        text = page.get_text("text", sort=True)
        words = text.split()
        for w in words:
            cleaned = clean_text(w)
            if cleaned: text_list.append(cleaned)
    return text_list

st.title("💊 Auditor de Conteúdo (Modo Texto)")
f1 = st.file_uploader("Bula Referência (Regulatória)", type=["pdf"])
f2 = st.file_uploader("Bula Marketing", type=["pdf"])

if st.button("🚀 Comparar Apenas Texto"):
    if f1 and f2:
        with st.spinner("Analisando fluxo de texto..."):
            t1 = extract_text(f1)
            t2 = extract_text(f2)
            
            matcher = SequenceMatcher(None, t1, t2)
            
            st.subheader("Diferenças de Conteúdo Encontradas:")
            divergencias = 0
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag != 'equal':
                    divergencias += 1
                    # Exibe apenas a divergência, sem despejar o texto todo
                    st.error(f"Divergência encontrada (Segmento {divergencias}):")
                    col1, col2 = st.columns(2)
                    col1.write(f"Referência: {' '.join(t1[i1:i2])}")
                    col2.write(f"Marketing: {' '.join(t2[j1:j2])}")
                    if divergencias > 20: # Limite para não travar a tela
                        st.warning("Muitas divergências. Verifique o arquivo.")
                        break
