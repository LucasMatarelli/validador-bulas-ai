import streamlit as st
import fitz
import difflib
import re

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Normaliza texto preservando pontuação para detectar mudanças de formatação."""
    # Remove espaços excessivos, mas mantém símbolos de lista/pontuação
    texto = re.sub(r'[ \t\r\n]+', ' ', texto)
    return texto.lower().strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Pro", layout="wide")

# ----------------- 2. EXTRAÇÃO E TRUNCAGEM -----------------
def get_pdf_words(uploaded_file):
    """Extrai palavras com coordenadas, parando na data da Anvisa."""
    file_bytes = uploaded_file.getvalue()
    doc = fitz.open("pdf", file_bytes)
    all_words = []
    
    anvisa_found = False
    for page_idx, page in enumerate(doc):
        # Busca a frase de truncagem
        text = page.get_text()
        if re.search(r"esta bula foi aprovada pela anvisa em", text, re.IGNORECASE):
            anvisa_found = True
            
        words = page.get_text("words")
        for w in words:
            # w = (x0, y0, x1, y1, "texto", block_no, line_no, word_no)
            all_words.append({
                "page": page_idx,
                "rect": fitz.Rect(w[:4]),
                "text": w[4]
            })
        
        if anvisa_found: break # Para de extrair após encontrar a data
    return all_words, doc

# ----------------- 3. COMPARAÇÃO E ANOTAÇÃO -----------------
def process_and_mark(doc_ref, doc_bel, words_ref, words_bel):
    """Compara as palavras e marca ambos os documentos."""
    # Lista apenas os textos para o difflib
    text_ref = [Sub_PreencherMapaDeVendas_Final_V29(w["text"]) for w in words_ref]
    text_bel = [Sub_PreencherMapaDeVendas_Final_V29(w["text"]) for w in words_bel]
    
    matcher = difflib.SequenceMatcher(None, text_ref, text_bel)
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal': continue
        
        # Se Referência tem algo a mais ou mudou:
        if tag in ['delete', 'replace']:
            for i in range(i1, i2):
                w = words_ref[i]
                page = doc_ref[w["page"]]
                a = page.add_highlight_annot(w["rect"])
                a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.4); a.update()
        
        # Se Belfar tem algo a mais ou mudou:
        if tag in ['insert', 'replace']:
            for i in range(j1, j2):
                w = words_bel[i]
                page = doc_bel[w["page"]]
                a = page.add_highlight_annot(w["rect"])
                a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.4); a.update()

# ----------------- 4. UI -----------------
st.title("💊 Validador de Bulas (Detecção Total)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Comparar Bula Inteira"):
    if not (f1 and f2):
        st.warning("Envie os dois arquivos.")
    else:
        with st.spinner("Analisando..."):
            w_ref, doc_ref = get_pdf_words(f1)
            w_bel, doc_bel = get_pdf_words(f2)
            
            process_and_mark(doc_ref, doc_bel, w_ref, w_bel)
            
            # Render lado a lado
            max_pag = max(len(doc_ref), len(doc_bel))
            for i in range(max_pag):
                st.divider()
                col1, col2 = st.columns(2)
                with col1:
                    if i < len(doc_ref):
                        st.image(doc_ref[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"))
                with col2:
                    if i < len(doc_bel):
                        st.image(doc_bel[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"))
