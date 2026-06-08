import streamlit as st
import fitz
import re
import unicodedata
from difflib import SequenceMatcher

st.set_page_config(page_title="Auditoria Belfar Enterprise", layout="wide")

# ----------------- FUNÇÕES DE LIMPEZA -----------------
def clean_text(text):
    text = unicodedata.normalize('NFKD', text)
    # Remove espaços extras e quebras de linha para focar no conteúdo
    return re.sub(r'\s+', ' ', text).lower().strip()

# ----------------- MOTOR DE EXTRAÇÃO DE BLOCOS -----------------
def get_blocks(doc):
    """Extrai texto por blocos lógicos (parágrafos)."""
    blocks_data = []
    for p_idx, page in enumerate(doc):
        # get_text("blocks") é a chave: ele agrupa o texto em parágrafos lógicos
        for b in page.get_text("blocks", sort=True):
            txt = clean_text(b[4])
            if len(txt) > 10: # Ignora blocos muito pequenos (sujeira)
                blocks_data.append({
                    "page": p_idx, 
                    "rect": fitz.Rect(b[:4]), 
                    "text": txt
                })
    return blocks_data

# ----------------- MOTOR DE COMPARAÇÃO -----------------
def get_divergences(blocks_ref, blocks_bel):
    """Compara apenas o conteúdo dos blocos, ignorando layout."""
    ref_texts = [b["text"] for b in blocks_ref]
    bel_texts = [b["text"] for b in blocks_bel]
    
    matcher = SequenceMatcher(None, ref_texts, bel_texts)
    divergentes = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            # Adiciona apenas os blocos que divergiram
            divergentes.extend(blocks_ref[i1:i2])
            divergentes.extend(blocks_bel[j1:j2])
    return divergentes

# ----------------- RENDERIZAÇÃO PROFISSIONAL -----------------
def render_page_with_marks(doc, page_num, divergent_blocks):
    """Renderiza a imagem da página com amarelo apenas nas divergências reais."""
    page = doc.load_page(page_num)
    
    # Desenha o marcatexto sólido (amarelo)
    for block in divergent_blocks:
        if block['page'] == page_num:
            annot = page.add_highlight_annot(block['rect'])
            annot.set_colors(stroke=(1, 1, 0)) # Amarelo vibrante
            annot.set_opacity(0.8)             # Sólido
            annot.update()
            
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    img_bytes = pix.tobytes("png")
    
    # Limpa anotações para não corromper o PDF original
    for annot in page.annots():
        page.delete_annot(annot)
        
    return img_bytes

# ----------------- INTERFACE -----------------
st.title("🛡️ Auditoria Visual: Conteúdo vs. Conteúdo")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if f1 and f2:
    doc_ref = fitz.open("pdf", f1.getvalue())
    doc_bel = fitz.open("pdf", f2.getvalue())
    
    if st.button("🚀 Processar Auditoria"):
        with st.spinner("Analisando blocos lógicos..."):
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
            
            if i < len(doc_ref):
                c_r.image(render_page_with_marks(doc_ref, i, st.session_state['divs']), use_container_width=True)
            if i < len(doc_bel):
                c_b.image(render_page_with_marks(doc_bel, i, st.session_state['divs']), use_container_width=True)
