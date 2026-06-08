import streamlit as st
import fitz
import difflib
import re

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Normaliza o texto, mas preserva a pontuação necessária para não quebrar termos técnicos."""
    # Remove apenas espaços excessivos e quebras de linha
    return re.sub(r'[ \t\r\n]+', ' ', texto).strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Pro", layout="wide")

# ----------------- 2. EXTRAÇÃO E TOKENIZAÇÃO -----------------
def extract_pdf_data(uploaded_file):
    """Extrai palavras com coordenadas, preservando negrito como tag."""
    file_bytes = uploaded_file.getvalue()
    doc = fitz.open("pdf", file_bytes)
    words_list = []
    
    stop_flag = False
    for p_idx, page in enumerate(doc):
        # Truncagem na Anvisa
        if "esta bula foi aprovada pela anvisa em" in page.get_text().lower():
            stop_flag = True
            
        blocks = page.get_text("dict")["blocks"]
        for b in blocks:
            if "lines" in b:
                for l in b["lines"]:
                    for s in l["spans"]:
                        text = s["text"]
                        # Preserva negrito
                        if s["flags"] & 2**4 or "bold" in s["font"].lower():
                            text = f"[B]{text}[/B]"
                        
                        # Tokeniza mantendo pontuação de palavras (ex: pus), Stevens-Johnson)
                        tokens = re.findall(r'\b[\w\[\]/]+|[\S]', text)
                        for t in tokens:
                            words_list.append({
                                "page": p_idx,
                                "rect": page.search_for(t.replace("[B]","").replace("[/B]",""))[0] if page.search_for(t.replace("[B]","").replace("[/B]","")) else fitz.Rect(0,0,0,0),
                                "text": t
                            })
        if stop_flag: break
    return words_list, doc

# ----------------- 3. COMPARAÇÃO E ANOTAÇÃO -----------------
def process_and_mark(doc_ref, doc_bel, words_ref, words_bel):
    text_ref = [w["text"] for w in words_ref]
    text_bel = [w["text"] for w in words_bel]
    
    matcher = difflib.SequenceMatcher(None, text_ref, text_bel)
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal': continue
        
        # Marca Referência se algo diverge
        if tag in ['delete', 'replace']:
            for i in range(i1, i2):
                w = words_ref[i]
                if w["rect"].is_valid:
                    page = doc_ref[w["page"]]
                    a = page.add_highlight_annot(w["rect"])
                    a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.6); a.update()
        
        # Marca Belfar se algo diverge
        if tag in ['insert', 'replace']:
            for i in range(j1, j2):
                w = words_bel[i]
                if w["rect"].is_valid:
                    page = doc_bel[w["page"]]
                    a = page.add_highlight_annot(w["rect"])
                    a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.6); a.update()

def mark_anvisa(doc):
    for page in doc:
        for inst in page.search_for("esta bula foi aprovada pela anvisa em"):
            a = page.add_highlight_annot(inst)
            a.set_colors(stroke=(0, 0.5, 1)); a.set_opacity(0.5); a.update()

# ----------------- 4. UI -----------------
st.title("💊 Comparador Visual de Bulas")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Comparar (Nível Palavra)"):
    if not (f1 and f2):
        st.warning("Envie os dois arquivos.")
    else:
        with st.spinner("Analisando divergências exatas..."):
            w_ref, doc_ref = extract_pdf_data(f1)
            w_bel, doc_bel = extract_pdf_data(f2)
            
            process_and_mark(doc_ref, doc_bel, w_ref, w_bel)
            mark_anvisa(doc_ref)
            mark_anvisa(doc_bel)
            
            for i in range(max(len(doc_ref), len(doc_bel))):
                st.divider()
                col_r, col_b = st.columns(2)
                with col_r:
                    if i < len(doc_ref): st.image(doc_ref[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
                with col_b:
                    if i < len(doc_bel): st.image(doc_bel[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
