import streamlit as st
import fitz
import re
import unicodedata
from difflib import SequenceMatcher

# ----------------- CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Auditoria Visual Belfar", layout="wide")

# ----------------- FUNÇÕES DE APOIO -----------------
def clean_text(text):
    text = unicodedata.normalize('NFKD', text)
    return re.sub(r'[^\w\-]', '', text).lower().strip()

def get_divergences(doc_ref, doc_bel):
    """Extrai texto e mapeia onde estão as divergências."""
    def get_words(doc):
        data = []
        for p_idx, page in enumerate(doc):
            for w in page.get_text("words"):
                data.append({"page": p_idx, "rect": fitz.Rect(w[:4]), "clean": clean_text(w[4])})
        return data

    words_ref = get_words(doc_ref)
    words_bel = get_words(doc_bel)
    
    text_ref = [w["clean"] for w in words_ref]
    text_bel = [w["clean"] for w in words_bel]
    
    matcher = SequenceMatcher(None, text_ref, text_bel)
    divergentes = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            divergentes.extend(words_ref[i1:i2])
            divergentes.extend(words_bel[j1:j2])
    return divergentes

def render_page_with_marks(doc, page_num, divergent_words):
    """Gera imagem da página com marcação amarela (sem editar o PDF original)."""
    if page_num >= len(doc): return None
    page = doc.load_page(page_num)
    
    # Desenha o marcatexto sólido (amarelo)
    for word in divergent_words:
        if word['page'] == page_num:
            annot = page.add_highlight_annot(word['rect'])
            annot.set_colors(stroke=(1, 1, 0)) # Amarelo vibrante
            annot.set_opacity(0.8)             # Sólido
            annot.update()
            
    # Gera a imagem
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    img_bytes = pix.tobytes("png")
    
    # Limpa as anotações para não corromper o PDF original
    for annot in page.annots():
        page.delete_annot(annot)
        
    return img_bytes

# ----------------- INTERFACE -----------------
st.title("🛡️ Auditoria Visual Enterprise")

col1, col2 = st.columns(2)
f1 = col1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = col2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if f1 and f2:
    doc_ref = fitz.open("pdf", f1.getvalue())
    doc_bel = fitz.open("pdf", f2.getvalue())
    
    if st.button("🚀 Processar Auditoria"):
        with st.spinner("Auditando..."):
            divs = get_divergences(doc_ref, doc_bel)
            st.session_state['divs'] = divs
            st.session_state['processed'] = True
            st.success("Auditoria pronta!")

    if st.session_state.get('processed'):
        st.write("### Comparação Visual (Scroll Vertical)")
        max_pag = max(len(doc_ref), len(doc_bel))
        
        for i in range(max_pag):
            st.divider()
            c_r, c_b = st.columns(2)
            
            # Referência
            if i < len(doc_ref):
                c_r.caption(f"Referência - Página {i+1}")
                c_r.image(render_page_with_marks(doc_ref, i, st.session_state['divs']), use_container_width=True)
            
            # Belfar
            if i < len(doc_bel):
                c_b.caption(f"BELFAR - Página {i+1}")
                c_b.image(render_page_with_marks(doc_bel, i, st.session_state['divs']), use_container_width=True)
