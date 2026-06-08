import streamlit as st
import fitz
import difflib
import re

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Normaliza o texto mas preserva tags de negrito e pontuação essencial."""
    # Remove apenas espaços excessivos e quebras de linha.
    # Não removemos pontuação para não perder tópicos ou traços.
    return re.sub(r'[ \t\r\n]+', ' ', texto).strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Pro", layout="wide")

# ----------------- 2. EXTRAÇÃO DE ALTA PRECISÃO -----------------
def get_words_with_coords(uploaded_file):
    """Extrai palavras com coordenadas exatas, preservando tags [B]."""
    file_bytes = uploaded_file.getvalue()
    doc = fitz.open("pdf", file_bytes)
    words_data = []
    
    stop_flag = False
    for p_idx, page in enumerate(doc):
        # Truncagem Anvisa
        if "esta bula foi aprovada pela anvisa em" in page.get_text().lower():
            stop_flag = True
            
        words = page.get_text("words")
        for w in words:
            # w = (x0, y0, x1, y1, "texto", ...)
            rect = fitz.Rect(w[:4])
            text = w[4]
            
            # Identifica negrito (PyMuPDF flag 2^4)
            # Para pegar a formatação, precisamos olhar o span correspondente
            blocks = page.get_text("dict")["blocks"]
            is_bold = False
            for b in blocks:
                if "lines" in b:
                    for l in b["lines"]:
                        for s in l["spans"]:
                            # Se a palavra estiver contida na área do span
                            if fitz.Rect(s["bbox"]).intersects(rect):
                                if s["flags"] & 2**4 or "bold" in s["font"].lower():
                                    is_bold = True
            
            if is_bold: text = f"[B]{text}[/B]"
            
            words_data.append({
                "page": p_idx,
                "rect": rect,
                "text": text
            })
        if stop_flag: break
    return words_data, doc

# ----------------- 3. COMPARAÇÃO E PINTURA -----------------
def process_and_mark(doc_ref, doc_bel, words_ref, words_bel):
    text_ref = [Sub_PreencherMapaDeVendas_Final_V29(w["text"]) for w in words_ref]
    text_bel = [Sub_PreencherMapaDeVendas_Final_V29(w["text"]) for w in words_bel]
    
    matcher = difflib.SequenceMatcher(None, text_ref, text_bel)
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal': continue
        
        # Divergência na Referência (Delete/Replace)
        if tag in ['delete', 'replace']:
            for i in range(i1, i2):
                w = words_ref[i]
                if w["rect"].is_valid and not w["rect"].is_empty:
                    a = doc_ref[w["page"]].add_highlight_annot(w["rect"])
                    a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.6); a.update()
        
        # Divergência na Belfar (Insert/Replace)
        if tag in ['insert', 'replace']:
            for i in range(j1, j2):
                w = words_bel[i]
                if w["rect"].is_valid and not w["rect"].is_empty:
                    a = doc_bel[w["page"]].add_highlight_annot(w["rect"])
                    a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.6); a.update()

def mark_anvisa(doc):
    for page in doc:
        for inst in page.search_for("esta bula foi aprovada pela anvisa em"):
            a = page.add_highlight_annot(inst)
            a.set_colors(stroke=(0, 0.5, 1)); a.set_opacity(0.4); a.update()

# ----------------- 4. UI -----------------
st.title("💊 Comparador Visual de Bulas")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Comparar Bula Inteira"):
    if not (f1 and f2):
        st.warning("Envie os dois arquivos.")
    else:
        with st.spinner("Analisando palavras..."):
            w_ref, doc_ref = get_words_with_coords(f1)
            w_bel, doc_bel = get_words_with_coords(f2)
            
            process_and_mark(doc_ref, doc_bel, w_ref, w_bel)
            mark_anvisa(doc_ref)
            mark_anvisa(doc_bel)
            
            for i in range(max(len(doc_ref), len(doc_bel))):
                st.divider()
                st.subheader(f"Página {i+1}")
                col_r, col_b = st.columns(2)
                with col_r:
                    if i < len(doc_ref): st.image(doc_ref[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
                with col_b:
                    if i < len(doc_bel): st.image(doc_bel[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
