import streamlit as st
import fitz
import difflib
import re

# ----------------- REGRA DE PROJETO APRIMORADA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    # Remove apenas pontuação isolada, mantém hífens e tags de negrito
    texto = re.sub(r'[^\w\-\[\]]', '', texto)
    return texto.lower().strip()

# Lista de palavras que o sistema deve ignorar (nomes de empresas/produtos)
IGNORE_LIST = ['sanofi', 'medley', 'belfar', 'flagyl', 'flagimax', 'urotrobel', 'norfloxacino']

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Pro", layout="wide")

# ----------------- 2. EXTRAÇÃO DE ALTA PRECISÃO -----------------
def get_words_with_coords(uploaded_file):
    doc = fitz.open("pdf", uploaded_file.getvalue())
    words_data = []
    
    stop_flag = False
    for p_idx, page in enumerate(doc):
        if "esta bula foi aprovada pela anvisa em" in page.get_text().lower():
            stop_flag = True
            
        blocks = page.get_text("dict")["blocks"]
        for b in blocks:
            if "lines" in b:
                for l in b["lines"]:
                    for s in l["spans"]:
                        is_bold = bool(s["flags"] & 2**4) or "bold" in s["font"].lower()
                        # Tokeniza separando por espaço mas mantendo pontuação relevante
                        tokens = s["text"].split()
                        for t in tokens:
                            rect = page.search_for(t)
                            words_data.append({
                                "page": p_idx,
                                "rect": rect[0] if rect else fitz.Rect(0,0,0,0),
                                "text": t,
                                "clean": Sub_PreencherMapaDeVendas_Final_V29(t),
                                "is_bold": is_bold
                            })
        if stop_flag: break
    return words_data, doc

# ----------------- 3. COMPARAÇÃO INTELIGENTE -----------------
def process_and_mark(doc_ref, doc_bel, words_ref, words_bel):
    text_ref = [w["clean"] for w in words_ref]
    text_bel = [w["clean"] for w in words_bel]
    
    matcher = difflib.SequenceMatcher(None, text_ref, text_bel)
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal': continue
        
        # Analisa divergências
        for i, j in [(i1, i2), (j1, j2)]:
            for k in range(i, j):
                # Se for referência (i1, i2) marca doc_ref; se for bel (j1, j2) marca doc_bel
                w = words_ref[k] if tag in ['delete', 'replace'] and k < len(words_ref) else None
                if not w and tag in ['insert', 'replace'] and k < len(words_bel):
                    w = words_bel[k]
                
                if w and w["text"].lower() not in IGNORE_LIST and len(w["clean"]) > 0:
                    # Verifica divergência de estilo (negrito)
                    # Se texto é igual mas negrito não, marca. Se texto é diferente, marca.
                    if w["rect"].is_valid:
                        try:
                            a = (doc_ref if tag in ['delete', 'replace'] else doc_bel)[w["page"]].add_highlight_annot(w["rect"])
                            a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.6); a.update()
                        except: pass

# ----------------- 4. UI -----------------
st.title("💊 Comparador Inteligente de Bulas")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Comparar"):
    if f1 and f2:
        with st.spinner("Comparando..."):
            w_ref, doc_ref = get_words_with_coords(f1)
            w_bel, doc_bel = get_words_with_coords(f2)
            process_and_mark(doc_ref, doc_bel, w_ref, w_bel)
            
            for i in range(max(len(doc_ref), len(doc_bel))):
                st.divider()
                col1, col2 = st.columns(2)
                if i < len(doc_ref): col1.image(doc_ref[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
                if i < len(doc_bel): col2.image(doc_bel[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
