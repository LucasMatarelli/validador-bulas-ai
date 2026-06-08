import streamlit as st
import fitz
import re
import unicodedata
from difflib import SequenceMatcher

# ----------------- CONFIGURAÇÕES INICIAIS -----------------
st.set_page_config(page_title="Auditoria Vertical Belfar", layout="wide")

def clean_text(text):
    text = unicodedata.normalize('NFKD', text)
    return re.sub(r'[^\w\-]', '', text).lower().strip()

# ----------------- MOTOR DE EXTRAÇÃO E COMPARAÇÃO -----------------
def run_audit(doc_ref, doc_bel):
    """Extrai palavras e encontra divergências sem renderizar nada ainda."""
    def get_words(doc):
        data = []
        for p_idx, page in enumerate(doc):
            for w in page.get_text("words"):
                data.append({"page": p_idx, "rect": fitz.Rect(w[:4]), "clean": clean_text(w[4])})
        return data

    words_ref = get_words(doc_ref)
    words_bel = get_words(doc_bel)
    
    # Compara texto bruto
    text_ref = [w["clean"] for w in words_ref]
    text_bel = [w["clean"] for w in words_bel]
    
    matcher = SequenceMatcher(None, text_ref, text_bel)
    divergentes = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            divergentes.extend(words_ref[i1:i2])
            divergentes.extend(words_bel[j1:j2])
            
    return divergentes, words_ref, words_bel

# ----------------- MOTOR DE RENDERIZAÇÃO VERTICAL -----------------
def get_clean_page_image(doc, page_num, divergent_words):
    """Gera imagem da página com amarelo, sem corromper o PDF."""
    page = doc.load_page(page_num)
    
    # Pinta o amarelo temporariamente na página
    for word in divergent_words:
        if word['page'] == page_num:
            page.add_highlight_annot(word['rect'])
            
    # Gera a imagem
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    img_bytes = pix.tobytes("png")
    
    # Limpa as anotações imediatamente para evitar erros de memória
    for annot in page.annots():
        page.delete_annot(annot)
        
    return img_bytes

# ----------------- INTERFACE -----------------
st.title("🛡️ Auditoria de Bulas - Fluxo Vertical")
c1, c2 = st.columns(2)
f1 = c1.file_uploader("Bula Referência", type=["pdf"])
f2 = c2.file_uploader("Bula BELFAR", type=["pdf"])

if f1 and f2:
    doc_ref = fitz.open("pdf", f1.getvalue())
    doc_bel = fitz.open("pdf", f2.getvalue())
    
    if st.button("🚀 Processar"):
        with st.spinner("Analisando todas as páginas..."):
            divs, _, _ = run_audit(doc_ref, doc_bel)
            st.session_state['divs'] = divs
            st.session_state['processed'] = True

    if st.session_state.get('processed'):
        st.subheader("Visualização Vertical")
        st.info("Role para baixo para conferir os documentos lado a lado.")
        
        max_pag = max(len(doc_ref), len(doc_bel))
        
        # Loop para mostrar uma página embaixo da outra
        for i in range(max_pag):
            st.markdown(f"--- ### Página {i+1}")
            c_left, c_right = st.columns(2)
            
            with c_left:
                if i < len(doc_ref):
                    st.image(get_clean_page_image(doc_ref, i, st.session_state['divs']), use_container_width=True)
            with c_right:
                if i < len(doc_bel):
                    st.image(get_clean_page_image(doc_bel, i, st.session_state['divs']), use_container_width=True)
