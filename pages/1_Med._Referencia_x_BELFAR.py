import streamlit as st
import fitz
import difflib
import re

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Normaliza o texto para garantir consistência na comparação."""
    return re.sub(r'[ \t\r\n]+', ' ', texto).lower().strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Pro", layout="wide")

# ----------------- 2. EXTRAÇÃO ROBUSTA -----------------
def get_pdf_data(uploaded_file):
    """Extrai palavras com coordenadas precisas, truncando na Anvisa."""
    doc = fitz.open("pdf", uploaded_file.getvalue())
    words_data = []
    
    stop_flag = False
    for p_idx, page in enumerate(doc):
        # Verifica truncagem na Anvisa
        if "esta bula foi aprovada pela anvisa em" in page.get_text().lower():
            stop_flag = True
        
        words = page.get_text("words")
        for w in words:
            # w = (x0, y0, x1, y1, "texto", block_no, line_no, word_no)
            # Cria um Rect e valida se é utilizável
            rect = fitz.Rect(w[:4])
            if rect.width > 0 and rect.height > 0:
                words_data.append({
                    "page": p_idx,
                    "rect": rect,
                    "text": w[4]
                })
        if stop_flag: break
    return words_data, doc

# ----------------- 3. COMPARAÇÃO E ANOTAÇÃO -----------------
def process_and_mark(doc_ref, doc_bel, words_ref, words_bel):
    text_ref = [Sub_PreencherMapaDeVendas_Final_V29(w["text"]) for w in words_ref]
    text_bel = [Sub_PreencherMapaDeVendas_Final_V29(w["text"]) for w in words_bel]
    
    matcher = difflib.SequenceMatcher(None, text_ref, text_bel)
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal': continue
        
        # Referência tem algo a mais ou mudou -> Marca Referência
        if tag in ['delete', 'replace']:
            for i in range(i1, i2):
                w = words_ref[i]
                page = doc_ref[w["page"]]
                a = page.add_highlight_annot(w["rect"])
                a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.4); a.update()
        
        # Belfar tem algo a mais ou mudou -> Marca Belfar
        if tag in ['insert', 'replace']:
            for i in range(j1, j2):
                w = words_bel[i]
                page = doc_bel[w["page"]]
                a = page.add_highlight_annot(w["rect"])
                a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.4); a.update()

def mark_anvisa(doc):
    pattern = r"esta bula foi aprovada pela anvisa em"
    for page in doc:
        for inst in page.search_for(pattern, flags=fitz.TEXT_PRESERVE_WHITESPACE):
            a = page.add_highlight_annot(inst)
            a.set_colors(stroke=(0, 0.5, 1)); a.set_opacity(0.3); a.update()

# ----------------- 4. UI -----------------
st.title("💊 Comparador Visual de Bulas")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Iniciar Auditoria"):
    if not (f1 and f2):
        st.warning("Envie os dois arquivos.")
    else:
        with st.spinner("Comparando e pintando..."):
            w_ref, doc_ref = get_pdf_data(f1)
            w_bel, doc_bel = get_pdf_data(f2)
            
            # Executa a comparação bidirecional
            process_and_mark(doc_ref, doc_bel, w_ref, w_bel)
            mark_anvisa(doc_ref)
            mark_anvisa(doc_bel)
            
            # Exibição
            max_pag = max(len(doc_ref), len(doc_bel))
            for i in range(max_pag):
                st.divider()
                col_r, col_b = st.columns(2)
                with col_r:
                    if i < len(doc_ref):
                        st.image(doc_ref[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
                with col_b:
                    if i < len(doc_bel):
                        st.image(doc_bel[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
