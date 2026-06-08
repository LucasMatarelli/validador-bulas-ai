import streamlit as st
import fitz
import re
import unicodedata
from difflib import SequenceMatcher

st.set_page_config(layout="wide")

def clean_text(text):
    # Limpeza pesada para garantir que espaços extras ou tabulações não atrapalhem
    text = unicodedata.normalize('NFKD', text)
    return re.sub(r'\s+', ' ', text).lower().strip()

def get_blocks(doc):
    """Extrai texto por blocos lógicos (parágrafos), ignorando colunas."""
    blocks = []
    for p in doc:
        # get_text("blocks") retorna o texto organizado logicamente
        page_blocks = p.get_text("blocks", sort=True)
        for b in page_blocks:
            # b[4] é o texto, b[:4] são as coordenadas
            txt = clean_text(b[4])
            if len(txt) > 5: # Ignora blocos muito curtos (sujeira)
                blocks.append({"page": p.number, "rect": fitz.Rect(b[:4]), "text": txt})
    return blocks

st.title("🛡️ Validador de Bulas - Auditoria por Blocos (Layout Flexível)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if f1 and f2:
    doc_ref = fitz.open("pdf", f1.getvalue())
    doc_bel = fitz.open("pdf", f2.getvalue())
    
    if st.button("🚀 Processar Auditoria Avançada"):
        with st.spinner("Analisando blocos lógicos..."):
            blocks_ref = get_blocks(doc_ref)
            blocks_bel = get_blocks(doc_bel)
            
            # Comparação por blocos
            ref_texts = [b["text"] for b in blocks_ref]
            bel_texts = [b["text"] for b in blocks_bel]
            
            matcher = SequenceMatcher(None, ref_texts, bel_texts)
            divergentes = []
            
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag != 'equal':
                    divergentes.extend(blocks_ref[i1:i2])
                    divergentes.extend(blocks_bel[j1:j2])
            
            st.session_state['divs'] = divergentes
            st.session_state['processed'] = True

    if st.session_state.get('processed'):
        def render_page(doc, page_num, divs):
            page = doc.load_page(page_num)
            for d in divs:
                if d['page'] == page_num:
                    page.add_highlight_annot(d['rect'])
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            return pix.tobytes("png")

        st.info("Abaixo estão as divergências identificadas por blocos:")
        max_pag = max(len(doc_ref), len(doc_bel))
        for i in range(max_pag):
            c_left, c_right = st.columns(2)
            if i < len(doc_ref):
                c_left.image(render_page(doc_ref, i, st.session_state['divs']), use_container_width=True)
            if i < len(doc_bel):
                c_right.image(render_page(doc_bel, i, st.session_state['divs']), use_container_width=True)
