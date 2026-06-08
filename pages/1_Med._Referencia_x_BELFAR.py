import streamlit as st
import fitz
import difflib
import re

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Limpa o texto mantendo a estrutura da linha."""
    # Remove tags internas, mas mantém a estrutura de frases
    texto = re.sub(r'\[B\]|\[/B\]', '', texto)
    return texto.lower().strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Pro", layout="wide")

# ----------------- 2. EXTRAÇÃO DE LINHAS COM ESTILO -----------------
def get_lines_with_style(uploaded_file):
    doc = fitz.open("pdf", uploaded_file.getvalue())
    lines_data = []
    
    for p_idx, page in enumerate(doc):
        # Truncagem rígida
        page_text = page.get_text()
        if "esta bula foi aprovada pela anvisa em" in page_text.lower():
            break
            
        blocks = page.get_text("dict")["blocks"]
        for b in blocks:
            if "lines" in b:
                for l in b["lines"]:
                    line_text = ""
                    is_bold = False
                    for s in l["spans"]:
                        line_text += s["text"]
                        if s["flags"] & 2**4 or "bold" in s["font"].lower():
                            is_bold = True
                    
                    if line_text.strip():
                        lines_data.append({
                            "page": p_idx,
                            "rect": fitz.Rect(l["bbox"]),
                            "text": line_text.strip(),
                            "is_bold": is_bold
                        })
    return lines_data, doc

# ----------------- 3. COMPARAÇÃO E PINTURA -----------------
def process_and_mark(doc_ref, doc_bel, lines_ref, lines_bel):
    text_ref = [Sub_PreencherMapaDeVendas_Final_V29(l["text"]) for l in lines_ref]
    text_bel = [Sub_PreencherMapaDeVendas_Final_V29(l["text"]) for l in lines_bel]
    
    matcher = difflib.SequenceMatcher(None, text_ref, text_bel)
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            # Verifica se o negrito mudou mesmo com o texto igual
            for k in range(i2 - i1):
                idx_ref, idx_bel = i1 + k, j1 + k
                if idx_ref < len(lines_ref) and idx_bel < len(lines_bel):
                    if lines_ref[idx_ref]["is_bold"] != lines_bel[idx_bel]["is_bold"]:
                        # Se negrito diferente, marca
                        w = lines_bel[idx_bel]
                        try:
                            a = doc_bel[w["page"]].add_highlight_annot(w["rect"])
                            a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.6); a.update()
                        except: pass
            continue
            
        # Marca divergências de conteúdo
        if tag in ['insert', 'replace']:
            for i in range(j1, j2):
                w = lines_bel[i]
                try:
                    a = doc_bel[w["page"]].add_highlight_annot(w["rect"])
                    a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.6); a.update()
                except: pass
        if tag in ['delete', 'replace']:
            for i in range(i1, i2):
                w = lines_ref[i]
                try:
                    a = doc_ref[w["page"]].add_highlight_annot(w["rect"])
                    a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.6); a.update()
                except: pass

def mark_anvisa(doc):
    for page in doc:
        for inst in page.search_for("esta bula foi aprovada pela anvisa em"):
            try:
                a = page.add_highlight_annot(inst)
                a.set_colors(stroke=(0, 0.5, 1)); a.set_opacity(0.4); a.update()
            except: pass

# ----------------- 4. UI -----------------
st.title("💊 Validador de Bulas (Detecção por Linha)")
c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Comparar Linha por Linha"):
    if not (f1 and f2):
        st.warning("Envie os arquivos.")
    else:
        with st.spinner("Analisando estrutura..."):
            lines_ref, doc_ref = get_lines_with_style(f1)
            lines_bel, doc_bel = get_lines_with_style(f2)
            
            process_and_mark(doc_ref, doc_bel, lines_ref, lines_bel)
            mark_anvisa(doc_ref)
            mark_anvisa(doc_bel)
            
            max_pag = max(len(doc_ref), len(doc_bel))
            for i in range(max_pag):
                st.divider()
                c_r, c_b = st.columns(2)
                if i < len(doc_ref): c_r.image(doc_ref[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
                if i < len(doc_bel): c_b.image(doc_bel[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
