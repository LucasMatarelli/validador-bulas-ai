import streamlit as st
import fitz
import re
import difflib

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Normaliza o texto para comparação justa."""
    texto = texto.lower()
    # Remove marcações de negrito, hifens de quebra de linha e espaços duplos
    texto = re.sub(r'\[B\]|\[/B\]', '', texto)
    texto = re.sub(r'[-\n\r]', ' ', texto) 
    texto = re.sub(r'[ \t]+', ' ', texto)
    return texto.strip()

# ----------------- 1. EXTRAÇÃO E TRUNCAGEM -----------------
def get_pdf_blocks(uploaded_file):
    """Extrai blocos de texto, truncando na data Anvisa."""
    doc = fitz.open("pdf", uploaded_file.getvalue())
    blocks = []
    
    for page in doc:
        # Texto da página
        text_full = page.get_text()
        
        # Truncagem: se achar a data, corta o texto a partir dali
        match = re.search(r"esta bula foi aprovada pela anvisa em", text_full, re.IGNORECASE)
        if match:
            text_to_process = text_full[:match.start()]
        else:
            text_to_process = text_full
            
        # Pega blocos de texto (parágrafos)
        page_blocks = page.get_text("blocks")
        for b in page_blocks:
            # Filtra blocos que ficaram pós-truncagem
            if b[4].strip(): 
                blocks.append({"text": b[4], "page": page.number, "rect": fitz.Rect(b[:4])})
                
    return blocks, doc

# ----------------- 2. COMPARAÇÃO E ANOTAÇÃO -----------------
def run_validation(doc_ref, doc_bel, blocks_ref, blocks_bel):
    """Compara os blocos e marca divergências."""
    # Extrai textos normalizados
    text_ref = [Sub_PreencherMapaDeVendas_Final_V29(b["text"]) for b in blocks_ref]
    text_bel = [Sub_PreencherMapaDeVendas_Final_V29(b["text"]) for b in blocks_bel]
    
    matcher = difflib.SequenceMatcher(None, text_ref, text_bel)
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal': continue
        
        # Marca Referência (se deletado ou substituído)
        if tag in ['delete', 'replace']:
            for i in range(i1, i2):
                b = blocks_ref[i]
                page = doc_ref[b["page"]]
                a = page.add_highlight_annot(b["rect"])
                a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.4); a.update()
        
        # Marca Belfar (se inserido ou substituído)
        if tag in ['insert', 'replace']:
            for i in range(j1, j2):
                b = blocks_bel[i]
                page = doc_bel[b["page"]]
                a = page.add_highlight_annot(b["rect"])
                a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.4); a.update()

# ----------------- 3. UI PRINCIPAL -----------------
st.title("💊 Comparador Inteligente de Blocos")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Comparar Estrutura Completa"):
    if f1 and f2:
        with st.spinner("Comparando parágrafos..."):
            b_ref, doc_ref = get_pdf_blocks(f1)
            b_bel, doc_bel = get_pdf_blocks(f2)
            
            run_validation(doc_ref, doc_bel, b_ref, b_bel)
            
            # Exibe
            max_pag = max(len(doc_ref), len(doc_bel))
            for i in range(max_pag):
                st.divider()
                col1, col2 = st.columns(2)
                with col1:
                    if i < len(doc_ref):
                        st.image(doc_ref[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
                with col2:
                    if i < len(doc_bel):
                        st.image(doc_bel[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
