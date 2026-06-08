import streamlit as st
import fitz  # PyMuPDF
import difflib
import re

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Normaliza o texto para garantir consistência na comparação."""
    # Remove tudo que não for letra ou número para comparar apenas o conteúdo
    texto = re.sub(r'[^a-zA-Z0-9]', '', texto)
    return texto.lower().strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador Pro", layout="wide")

# ----------------- 2. FUNÇÕES DE PROCESSAMENTO -----------------
def get_words_with_coords(doc):
    """Extrai todas as palavras do PDF com suas coordenadas."""
    words_data = []
    for page_num, page in enumerate(doc):
        words = page.get_text("words") # Retorna (x0, y0, x1, y1, "texto", block_no, line_no, word_no)
        words_data.append(words)
    return words_data

def compare_and_mark(doc_ref, doc_bel):
    """Compara as listas de palavras e pinta as divergências na Belfar."""
    
    # Processa as listas de palavras
    all_words_ref = []
    for p in doc_ref: all_words_ref.extend(p.get_text("words"))
    
    all_words_bel = []
    for p in doc_bel: all_words_bel.extend(p.get_text("words"))

    # Extrai só o texto para o comparador
    text_ref = [Sub_PreencherMapaDeVendas_Final_V29(w[4]) for w in all_words_ref]
    text_bel = [Sub_PreencherMapaDeVendas_Final_V29(w[4]) for w in all_words_bel]
    
    matcher = difflib.SequenceMatcher(None, text_ref, text_bel)
    
    # Itera sobre as diferenças encontradas
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal': continue
        
        # Se for divergente, pinta as palavras correspondentes na Belfar
        for idx in range(j1, j2):
            word_obj = all_words_bel[idx]
            page_idx = -1 # Precisamos achar a página
            # (Simplificação: busca a página pela palavra)
            for p_idx, p_words in enumerate(doc_bel):
                if word_obj in p_words.get_text("words"):
                    page_idx = p_idx
                    break
            
            if page_idx != -1:
                page = doc_bel[page_idx]
                rect = fitz.Rect(word_obj[0], word_obj[1], word_obj[2], word_obj[3])
                annot = page.add_highlight_annot(rect)
                annot.set_colors(stroke=(1, 0.85, 0)) # Amarelo
                annot.set_opacity(0.4)
                annot.update()

# ----------------- 3. UI PRINCIPAL -----------------
st.title("💊 Comparador Visual de Bulas (Nível Palavra)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Comparar Documentos"):
    if not (f1 and f2):
        st.warning("Envie os arquivos.")
    else:
        with st.spinner("Analisando palavra por palavra..."):
            doc_ref = fitz.open("pdf", f1.getvalue())
            doc_bel = fitz.open("pdf", f2.getvalue())
            
            # Executa a comparação e pintura
            compare_and_mark(doc_ref, doc_bel)
            
            # Anvisa (Marcador Azul extra)
            for page in doc_bel:
                for inst in page.search_for("esta bula foi aprovada pela anvisa em"):
                    a = page.add_highlight_annot(inst)
                    a.set_colors(stroke=(0, 0.5, 1)); a.set_opacity(0.3); a.update()

            # Exibição
            for i in range(len(doc_bel)):
                st.divider()
                st.subheader(f"Página {i+1}")
                col_r, col_b = st.columns(2)
                
                with col_r:
                    st.image(doc_ref[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
                with col_b:
                    st.image(doc_bel[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
