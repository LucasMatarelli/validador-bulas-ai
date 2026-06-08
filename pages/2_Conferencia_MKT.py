import streamlit as st
import fitz
import re
import unicodedata
from difflib import SequenceMatcher

st.set_page_config(page_title="Validador Belfar Enterprise", layout="wide")

# ----------------- FUNÇÕES DE APOIO -----------------
def clean_text(text):
    text = unicodedata.normalize('NFKD', text)
    # Limpeza mais tolerante para não disparar divergência por espaços
    return re.sub(r'\s+', ' ', text).lower().strip()

# ----------------- MOTOR DE EXTRAÇÃO DE BLOCOS -----------------
def get_blocks(doc):
    """Extrai blocos lógicos (parágrafos) do PDF."""
    blocks_data = []
    for p_idx, page in enumerate(doc):
        # O "blocks" é muito superior a "words" para layouts com colunas
        for b in page.get_text("blocks", sort=True):
            txt = clean_text(b[4])
            if len(txt) > 10: # Filtra ruídos
                blocks_data.append({
                    "page": p_idx, 
                    "rect": fitz.Rect(b[:4]), 
                    "text": txt
                })
    return blocks_data

# ----------------- MOTOR DE COMPARAÇÃO -----------------
def get_divergences(blocks_ref, blocks_bel):
    """Compara o texto dos blocos."""
    ref_texts = [b["text"] for b in blocks_ref]
    bel_texts = [b["text"] for b in blocks_bel]
    
    matcher = SequenceMatcher(None, ref_texts, bel_texts)
    divergentes = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            # Se for diferente, pega o bloco para pintar
            divergentes.extend(blocks_ref[i1:i2])
            divergentes.extend(blocks_bel[j1:j2])
    return divergentes

# ----------------- RENDERIZAÇÃO SEM ERROS -----------------
def render_page_with_marks(doc, page_num, divergent_blocks):
    """Pinta apenas os blocos que divergiram."""
    page = doc.load_page(page_num)
    
    for block in divergent_blocks:
        if block['page'] == page_num:
            # Marcatexto sólido e vibrante
            annot = page.add_highlight_annot(block['rect'])
            annot.set_colors(stroke=(1, 1, 0))
            annot.set_opacity(0.7)
            annot.update()
            
    # Gera a imagem sem tocar no arquivo original
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    img_bytes = pix.tobytes("png")
    
    # Limpa as anotações para a próxima renderização
    for annot in page.annots():
        page.delete_annot(annot)
        
    return img_bytes

# ----------------- UI -----------------
st.title("🛡️ Validador Belfar (Modo Auditoria por Blocos)")

col1, col2 = st.columns(2)
f1 = col1.file_uploader("Bula Referência", type=["pdf"])
f2 = col2.file_uploader("Bula BELFAR", type=["pdf"])

if f1 and f2:
    doc_ref = fitz.open("pdf", f1.getvalue())
    doc_bel = fitz.open("pdf", f2.getvalue())
    
    if st.button("🚀 Processar"):
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
            
            # Renderiza lado a lado
            if i < len(doc_ref):
                c_r.image(render_page_with_marks(doc_ref, i, st.session_state['divs']), use_container_width=True)
            if i < len(doc_bel):
                c_b.image(render_page_with_marks(doc_bel, i, st.session_state['divs']), use_container_width=True)
