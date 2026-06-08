import streamlit as st
import fitz
import difflib
import re

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Normaliza o texto mantendo a integridade para comparação."""
    # Remove espaços excessivos mas mantém pontuação vital
    return re.sub(r'[ \t\r\n]+', ' ', texto).lower().strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Pro", layout="wide")

# ----------------- 2. EXTRAÇÃO E TRUNCAGEM -----------------
def get_pdf_words(uploaded_file):
    """Extrai palavras parando na data da Anvisa."""
    file_bytes = uploaded_file.getvalue()
    doc = fitz.open("pdf", file_bytes)
    all_words = []
    
    stop_flag = False
    for page_idx, page in enumerate(doc):
        text = page.get_text()
        # Gatilho de parada
        if "esta bula foi aprovada pela anvisa em" in text.lower():
            stop_flag = True
            
        words = page.get_text("words")
        for w in words:
            all_words.append({
                "page": page_idx,
                "rect": fitz.Rect(w[:4]),
                "text": w[4]
            })
        if stop_flag: break 
    return all_words, doc

# ----------------- 3. COMPARAÇÃO E ANOTAÇÃO -----------------
def process_and_mark(doc_ref, doc_bel, words_ref, words_bel):
    text_ref = [Sub_PreencherMapaDeVendas_Final_V29(w["text"]) for w in words_ref]
    text_bel = [Sub_PreencherMapaDeVendas_Final_V29(w["text"]) for w in words_bel]
    
    matcher = difflib.SequenceMatcher(None, text_ref, text_bel)
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal': continue
        
        # Se Referência tem algo a mais ou mudou (Marca a Referência)
        if tag in ['delete', 'replace']:
            for i in range(i1, i2):
                w = words_ref[i]
                page = doc_ref[w["page"]]
                a = page.add_highlight_annot(w["rect"])
                a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.4); a.update()
        
        # Se Belfar tem algo a mais ou mudou (Marca a Belfar)
        if tag in ['insert', 'replace']:
            for i in range(j1, j2):
                w = words_bel[i]
                page = doc_bel[w["page"]]
                a = page.add_highlight_annot(w["rect"])
                a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.4); a.update()

def mark_anvisa(doc):
    """Pinta a data da anvisa de azul."""
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

if st.button("🚀 Comparar Bula Inteira"):
    if not (f1 and f2):
        st.warning("Envie os dois arquivos.")
    else:
        with st.spinner("Analisando divergências em ambas as bulas..."):
            w_ref, doc_ref = get_pdf_words(f1)
            w_bel, doc_bel = get_pdf_words(f2)
            
            # Executa a comparação e pintura
            process_and_mark(doc_ref, doc_bel, w_ref, w_bel)
            mark_anvisa(doc_ref)
            mark_anvisa(doc_bel)
            
            # Exibição
            max_pag = max(len(doc_ref), len(doc_bel))
            for i in range(max_pag):
                st.divider()
                st.subheader(f"Página {i+1}")
                col_r, col_b = st.columns(2)
                
                with col_r:
                    if i < len(doc_ref):
                        st.image(doc_ref[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
                with col_b:
                    if i < len(doc_bel):
                        st.image(doc_bel[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
