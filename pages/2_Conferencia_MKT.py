import streamlit as st
import fitz
import re
import unicodedata
from difflib import SequenceMatcher

st.set_page_config(page_title="Validador Belfar Side-by-Side", layout="wide")

# ----------------- FUNÇÕES DE APOIO -----------------
def clean_text(text):
    text = unicodedata.normalize('NFKD', text)
    return re.sub(r'[^\w\-]', '', text).lower().strip()

# ----------------- MOTOR DE AUDITORIA (LOGIC) -----------------
def get_divergences(doc_ref, doc_bel):
    """Retorna lista de blocos divergentes sem tocar no PDF original."""
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

# ----------------- MOTOR DE RENDERIZAÇÃO (VISUAL) -----------------
def render_page_with_marks(doc, page_num, divergent_words):
    """Renderiza a página como imagem com marcações amarelas."""
    if page_num >= len(doc): return None
    
    page = doc.load_page(page_num)
    
    # Adiciona anotações na página em memória temporária
    for word in divergent_words:
        if word['page'] == page_num:
            annot = page.add_highlight_annot(word['rect'])
            annot.set_colors(stroke=(1, 1, 0)) # Amarelo (R,G,B)
            annot.set_opacity(0.8)             # Opacidade alta (sólido)
            annot.update()
            
    # Gera a imagem
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    img_bytes = pix.tobytes("png")
    
    # Limpa as anotações para não corromper o documento na próxima renderização
    for annot in page.annots():
        page.delete_annot(annot)
        
    return img_bytes

# ----------------- UI -----------------
st.title("🛡️ Auditoria de Bulas: Comparação Lado a Lado")

col1, col2 = st.columns(2)
f1 = col1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = col2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if f1 and f2:
    doc_ref = fitz.open("pdf", f1.getvalue())
    doc_bel = fitz.open("pdf", f2.getvalue())
    
    if st.button("🚀 Iniciar Auditoria Visual"):
        with st.spinner("Analisando divergências..."):
            divs = get_divergences(doc_ref, doc_bel)
            st.session_state['divs'] = divs
            st.session_state['processed'] = True

    if st.session_state.get('processed'):
        max_pag = max(len(doc_ref), len(doc_bel))
        st.write("### Auditoria Visual (Role para comparar)")
        
        for i in range(max_pag):
            st.divider()
            c_r, c_b = st.columns(2)
            
            with c_r:
                st.caption(f"Referência - Página {i+1}")
                st.image(render_page_with_marks(doc_ref, i, st.session_state['divs']), use_container_width=True)
            
            with c_b:
                st.caption(f"BELFAR - Página {i+1}")
                st.image(render_page_with_marks(doc_bel, i, st.session_state['divs']), use_container_width=True)
