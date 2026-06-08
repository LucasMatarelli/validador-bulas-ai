import streamlit as st
import fitz
import re
import unicodedata
from difflib import SequenceMatcher

# ----------------- CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador Professional Belfar", layout="wide")

# ----------------- LÓGICA DE LIMPEZA -----------------
def clean_text(text):
    text = unicodedata.normalize('NFKD', text)
    return re.sub(r'[^\w\-]', '', text).lower().strip()

# ----------------- MOTOR DE COMPARAÇÃO -----------------
def get_divergences(doc_ref, doc_bel):
    """Retorna uma lista de palavras que divergem entre os dois documentos."""
    # Extrai todo o texto para comparação lógica (ignora colunas/layout)
    def extract_words(doc):
        words = []
        for p in doc:
            for w in p.get_text("words"):
                words.append({"page": p.number, "rect": fitz.Rect(w[:4]), "text": clean_text(w[4])})
        return words

    words_ref = extract_words(doc_ref)
    words_bel = extract_words(doc_bel)
    
    text_ref = [w["text"] for w in words_ref]
    text_bel = [w["text"] for w in words_bel]
    
    matcher = SequenceMatcher(None, text_ref, text_bel)
    divergentes = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            # Se houve divergência, marcamos as palavras da referência e da belfar
            divergentes.extend(words_ref[i1:i2])
            divergentes.extend(words_bel[j1:j2])
    return divergentes, words_ref, words_bel

# ----------------- MOTOR DE VISUALIZAÇÃO (O SEGREDO) -----------------
def get_page_image_with_highlights(doc, page_num, divergent_words):
    """Desenha o amarelo APENAS na imagem, nunca no PDF original."""
    page = doc.load_page(page_num)
    # Criamos uma cópia temporária da página para anotar
    # Anotamos, renderizamos a imagem e descartamos a anotação
    for word in divergent_words:
        if word['page'] == page_num:
            page.add_highlight_annot(word['rect'])
            
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
    img_data = pix.tobytes("png")
    # Limpamos as anotações após gerar a imagem para não corromper o doc
    for annot in page.annots():
        page.delete_annot(annot)
    return img_data

# ----------------- INTERFACE -----------------
st.title("🛡️ Validador de Bulas Enterprise - Motor de Auditoria")

f1, f2 = st.columns(2)
file_ref = f1.file_uploader("Bula Referência", type=["pdf"])
file_bel = f2.file_uploader("Bula BELFAR", type=["pdf"])

if file_ref and file_bel:
    doc_ref = fitz.open("pdf", file_ref.getvalue())
    doc_bel = fitz.open("pdf", file_bel.getvalue())
    
    if st.button("🚀 Processar Auditoria"):
        with st.spinner("Auditando..."):
            divs, _, _ = get_divergences(doc_ref, doc_bel)
            st.session_state['divergentes'] = divs
            st.success("Auditoria concluída! Navegue pelas páginas abaixo.")

if 'divergentes' in st.session_state:
    max_pag = max(len(doc_ref), len(doc_bel))
    page_select = st.slider("Página:", 0, max_pag - 1, 0)
    
    c1, c2 = st.columns(2)
    with c1:
        st.image(get_page_image_with_highlights(doc_ref, page_select, st.session_state['divergentes']), use_container_width=True)
    with c2:
        st.image(get_page_image_with_highlights(doc_bel, page_select, st.session_state['divergentes']), use_container_width=True)
