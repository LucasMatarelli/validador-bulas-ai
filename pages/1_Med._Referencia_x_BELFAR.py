import streamlit as st
import fitz
import difflib
import re
import unicodedata

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Limpa pontuação e caracteres invisíveis do PDF, garantindo precisão matemática."""
    texto = unicodedata.normalize('NFKC', texto)
    # Removemos pontuação, mas mantemos letras, números e hífens essenciais
    texto_limpo = re.sub(r'[^\w\-]', '', texto)
    return texto_limpo.lower().strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Enterprise", layout="wide")

# ----------------- 2. EXTRAÇÃO DE ALTA PRECISÃO -----------------
def get_words_with_coords(uploaded_file):
    doc = fitz.open("pdf", uploaded_file.getvalue())
    words_data = []

    for p_idx, page in enumerate(doc):
        # sort=True força a leitura na ordem humana (evita embaralhamento de layout)
        words = page.get_text("words", sort=True)
        blocks = page.get_text("dict")["blocks"]

        # Mapeia cirurgicamente onde estão os negritos
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

            # Lógica de intersecção de área matemática (mata o vazamento de negrito)
            is_bold = False
            for span in spans_info:
                intersect = span["rect"] & rect
                # Se pelo menos 40% da palavra está dentro do bloco de negrito original
                if intersect.get_area() > rect.get_area() * 0.4:
                    is_bold = span["is_bold"]
                    break

            words_data.append({
                "page": p_idx,
                "rect": rect,
                "raw": raw_text,
                "clean": clean_text,
                "is_bold": is_bold
            })

    # TRUNCAGEM E MARCAÇÃO AZUL DA ANVISA
    truncate_idx = len(words_data)
    blue_rects = []
    
    for i in range(len(words_data) - 4):
        # Radar âncora: "aprovada pela anvisa em"
        if (words_data[i]["clean"] == "aprovada" and 
            words_data[i+1]["clean"] == "pela" and 
            words_data[i+2]["clean"] == "anvisa" and 
            words_data[i+3]["clean"] == "em"):
            
            # Retrocede para achar o sujeito da frase ("esta" ou "essa")
            start_idx = i
            for k in range(i, max(-1, i - 15), -1):
                if words_data[k]["clean"] in ["esta", "essa"]:
                    start_idx = k
                    break
            
            # Avança para capturar a data final (ex: 2025)
            end_idx = i + 4
            for k in range(i + 4, min(len(words_data), i + 10)):
                end_idx = k
                if re.search(r'\d{4}', words_data[k]["raw"]):
                    end_idx = k + 1
                    break
                    
            truncate_idx = start_idx # Corta o documento EXATAMENTE antes da Anvisa
            
            # Salva os retângulos da frase final para pintar de azul
            for k in range(start_idx, end_idx):
                blue_rects.append((words_data[k]["page"], words_data[k]["rect"]))
            break

    # Retorna os dados cortando o jurídiques do final
    return words_data[:truncate_idx], blue_rects, doc

# ----------------- 3. COMPARAÇÃO MATEMÁTICA E PINTURA -----------------
def paint_rect(doc, page_idx, rect, color, opacity=0.9):
    """Pinta o retângulo no PDF com opacidade totalmente sólida."""
    if rect.is_valid and not rect.is_empty:
        try:
            page = doc[page_idx]
            a = page.add_highlight_annot(rect)
            a.set_colors(stroke=color)
            a.set_opacity(opacity)
            a.update()
        except: pass

def process_and_mark(doc_ref, doc_bel, words_ref, words_bel):
    text_ref = [w["clean"] for w in words_ref]
    text_bel = [w["clean"] for w in words_bel]

    matcher = difflib.SequenceMatcher(None, text_ref, text_bel)
    yellow = (1, 0.9, 0) # Amarelo profissional

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            # Textos idênticos: checa EXCLUSIVAMENTE se o negrito divergiu
            for k in range(i2 - i1):
                w_ref = words_ref[i1 + k]
                w_bel = words_bel[j1 + k]
                if w_ref["is_bold"] != w_bel["is_bold"]:
                    paint_rect(doc_ref, w_ref["page"], w_ref["rect"], yellow, opacity=0.9) # Marcado como 0.9
                    paint_rect(doc_bel, w_bel["page"], w_bel["rect"], yellow, opacity=0.9)
        else:
            # DIVERGÊNCIA ENCONTRADA: Pinta ambos os lados para você nunca perder a diferença
            # Pinta Referência
            for i in range(i1, i2): 
                if i < len(words_ref):
                    paint_rect(doc_ref, words_ref[i]["page"], words_ref[i]["rect"], yellow, opacity=0.9)
            # Pinta Belfar
            for j in range(j1, j2): 
                if j < len(words_bel):
                    paint_rect(doc_bel, words_bel[j]["page"], words_bel[j]["rect"], yellow, opacity=0.9)
def paint_blue_anvisa(doc, blue_rects):
    blue = (0, 0.5, 1)
    for page_idx, rect in blue_rects:
        paint_rect(doc, page_idx, rect, blue, opacity=0.5)

# ----------------- 4. UI -----------------
st.title("💊 Validador Enterprise de Bulas")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Processar Auditoria Exata"):
    if not (f1 and f2):
        st.warning("Por favor, envie os dois arquivos PDF.")
    else:
        with st.spinner("Analisando caracteres, formatação e isolando Anvisa..."):
            w_ref, blue_ref, doc_ref = get_words_with_coords(f1)
            w_bel, blue_bel, doc_bel = get_words_with_coords(f2)
            
            # Compara e pinta as divergências reais
            process_and_mark(doc_ref, doc_bel, w_ref, w_bel)
            
            # Pinta a data da Anvisa de azul
            paint_blue_anvisa(doc_ref, blue_ref)
            paint_blue_anvisa(doc_bel, blue_bel)
            
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
