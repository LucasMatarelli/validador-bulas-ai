import streamlit as st
import fitz
import re
import unicodedata
from difflib import SequenceMatcher

st.set_page_config(page_title="Validador Belfar Enterprise", layout="wide")

# ----------------- FUNÇÕES DE APOIO -----------------
def clean_text(text):
    text = unicodedata.normalize('NFKD', text)
    return re.sub(r'\s+', ' ', text).lower().strip()

# ----------------- MOTOR DE AUDITORIA POR BLOCOS -----------------
def get_blocks(doc):
    """Extrai blocos de texto logicamente para evitar erros de layout."""
    blocks_data = []
    for p_idx, page in enumerate(doc):
        # get_text("blocks") é muito mais robusto para colunas que "words"
        for b in page.get_text("blocks", sort=True):
            txt = clean_text(b[4])
            if len(txt) > 10: # Ignora blocos muito pequenos (lixo)
                blocks_data.append({
                    "page": p_idx, 
                    "rect": fitz.Rect(b[:4]), 
                    "text": txt
                })
    return blocks_data

def get_divergences(blocks_ref, blocks_bel):
    """Compara blocos e retorna a lista de divergentes."""
    ref_texts = [b["text"] for b in blocks_ref]
    bel_texts = [b["text"] for b in blocks_bel]
    
    matcher = SequenceMatcher(None, ref_texts, bel_texts)
    divergentes = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            divergentes.extend(blocks_ref[i1:i2])
            divergentes.extend(blocks_bel[j1:j2])
    return divergentes

# ----------------- MOTOR DE RENDERIZAÇÃO (SEM TRAVAR) -----------------
def render_page_with_marks(doc, page_num, divergent_blocks):
    """Desenha marcação sólida apenas na imagem de exibição."""
    page = doc.load_page(page_num)
    
    # Desenha o marcatexto sólido
    for block in divergent_blocks:
        if block['page'] == page_num:
            annot = page.add_highlight_annot(block['rect'])
            annot.set_colors(stroke=(1, 1, 0)) # Amarelo puro
            annot.set_opacity(0.8)             # Sólido (igual à sua imagem 2)
            annot.update()
            
    # Gera a imagem
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    img_bytes = pix.tobytes("png")
    
    # LIMPEZA OBRIGATÓRIA: Apaga a anotação para não corromper o PDF
    for annot in page.annots():
        page.delete_annot(annot)
        
    return img_bytes

# ----------------- UI -----------------
st.title("🛡️ Auditoria Visual Enterprise")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if f1 and f2:
    doc_ref = fitz.open("pdf", f1.getvalue())
    doc_bel = fitz.open("pdf", f2.getvalue())
    
    if st.button("🚀 Processar Auditoria"):
        with st.spinner("Auditando blocos de texto..."):
            blocks_ref = get_blocks(doc_ref)
            blocks_bel = get_blocks(doc_bel)
            divs = get_divergences(blocks_ref, blocks_bel)
            
            st.session_state['divs'] = divs
            st.session_state['processed'] = True

    if st.session_state.get('processed'):
        st.write("### Comparação Visual (Scroll Vertical)")
        max_pag = max(len(doc_ref), len(doc_bel))
        
        for i in range(max_pag):
            st.divider()
            c_r, c_b = st.columns(2)
            
            # Referência
            if i < len(doc_ref):
                c_r.image(render_page_with_marks(doc_ref, i, st.session_state['divs']), use_container_width=True)
            
            # Belfar
            if i < len(doc_bel):
                c_b.image(render_page_with_marks(doc_bel, i, st.session_state['divs']), use_container_width=True)
