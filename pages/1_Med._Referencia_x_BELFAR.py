import streamlit as st
import fitz
import difflib
import re

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Normaliza texto para garantir que só divergências reais sejam pegas."""
    # Preserva tags [B] para que o comparador saiba que negrito é conteúdo diferente
    texto = texto.lower()
    return re.sub(r'[ \t\r\n]+', ' ', texto).strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Pro", layout="wide")

# ----------------- 2. EXTRAÇÃO DE PRECISÃO (Dicionário de Palavras) -----------------
def extract_words_with_coords(uploaded_file):
    """Extrai cada palavra com sua coordenada exata."""
    doc = fitz.open("pdf", uploaded_file.getvalue())
    all_words = []
    
    for page_idx, page in enumerate(doc):
        # Truncagem na Anvisa
        if "esta bula foi aprovada pela anvisa em" in page.get_text().lower():
            break
            
        # Extração inteligente via dicionário para capturar negrito
        blocks = page.get_text("dict")["blocks"]
        for b in blocks:
            if "lines" in b:
                for l in b["lines"]:
                    for s in l["spans"]:
                        text = s["text"]
                        # Identifica negrito
                        is_bold = s["flags"] & 2**4 or "bold" in s["font"].lower()
                        # Divide o span em palavras individuais para não marcar a frase toda
                        words = re.findall(r'\b[\w\.]+\b|\S', text)
                        for w in words:
                            # Tenta achar o retângulo exato da palavra (aproximação do span)
                            rect = page.search_for(w)
                            all_words.append({
                                "page": page_idx,
                                "rect": rect[0] if rect else None,
                                "text": f"[B]{w}[/B]" if is_bold else w
                            })
    return all_words, doc

# ----------------- 3. COMPARAÇÃO E ANOTAÇÃO -----------------
def process_and_mark(doc_ref, doc_bel, words_ref, words_bel):
    """Compara as listas de palavras e marca as divergências."""
    text_ref = [Sub_PreencherMapaDeVendas_Final_V29(w["text"]) for w in words_ref]
    text_bel = [Sub_PreencherMapaDeVendas_Final_V29(w["text"]) for w in words_bel]
    
    matcher = difflib.SequenceMatcher(None, text_ref, text_bel)
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal': continue
        
        # Divergência encontrada: marca ambos os lados para você ver o que falta
        if tag in ['delete', 'replace']:
            for i in range(i1, i2):
                w = words_ref[i]
                if w["rect"]:
                    page = doc_ref[w["page"]]
                    a = page.add_highlight_annot(w["rect"])
                    a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.6); a.update()
        
        if tag in ['insert', 'replace']:
            for i in range(j1, j2):
                w = words_bel[i]
                if w["rect"]:
                    page = doc_bel[w["page"]]
                    a = page.add_highlight_annot(w["rect"])
                    a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.6); a.update()

def mark_anvisa(doc):
    for page in doc:
        for inst in page.search_for("esta bula foi aprovada pela anvisa em"):
            a = page.add_highlight_annot(inst)
            a.set_colors(stroke=(0, 0.5, 1)); a.set_opacity(0.3); a.update()

# ----------------- 4. UI -----------------
st.title("💊 Comparador Visual de Bulas")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Comparar Documentos"):
    if not (f1 and f2):
        st.warning("Envie os arquivos.")
    else:
        with st.spinner("Analisando palavra por palavra..."):
            w_ref, doc_ref = extract_words_with_coords(f1)
            w_bel, doc_bel = extract_words_with_coords(f2)
            
            process_and_mark(doc_ref, doc_bel, w_ref, w_bel)
            mark_anvisa(doc_ref)
            mark_anvisa(doc_bel)
            
            # Exibição
            max_pag = max(len(doc_ref), len(doc_bel))
            for i in range(max_pag):
                st.divider()
                col_r, col_b = st.columns(2)
                with col_r:
                    if i < len(doc_ref): st.image(doc_ref[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
                with col_b:
                    if i < len(doc_bel): st.image(doc_bel[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
