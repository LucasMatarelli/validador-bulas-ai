import streamlit as st
import fitz
import re
import unicodedata
from difflib import SequenceMatcher

st.set_page_config(page_title="Auditoria Belfar Enterprise", layout="wide")

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

def render_page_with_solid_marks(doc, page_num, divergent_words):
    """Desenha o marcatexto sólido na imagem, sem corromper o PDF original."""
    page = doc.load_page(page_num)
    
    # Adiciona a anotação amarela sólida
    for word in divergent_words:
        if word['page'] == page_num:
            annot = page.add_highlight_annot(word['rect'])
            annot.set_colors(stroke=(1, 1, 0)) # Amarelo puro
            annot.set_opacity(0.8)             # Opacidade alta (Sólido!)
            annot.update()
            
    # Gera a imagem da página já com a anotação
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    img_bytes = pix.tobytes("png")
    
    # IMPORTANTE: Deleta a anotação imediatamente para limpar a página original
    for annot in page.annots():
        page.delete_annot(annot)
        
    return img_bytes

# ----------------- INTERFACE -----------------
st.title("🛡️ Auditoria Visual Enterprise")

col_f1, col_f2 = st.columns(2)
f1 = col_f1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = col_f2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if f1 and f2:
    doc_ref = fitz.open("pdf", f1.getvalue())
    doc_bel = fitz.open("pdf", f2.getvalue())
    
    if st.button("🚀 Processar Auditoria"):
        with st.spinner("Analisando..."):
            divs = get_divergences(doc_ref, doc_bel)
            st.session_state['divs'] = divs
            st.session_state['processed'] = True

    if st.session_state.get('processed'):
        max_pag = max(len(doc_ref), len(doc_bel))
        st.write("### Comparação Visual (Scroll Vertical)")
        
        for i in range(max_pag):
            st.divider()
            c_r, c_b = st.columns(2)
            
            # Renderiza Referência
            if i < len(doc_ref):
                c_r.image(render_page_with_marks(doc_ref, i, st.session_state['divs']), use_container_width=True)
            
            # Renderiza Belfar
            if i < len(doc_bel):
                c_b.image(render_page_with_marks(doc_bel, i, st.session_state['divs']), use_container_width=True)
