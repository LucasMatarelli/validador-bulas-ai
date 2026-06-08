import streamlit as st
import fitz
import difflib
import re
import unicodedata

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Limpa pontuação e caracteres invisíveis do PDF, garantindo precisão."""
    # Normaliza unicode (resolve ligaturas do PDF onde 'f' e 'i' ficam grudados)
    texto = unicodedata.normalize('NFKC', texto)
    # Remove pontuação, mas preserva hífens (ex: Stevens-Johnson)
    texto_limpo = re.sub(r'[^\w\-]', '', texto)
    return texto_limpo.lower().strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Enterprise", layout="wide")

# ----------------- 2. EXTRAÇÃO DE ALTA PRECISÃO -----------------
def get_words_with_coords(uploaded_file):
    doc = fitz.open("pdf", uploaded_file.getvalue())
    words_data = []
    stop_flag = False

    for p_idx, page in enumerate(doc):
        if "esta bula foi aprovada pela anvisa em" in page.get_text().lower():
            stop_flag = True

        # sort=True força o PyMuPDF a ler na ordem humana (cima->baixo, esq->dir)
        words = page.get_text("words", sort=True)
        blocks = page.get_text("dict")["blocks"]

        # Mapeia onde estão os negritos
        spans_info = []
        for b in blocks:
            if "lines" in b:
                for l in b["lines"]:
                    for s in l["spans"]:
                        is_bold = bool(s["flags"] & 2**4) or "bold" in s["font"].lower()
                        spans_info.append({"rect": fitz.Rect(s["bbox"]), "is_bold": is_bold})

        for w in words:
            rect = fitz.Rect(w[:4])
            raw_text = w[4]
            clean_text = Sub_PreencherMapaDeVendas_Final_V29(raw_text)

            if not clean_text: continue 

            # Verifica o estilo (negrito) exato da palavra
            is_bold = False
            for span in spans_info:
                if span["rect"].intersects(rect):
                    is_bold = span["is_bold"]
                    break

            words_data.append({
                "page": p_idx,
                "rect": rect,
                "clean": clean_text,
                "is_bold": is_bold
            })

        if stop_flag: break 
    return words_data, doc

# ----------------- 3. COMPARAÇÃO MATEMÁTICA E PINTURA -----------------
def paint_rect(doc, word_data, color=(1, 0.85, 0)):
    """Pinta o retângulo no PDF de forma segura."""
    if word_data["rect"].is_valid and not word_data["rect"].is_empty:
        try:
            page = doc[word_data["page"]]
            a = page.add_highlight_annot(word_data["rect"])
            a.set_colors(stroke=color)
            a.set_opacity(0.6) # Opacidade padrão, sem 'amarelo fraquinho'
            a.update()
        except: pass

def process_and_mark(doc_ref, doc_bel, words_ref, words_bel):
    text_ref = [w["clean"] for w in words_ref]
    text_bel = [w["clean"] for w in words_bel]

    matcher = difflib.SequenceMatcher(None, text_ref, text_bel)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            # Palavras são idênticas, mas e o negrito?
            for k in range(i2 - i1):
                w_ref = words_ref[i1 + k]
                w_bel = words_bel[j1 + k]
                # Se um tem negrito e o outro não, marca os dois com o amarelo normal
                if w_ref["is_bold"] != w_bel["is_bold"]:
                    paint_rect(doc_ref, w_ref)
                    paint_rect(doc_bel, w_bel)
                    
        elif tag == 'replace':
            # Textos divergentes (Ex: Flagyl vs Flagimax)
            for i in range(i1, i2): paint_rect(doc_ref, words_ref[i])
            for j in range(j1, j2): paint_rect(doc_bel, words_bel[j])
                
        elif tag == 'delete':
            # Falta na Belfar
            for i in range(i1, i2): paint_rect(doc_ref, words_ref[i])
                
        elif tag == 'insert':
            # Tem a mais na Belfar
            for j in range(j1, j2): paint_rect(doc_bel, words_bel[j])

def mark_anvisa(doc):
    for page in doc:
        for inst in page.search_for("esta bula foi aprovada pela anvisa em", flags=fitz.TEXT_PRESERVE_WHITESPACE):
            try:
                a = page.add_highlight_annot(inst)
                a.set_colors(stroke=(0, 0.5, 1)) # Azul
                a.set_opacity(0.5)
                a.update()
            except: pass

# ----------------- 4. UI -----------------
st.title("💊 Validador Enterprise de Bulas")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Processar Auditoria"):
    if not (f1 and f2):
        st.warning("Por favor, envie os dois arquivos PDF.")
    else:
        with st.spinner("Lendo camada binária e comparando dados..."):
            w_ref, doc_ref = get_words_with_coords(f1)
            w_bel, doc_bel = get_words_with_coords(f2)
            
            process_and_mark(doc_ref, doc_bel, w_ref, w_bel)
            mark_anvisa(doc_ref)
            mark_anvisa(doc_bel)
            
            max_pag = max(len(doc_ref), len(doc_bel))
            for i in range(max_pag):
                st.divider()
                col_r, col_b = st.columns(2)
                with col_r:
                    st.caption(f"Referência (Página {i+1})")
                    if i < len(doc_ref): st.image(doc_ref[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
                with col_b:
                    st.caption(f"BELFAR (Página {i+1})")
                    if i < len(doc_bel): st.image(doc_bel[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
