import streamlit as st
import fitz
import re
import unicodedata
import pandas as pd
from difflib import SequenceMatcher

# ----------------- FUNÇÕES DE APOIO -----------------
def clean_text(text):
    text = unicodedata.normalize('NFKD', text)
    return re.sub(r'[^\w\-]', '', text).lower().strip()

def render_page_as_image(doc, page_num):
    """Converte uma página de PDF em imagem (pixmap) para exibição."""
    page = doc.load_page(page_num)
    pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)) # Qualidade de visualização
    return pix.tobytes("png")

def extract_text(doc):
    """Extrai texto estruturado para comparação."""
    full_text = []
    for p in doc:
        text = p.get_text("text", sort=True)
        for w in text.split():
            cleaned = clean_text(w)
            if cleaned: full_text.append(cleaned)
    return full_text

# ----------------- UI DO STREAMLIT -----------------
st.set_page_config(layout="wide")
st.title("🛡️ Validador Profissional: Visualizador Lado a Lado")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Bula Referência (PDF)", type=["pdf"])
f2 = c2.file_uploader("Bula BELFAR / MKT (PDF)", type=["pdf"])

if f1 and f2:
    doc_ref = fitz.open("pdf", f1.getvalue())
    doc_bel = fitz.open("pdf", f2.getvalue())
    
    # Navegação de páginas
    max_pages = max(len(doc_ref), len(doc_bel))
    page_select = st.slider("Escolha a página para conferência visual:", 0, max_pages - 1, 0)
    
    st.divider()
    
    # Exibição Lado a Lado
    col_vis1, col_vis2 = st.columns(2)
    with col_vis1:
        st.subheader("Referência")
        if page_select < len(doc_ref):
            st.image(render_page_as_image(doc_ref, page_select), use_container_width=True)
    with col_vis2:
        st.subheader("BELFAR / MKT")
        if page_select < len(doc_bel):
            st.image(render_page_as_image(doc_bel, page_select), use_container_width=True)
            
    st.divider()
    
    # Auditoria de Conteúdo abaixo
    if st.button("🚀 Executar Auditoria de Texto (Sem pintar PDF)"):
        with st.spinner("Comparando conteúdos..."):
            t1 = extract_text(doc_ref)
            t2 = extract_text(doc_bel)
            matcher = SequenceMatcher(None, t1, t2)
            
            divergencias = []
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag != 'equal':
                    divergencias.append({
                        "Tipo": tag.upper(),
                        "Referência": " ".join(t1[i1:i2]),
                        "BELFAR": " ".join(t2[j1:j2])
                    })
            
            if divergencias:
                st.warning(f"Foram encontradas {len(divergencias)} divergências de texto:")
                st.table(pd.DataFrame(divergencias))
            else:
                st.success("✅ Textos idênticos!")
