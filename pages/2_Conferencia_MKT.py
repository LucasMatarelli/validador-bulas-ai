import streamlit as st
import fitz
import re
import unicodedata
from difflib import SequenceMatcher

# ----------------- FUNÇÕES DE APOIO -----------------
def clean_text(text):
    text = unicodedata.normalize('NFKD', text)
    return re.sub(r'[^\w\-]', '', text).lower().strip()

def get_mismatched_rects(doc, other_doc_words):
    """Retorna lista de retângulos que devem ser pintados de amarelo."""
    # Lógica simplificada: extrai texto e coordenadas
    words_data = []
    for p_idx, page in enumerate(doc):
        for w in page.get_text("words"):
            words_data.append({"page": p_idx, "rect": fitz.Rect(w[:4]), "clean": clean_text(w[4])})
    return words_data

st.set_page_config(layout="wide")
st.title("🛡️ Validador com Marcação Amarela Inteligente")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Bula Referência (PDF)", type=["pdf"])
f2 = c2.file_uploader("Bula BELFAR (PDF)", type=["pdf"])

if f1 and f2:
    doc_ref = fitz.open("pdf", f1.getvalue())
    doc_bel = fitz.open("pdf", f2.getvalue())
    
    # Extração para comparação
    def get_text_list(doc):
        full = []
        for p in doc:
            for w in p.get_text("words"):
                full.append(clean_text(w[4]))
        return full

    t1 = get_text_list(doc_ref)
    t2 = get_text_list(doc_bel)
    matcher = SequenceMatcher(None, t1, t2)
    
    # Mapear divergências
    divergent_words = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            divergent_words.extend(t1[i1:i2])
            divergent_words.extend(t2[j1:j2])

    page_select = st.slider("Página:", 0, max(len(doc_ref), len(doc_bel)) - 1, 0)
    
    # Renderização com Amarelo (Sem erro de Quads)
    def render_with_highlights(doc, page_num, divergent_list):
        if page_num >= len(doc): return None
        page = doc.load_page(page_num)
        
        # PINTA O AMARELO NA IMAGEM (Overlay)
        words = page.get_text("words")
        for w in words:
            if clean_text(w[4]) in divergent_list:
                # Desenha o retângulo no PDF (temporário)
                page.add_highlight_annot(fitz.Rect(w[:4]))
        
        # Renderiza a página com as anotações
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        return pix.tobytes("png")

    col_vis1, col_vis2 = st.columns(2)
    with col_vis1:
        st.subheader("Referência")
        st.image(render_with_highlights(doc_ref, page_select, divergent_words), use_container_width=True)
    with col_vis2:
        st.subheader("BELFAR")
        st.image(render_with_highlights(doc_bel, page_select, divergent_words), use_container_width=True)
