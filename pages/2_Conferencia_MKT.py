import streamlit as st
import fitz
import re
import unicodedata
from difflib import SequenceMatcher

st.set_page_config(page_title="Validador Belfar Enterprise", layout="wide")

# ----------------- FUNÇÕES DE LIMPEZA -----------------
def clean_text(text):
    text = unicodedata.normalize('NFKD', text)
    return re.sub(r'[^\w\-]', '', text).lower().strip()

# ----------------- MOTOR DE EXTRAÇÃO (LAYOUT-AWARE) -----------------
def get_blocks(doc):
    """Extrai texto por blocos lógicos, o segredo para bulas com colunas."""
    blocks_data = []
    for p_idx, page in enumerate(doc):
        # Usamos 'blocks' em vez de 'words' para ignorar a posição visual das colunas
        blocks = page.get_text("blocks", sort=True)
        for b in blocks:
            txt = clean_text(b[4])
            if len(txt) > 5: # Ignora ruídos (números de página, etc)
                blocks_data.append({
                    "page": p_idx, 
                    "rect": fitz.Rect(b[:4]), 
                    "text": txt
                })
    return blocks_data

# ----------------- COMPARAÇÃO E PINTURA (ESTILO CIMED) -----------------
def paint_rect(page, rect):
    """Pinta o retângulo com amarelo sólido vibrante."""
    # Amarelo puro (1, 1, 0) e opacidade 0.8 (sólido como na imagem 2)
    annot = page.add_highlight_annot(rect)
    annot.set_colors(stroke=(1, 1, 0))
    annot.set_opacity(0.8)
    annot.update()

def process_audit(doc_ref, doc_bel):
    blocks_ref = get_blocks(doc_ref)
    blocks_bel = get_blocks(doc_bel)
    
    ref_texts = [b["text"] for b in blocks_ref]
    bel_texts = [b["text"] for b in blocks_bel]
    
    matcher = SequenceMatcher(None, ref_texts, bel_texts)
    
    # Lista de páginas que precisam de pintura
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            # Pinta na Referência
            for i in range(i1, i2):
                if i < len(blocks_ref):
                    paint_rect(doc_ref.load_page(blocks_ref[i]["page"]), blocks_ref[i]["rect"])
            # Pinta na Belfar
            for j in range(j1, j2):
                if j < len(blocks_bel):
                    paint_rect(doc_bel.load_page(blocks_bel[j]["page"]), blocks_bel[j]["rect"])

# ----------------- UI -----------------
st.title("🛡️ Validador de Bulas Enterprise - Auditoria Visual")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("Bula Referência", type=["pdf"])
f2 = c2.file_uploader("Bula BELFAR", type=["pdf"])

if f1 and f2:
    doc_ref = fitz.open("pdf", f1.getvalue())
    doc_bel = fitz.open("pdf", f2.getvalue())
    
    if st.button("🚀 Processar Auditoria Visual"):
        with st.spinner("Analisando estruturas e pintando divergências..."):
            process_audit(doc_ref, doc_bel)
            st.session_state['processed'] = True

    if st.session_state.get('processed'):
        max_pag = max(len(doc_ref), len(doc_bel))
        for i in range(max_pag):
            st.divider()
            col_r, col_b = st.columns(2)
            if i < len(doc_ref):
                col_r.subheader(f"Referência (Pág {i+1})")
                col_r.image(doc_ref[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
            if i < len(doc_bel):
                col_b.subheader(f"BELFAR (Pág {i+1})")
                col_b.image(doc_bel[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
