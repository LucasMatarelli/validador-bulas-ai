import streamlit as st
import fitz
import difflib
import re
import unicodedata

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Limpa pontuação que causa falsos positivos, mantendo hífens."""
    texto = unicodedata.normalize('NFKC', texto)
    return re.sub(r'[^\w\-]', '', texto).lower().strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador Profissional de Bulas", layout="wide")

# ----------------- 2. EXTRAÇÃO DE ALTA PRECISÃO -----------------
def get_words_with_coords(uploaded_file):
    doc = fitz.open("pdf", uploaded_file.getvalue())
    words_data = []
    stop_flag = False

    for p_idx, page in enumerate(doc):
        # Truncagem exata na Anvisa
        if "esta bula foi aprovada pela anvisa em" in page.get_text().lower():
            stop_flag = True

        blocks = page.get_text("dict")["blocks"]
        spans_info = []
        for b in blocks:
            if "lines" in b:
                for l in b["lines"]:
                    for s in l["spans"]:
                        is_bold = bool(s["flags"] & 2**4) or "bold" in s["font"].lower()
                        spans_info.append({"rect": fitz.Rect(s["bbox"]), "is_bold": is_bold})

        words = page.get_text("words", sort=True)
        for w in words:
            rect = fitz.Rect(w[:4])
            raw_text = w[4]
            clean_text = Sub_PreencherMapaDeVendas_Final_V29(raw_text)
            if not clean_text: continue 

            is_bold = False
            for span in spans_info:
                if span["rect"].intersects(rect) and span["rect"].get_area() > 0:
                    is_bold = span["is_bold"]
                    break

            words_data.append({"page": p_idx, "rect": rect, "clean": clean_text, "is_bold": is_bold})
        if stop_flag: break
    return words_data, doc

# ----------------- 3. COMPARAÇÃO MATEMÁTICA E PINTURA -----------------
def paint_rect(doc, page_idx, rect, color=(1, 0.9, 0)):
    """Pinta com opacidade sólida de 0.6 (sem tons clarinhos)."""
    if rect.is_valid and not rect.is_empty:
        try:
            page = doc[page_idx]
            a = page.add_highlight_annot(rect)
            a.set_colors(stroke=color)
            a.set_opacity(0.6) # Opacidade padrão, sem "amarelo fraquinho"
            a.update()
        except: pass

def process_and_mark(doc_ref, doc_bel, words_ref, words_bel):
    text_ref = [w["clean"] for w in words_ref]
    text_bel = [w["clean"] for w in words_bel]
    matcher = difflib.SequenceMatcher(None, text_ref, text_bel)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            # Verifica apenas se o NEGRITO divergiu entre textos iguais
            for k in range(i2 - i1):
                w_ref = words_ref[i1 + k]
                w_bel = words_bel[j1 + k]
                if w_ref["is_bold"] != w_bel["is_bold"]:
                    paint_rect(doc_ref, w_ref["page"], w_ref["rect"])
                    paint_rect(doc_bel, w_bel["page"], w_bel["rect"])
        else:
            # Qualquer outra divergência marca tudo (texto diferente)
            for i in range(i1, i2): paint_rect(doc_ref, words_ref[i]["page"], words_ref[i]["rect"])
            for j in range(j1, j2): paint_rect(doc_bel, words_bel[j]["page"], words_bel[j]["rect"])

# ----------------- 4. UI -----------------
st.title("💊 Validador de Bulas (Foco em Divergência Real)")
c1, c2 = st.columns(2)
f1, f2 = c1.file_uploader("Referência", type=["pdf"]), c2.file_uploader("BELFAR", type=["pdf"])

if st.button("🚀 Iniciar Auditoria"):
    if f1 and f2:
        with st.spinner("Analisando..."):
            w_ref, doc_ref = get_words_with_coords(f1)
            w_bel, doc_bel = get_words_with_coords(f2)
            process_and_mark(doc_ref, doc_bel, w_ref, w_bel)
            
            for i in range(max(len(doc_ref), len(doc_bel))):
                st.divider()
                col1, col2 = st.columns(2)
                if i < len(doc_ref): col1.image(doc_ref[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
                if i < len(doc_bel): col2.image(doc_bel[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
