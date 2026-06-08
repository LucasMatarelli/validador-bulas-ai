import streamlit as st
import fitz
import difflib
import re
import unicodedata

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Limpa pontuação e normaliza caracteres do PDF para garantir 100% de precisão."""
    # A NFKD normaliza caracteres especiais (evita que acentos e símbolos sejam lidos errado)
    texto = unicodedata.normalize('NFKD', texto)
    # Remove tudo que não for letra ou número (exceto hífen de palavras compostas)
    texto_limpo = re.sub(r'[^\w\-]', '', texto)
    return texto_limpo.lower().strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Enterprise", layout="wide")

# ----------------- 2. EXTRAÇÃO DE ALTA PRECISÃO -----------------
def get_words_with_coords(uploaded_file):
    doc = fitz.open("pdf", uploaded_file.getvalue())
    words_data = []

    for p_idx, page in enumerate(doc):
        # Lê a página na ordem correta de leitura (sort=True)
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

            # Lógica de intersecção: Só marca negrito se a palavra estiver DENTRO do bloco
            is_bold = False
            for span in spans_info:
                if span["rect"].intersects(rect) and span["rect"].get_area() > 0:
                    is_bold = span["is_bold"]
                    break

            words_data.append({
                "page": p_idx,
                "rect": rect,
                "raw": raw_text,
                "clean": clean_text,
                "is_bold": is_bold
            })
    return words_data, doc

# ----------------- 3. COMPARAÇÃO MATEMÁTICA E PINTURA (SÓLIDA) -----------------
def paint_rect(doc, page_idx, rect, color=(1, 1, 0)): # Amarelo puro
    if rect.is_valid and not rect.is_empty:
        try:
            page = doc[page_idx]
            a = page.add_highlight_annot(rect)
            a.set_colors(stroke=color)
            a.set_opacity(0.7) # Cor sólida, sem transparência excessiva
            a.update()
        except: pass

def process_and_mark(doc_ref, doc_bel, words_ref, words_bel):
    text_ref = [w["clean"] for w in words_ref]
    text_bel = [w["clean"] for w in words_bel]

    matcher = difflib.SequenceMatcher(None, text_ref, text_bel)
    yellow = (1, 1, 0) # Amarelo vibrante

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            # Texto idêntico: Checa apenas se o negrito divergiu
            for k in range(i2 - i1):
                w_ref = words_ref[i1 + k]
                w_bel = words_bel[j1 + k]
                if w_ref["is_bold"] != w_bel["is_bold"]:
                    paint_rect(doc_ref, w_ref["page"], w_ref["rect"], yellow)
                    paint_rect(doc_bel, w_bel["page"], w_bel["rect"], yellow)
        else:
            # Qualquer diferença de texto: Pinta ambos para mostrar a divergência
            for i in range(i1, i2): paint_rect(doc_ref, words_ref[i]["page"], words_ref[i]["rect"], yellow)
            for j in range(j1, j2): paint_rect(doc_bel, words_bel[j]["page"], words_bel[j]["rect"], yellow)

# ----------------- 4. UI -----------------
st.title("💊 Validador de Bulas Enterprise")
c1, c2 = st.columns(2)
f1 = c1.file_uploader("Bula Referência", type=["pdf"])
f2 = c2.file_uploader("Bula BELFAR", type=["pdf"])

if st.button("🚀 Processar Auditoria Exata"):
    if f1 and f2:
        with st.spinner("Analisando página por página..."):
            w_ref, doc_ref = get_words_with_coords(f1)
            w_bel, doc_bel = get_words_with_coords(f2)
            process_and_mark(doc_ref, doc_bel, w_ref, w_bel)
            
            for i in range(max(len(doc_ref), len(doc_bel))):
                st.divider()
                col_r, col_b = st.columns(2)
                if i < len(doc_ref): col_r.image(doc_ref[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
                if i < len(doc_bel): col_b.image(doc_bel[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
