import streamlit as st
import fitz
import difflib
import re

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Limpa pontuação que causa falsos positivos, mas preserva hífens (ex: Stevens-Johnson)"""
    # Remove tudo que não for letra, número ou hífen
    texto_limpo = re.sub(r'[^\w\-]', '', texto)
    return texto_limpo.lower().strip()

# Lista de marcas/termos esperados que NÃO devem ser marcados como divergência
IGNORE_LIST = [
    'sanofi', 'medley', 'belfar', 'flagyl', 'flagimax', 'agimax', 
    'urotrobel', 'norfloxacino', 'ltda', 'farmacêutica', 'opella', 'healthcare', 'brazil'
]

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Definitivo", layout="wide")

# ----------------- 2. EXTRAÇÃO EXATA -----------------
def get_words_with_coords(uploaded_file):
    """Extrai palavra por palavra, guardando a coordenada e o status de negrito."""
    doc = fitz.open("pdf", uploaded_file.getvalue())
    words_data = []
    stop_flag = False

    for p_idx, page in enumerate(doc):
        # Truncagem exata na Anvisa
        if "esta bula foi aprovada pela anvisa em" in page.get_text().lower():
            stop_flag = True

        words = page.get_text("words")
        blocks = page.get_text("dict")["blocks"]

        # Pré-calcula os blocos de negrito para não perder performance
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

            # Pula símbolos que ficaram vazios após a limpeza (ex: vírgulas soltas)
            if not clean_text: continue 

            # Verifica se a palavra está dentro de um bloco em negrito
            is_bold = False
            for span in spans_info:
                if span["rect"].intersects(rect):
                    is_bold = span["is_bold"]
                    break

            words_data.append({
                "page": p_idx,
                "rect": rect,
                "raw": raw_text,
                "clean": clean_text,
                "is_bold": is_bold
            })

        if stop_flag: break # Para de ler o documento após a página da Anvisa
    return words_data, doc

# ----------------- 3. COMPARAÇÃO E PINTURA -----------------
def paint_rect(doc, word_data):
    """Função segura para pintar o retângulo no PDF."""
    if word_data["rect"].is_valid and not word_data["rect"].is_empty:
        try:
            page = doc[word_data["page"]]
            a = page.add_highlight_annot(word_data["rect"])
            a.set_colors(stroke=(1, 0.85, 0)) # Amarelo exato
            a.set_opacity(0.6)
            a.update()
        except: pass

def process_and_mark(doc_ref, doc_bel, words_ref, words_bel):
    """Compara as bulas e marca apenas as divergências reais."""
    text_ref = [w["clean"] for w in words_ref]
    text_bel = [w["clean"] for w in words_bel]

    matcher = difflib.SequenceMatcher(None, text_ref, text_bel)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            # Se o texto é igual, verifica o NEGRITO
            for k in range(i2 - i1):
                w_ref = words_ref[i1 + k]
                w_bel = words_bel[j1 + k]
                # Só pinta se um for True e o outro False
                if w_ref["is_bold"] != w_bel["is_bold"]:
                    paint_rect(doc_ref, w_ref)
                    paint_rect(doc_bel, w_bel)
                    
        elif tag == 'replace':
            for i in range(i1, i2):
                if words_ref[i]["clean"] not in IGNORE_LIST: paint_rect(doc_ref, words_ref[i])
            for j in range(j1, j2):
                if words_bel[j]["clean"] not in IGNORE_LIST: paint_rect(doc_bel, words_bel[j])
                
        elif tag == 'delete': # Falta na Belfar
            for i in range(i1, i2):
                if words_ref[i]["clean"] not in IGNORE_LIST: paint_rect(doc_ref, words_ref[i])
                
        elif tag == 'insert': # Sobrando na Belfar
            for j in range(j1, j2):
                if words_bel[j]["clean"] not in IGNORE_LIST: paint_rect(doc_bel, words_bel[j])

def mark_anvisa(doc):
    """Pinta a frase da Anvisa de azul."""
    for page in doc:
        for inst in page.search_for("esta bula foi aprovada pela anvisa em", flags=fitz.TEXT_PRESERVE_WHITESPACE):
            try:
                a = page.add_highlight_annot(inst)
                a.set_colors(stroke=(0, 0.5, 1)) # Azul
                a.set_opacity(0.4)
                a.update()
            except: pass

# ----------------- 4. UI PRINCIPAL -----------------
st.title("💊 Validador Definitivo de Bulas")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Validar Divergências"):
    if not (f1 and f2):
        st.warning("Por favor, envie os dois arquivos PDF.")
    else:
        with st.spinner("Realizando comparação exata..."):
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
