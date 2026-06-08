import streamlit as st
import fitz
import re
import unicodedata
from difflib import SequenceMatcher

def clean_text(text):
    text = unicodedata.normalize('NFKD', text)
    # Remove tudo que não for alfanumérico ou hífen
    return re.sub(r'[^\w\-]', '', text).lower().strip()

def extract_text_flow(uploaded_file):
    doc = fitz.open("pdf", uploaded_file.getvalue())
    full_text = []
    for page in doc:
        # Extrai o texto na ordem de leitura, ignorando posição visual
        text = page.get_text("text", sort=True)
        # Quebra em palavras limpas mantendo a ordem
        words = text.split()
        for w in words:
            cleaned = clean_text(w)
            if cleaned: full_text.append(cleaned)
    return full_text

st.title("💊 Validador de Bulas (Modo Texto Puro)")
f1 = st.file_uploader("Bula Referência", type=["pdf"])
f2 = st.file_uploader("Bula Comparação", type=["pdf"])

if st.button("🚀 Comparar Conteúdo"):
    if f1 and f2:
        t1 = extract_text_flow(f1)
        t2 = extract_text_flow(f2)
        
        matcher = SequenceMatcher(None, t1, t2)
        
        # Exibe as divergências sem pintar o PDF (evita erros visuais)
        st.subheader("Divergências Encontradas:")
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag != 'equal':
                st.error(f"Divergência: '{' '.join(t1[i1:i2])}' vs '{' '.join(t2[j1:j2])}'")
