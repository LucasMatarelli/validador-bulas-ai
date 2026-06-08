import streamlit as st
import fitz
import difflib
import re
import unicodedata

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Limpa pontuação que causa falsos positivos, mas preserva hífens (ex: Stevens-Johnson)."""
    # Normaliza caracteres especiais (evita que letras grudadas no PDF enganem o sistema)
    texto = unicodedata.normalize('NFKC', texto)
    # Mantém apenas letras, números e hífen
    texto_limpo = re.sub(r'[^\w\-]', '', texto)
    return texto_limpo.lower().strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador Definitivo de Bulas", layout="wide")

# ----------------- 2. EXTRAÇÃO E TRUNCAGEM PERFEITA -----------------
def get_words_with_coords(uploaded_file):
    """Extrai palavras pelo centro focal (evita vazamento de negrito) e isola a Anvisa."""
    doc = fitz.open("pdf", uploaded_file.getvalue())
    words_data = []

    for p_idx, page in enumerate(doc):
        words = page.get_text("words")
        blocks = page.get_text("dict")["blocks"]

        # Mapeia onde o negrito está na página
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

            # Calcula o centro da palavra para não ler a formatação da palavra vizinha
            cx = (rect.x0 + rect.x1) / 2
            cy = (rect.y0 + rect.y1) / 2
            pt = fitz.Point(cx, cy)

            is_bold = False
            for span in spans_info:
                if span["rect"].contains(pt):
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
    anvisa_blue_rects = []
    
    for i, w in enumerate(words_data):
        if w["clean"] == "anvisa":
            date_found = False
            # Busca se existe uma data nas próximas 8 palavras
            for j in range(1, 9): 
                if i + j < len(words_data):
                    nums = re.sub(r'[^\d]', '', words_data[i+j]["raw"])
                    if len(nums) >= 6: # Identifica padrão de data (ex: 31072025)
                        truncate_idx = i + j + 1
                        date_found = True
                        break
            
            if date_found:
                # Volta para trás para achar o começo da frase ("esta" ou "essa")
                start_idx = i
                for k in range(i, max(-1, i - 20), -1):
                    if words_data[k]["clean"] in ["esta", "essa", "bula"]:
                        start_idx = k
                        break
                # Coleta as coordenadas exatas da frase inteira para pintar de azul
                for k in range(start_idx, truncate_idx):
                    anvisa_blue_rects.append((words_data[k]["page"], words_data[k]["rect"]))
                break

    # Retorna os dados até a data da Anvisa (ignora Dizeres Legais automaticamente)
    return words_data[:truncate_idx], anvisa_blue_rects, doc

# ----------------- 3. COMPARAÇÃO E PINTURA (SEM BLEFES) -----------------
def paint_rect(doc, page_idx, rect, color):
    """Aplica o marca-texto de forma segura."""
    if rect.is_valid and not rect.is_empty:
        try:
            page = doc[page_idx]
            a = page.add_highlight_annot(rect)
            a.set_colors(stroke=color)
            a.set_opacity(0.6) # Opacidade forte, fim do amarelo fraquinho
            a.update()
        except: pass

def process_and_mark(doc_ref, doc_bel, words_ref, words_bel):
    text_ref = [w["clean"] for w in words_ref]
    text_bel = [w["clean"] for w in words_bel]

    matcher = difflib.SequenceMatcher(None, text_ref, text_bel)
    yellow = (1, 0.85, 0)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            # Textos idênticos: checa EXCLUSIVAMENTE se um tem negrito e outro não
            for k in range(i2 - i1):
                w_ref = words_ref[i1 + k]
                w_bel = words_bel[j1 + k]
                if w_ref["is_bold"] != w_bel["is_bold"]:
                    paint_rect(doc_ref, w_ref["page"], w_ref["rect"], yellow)
                    paint_rect(doc_bel, w_bel["page"], w_bel["rect"], yellow)
                    
        elif tag == 'replace': # Conteúdo divergente (ex: Flagyl vs Flagimax)
            for i in range(i1, i2): paint_rect(doc_ref, words_ref[i]["page"], words_ref[i]["rect"], yellow)
            for j in range(j1, j2): paint_rect(doc_bel, words_bel[j]["page"], words_bel[j]["rect"], yellow)
                
        elif tag == 'delete': # Falta na Belfar
            for i in range(i1, i2): paint_rect(doc_ref, words_ref[i]["page"], words_ref[i]["rect"], yellow)
                
        elif tag == 'insert': # Sobrando na Belfar
            for j in range(j1, j2): paint_rect(doc_bel, words_bel[j]["page"], words_bel[j]["rect"], yellow)

def paint_blue_anvisa(doc, blue_rects):
    blue = (0, 0.5, 1)
    for page_idx, rect in blue_rects:
        paint_rect(doc, page_idx, rect, blue)

# ----------------- 4. UI -----------------
st.title("💊 Validador Definitivo de Bulas")

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
