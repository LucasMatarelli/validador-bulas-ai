import streamlit as st
import fitz
import difflib
import re
import unicodedata

# ----------------- CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador Linha a Linha", layout="wide")

def Sub_LimparTexto(texto):
    texto = unicodedata.normalize('NFKC', texto)
    return re.sub(r'[^\w\-]', '', texto).lower().strip()

# ----------------- EXTRAÇÃO POR LINHAS -----------------
def get_lines_with_coords(uploaded_file):
    doc = fitz.open("pdf", uploaded_file.getvalue())
    lines_data = []

    for p_idx, page in enumerate(doc):
        # Extrai dicionário para pegar blocos/linhas exatos
        blocks = page.get_text("dict")["blocks"]
        for b in blocks:
            if "lines" in b:
                for l in b["lines"]:
                    # Calcula o retângulo da linha inteira
                    line_rect = fitz.Rect(l["bbox"])
                    # Pega o texto da linha
                    line_text = "".join([s["text"] for s in l["spans"]])
                    clean_text = Sub_LimparTexto(line_text)
                    
                    if not clean_text: continue
                    
                    lines_data.append({
                        "page": p_idx,
                        "rect": line_rect,
                        "clean": clean_text,
                        "raw": line_text
                    })
    return lines_data, doc

# ----------------- PINTURA DE LINHA -----------------
def paint_line(doc, page_idx, rect, color=(1, 1, 0), opacity=0.8):
    if rect.is_valid and not rect.is_empty:
        try:
            page = doc[page_idx]
            a = page.add_highlight_annot(rect)
            a.set_colors(stroke=color)
            a.set_opacity(opacity)
            a.update()
        except: pass

def process_and_mark_lines(doc_ref, doc_bel, lines_ref, lines_bel):
    text_ref = [l["clean"] for l in lines_ref]
    text_bel = [l["clean"] for l in lines_bel]

    matcher = difflib.SequenceMatcher(None, text_ref, text_bel)
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'replace' or tag == 'insert' or tag == 'delete':
            # Pinta a linha inteira de amarelo se houver divergência
            for i in range(i1, i2): 
                paint_line(doc_ref, lines_ref[i]["page"], lines_ref[i]["rect"])
            for j in range(j1, j2): 
                paint_line(doc_bel, lines_bel[j]["page"], lines_bel[j]["rect"])

# ----------------- UI -----------------
st.title("🛡️ Validador: Marcação Linha a Linha")
c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Processar Auditoria"):
    if f1 and f2:
        l_ref, doc_ref = get_lines_with_coords(f1)
        l_bel, doc_bel = get_lines_with_coords(f2)
        
        process_and_mark_lines(doc_ref, doc_bel, l_ref, l_bel)
        
        # Exibição
        max_pag = max(len(doc_ref), len(doc_bel))
        for i in range(max_pag):
            st.divider()
            col_r, col_b = st.columns(2)
            if i < len(doc_ref):
                col_r.image(doc_ref[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
            if i < len(doc_bel):
                col_b.image(doc_bel[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
