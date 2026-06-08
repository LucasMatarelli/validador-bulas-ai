import streamlit as st
import fitz
import re
import unicodedata
from difflib import SequenceMatcher

st.set_page_config(layout="wide")

def clean_text(text):
    # Remove tudo que é ruído visual (espaços duplos, quebras de linha)
    text = unicodedata.normalize('NFKD', text)
    return re.sub(r'\s+', ' ', text).lower().strip()

def get_blocks(doc):
    """Extrai blocos de texto (parágrafos) logicamente."""
    blocks_data = []
    for p_idx, page in enumerate(doc):
        # b[4] é o texto, b[:4] são as coordenadas
        for b in page.get_text("blocks", sort=True):
            txt = clean_text(b[4])
            if len(txt) > 10: # Filtra ruídos pequenos (números de página, marcas de corte)
                blocks_data.append({"page": p_idx, "rect": fitz.Rect(b[:4]), "text": txt})
    return blocks_data

def get_divergences(blocks_ref, blocks_bel):
    """Compara apenas o conteúdo dos blocos."""
    ref_texts = [b["text"] for b in blocks_ref]
    bel_texts = [b["text"] for b in blocks_bel]
    
    matcher = SequenceMatcher(None, ref_texts, bel_texts)
    divergentes = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            # Salva o bloco inteiro que é divergente
            divergentes.extend(blocks_ref[i1:i2])
            divergentes.extend(blocks_bel[j1:j2])
    return divergentes

# UI
st.title("🛡️ Validador de Bulas (Motor de Blocos - Estilo TVT)")
c1, c2 = st.columns(2)
f1 = c1.file_uploader("Bula Referência", type=["pdf"])
f2 = c2.file_uploader("Bula BELFAR", type=["pdf"])

if f1 and f2:
    doc_ref = fitz.open("pdf", f1.getvalue())
    doc_bel = fitz.open("pdf", f2.getvalue())
    
    if st.button("🚀 Processar Auditoria"):
        with st.spinner("Analisando blocos..."):
            blocks_ref = get_blocks(doc_ref)
            blocks_bel = get_blocks(doc_bel)
            divs = get_divergences(blocks_ref, blocks_bel)
            st.session_state['divs'] = divs
            st.session_state['processed'] = True

    if st.session_state.get('processed'):
        max_pag = max(len(doc_ref), len(doc_bel))
        for i in range(max_pag):
            st.divider()
            c_r, c_b = st.columns(2)
            
            # Função de pintura local para não corromper o PDF
            def draw_marks(doc, page_num, blocks):
                page = doc.load_page(page_num)
                for b in blocks:
                    if b['page'] == page_num:
                        annot = page.add_highlight_annot(b['rect'])
                        annot.set_colors(stroke=(1, 1, 0))
                        annot.set_opacity(0.8)
                        annot.update()
                img = page.get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png")
                # Apaga as anotações após o render
                for a in page.annots(): page.delete_annot(a)
                return img

            if i < len(doc_ref):
                c_r.image(draw_marks(doc_ref, i, st.session_state['divs']), use_container_width=True)
            if i < len(doc_bel):
                c_b.image(draw_marks(doc_bel, i, st.session_state['divs']), use_container_width=True)
