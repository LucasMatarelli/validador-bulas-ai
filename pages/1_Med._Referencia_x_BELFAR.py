import streamlit as st
import fitz  # PyMuPDF
import difflib
import re

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Limpa o texto para garantir uma comparação justa, sem ruídos de formatação."""
    # Remove tags de negrito para comparar o conteúdo puro
    texto = re.sub(r'\[B\]|\[/B\]', '', texto)
    # Remove quebras de linha e espaços extras
    texto = re.sub(r'[ \t\r\n]+', ' ', texto)
    return texto.lower().strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Visual", layout="wide")

# ----------------- 2. LÓGICA DE COMPARAÇÃO -----------------
def get_divergences(ref_text, belfar_text):
    """Compara as bulas e retorna as palavras que divergem."""
    # Normaliza antes de comparar
    ref_norm = Sub_PreencherMapaDeVendas_Final_V29(ref_text).split()
    bel_norm = Sub_PreencherMapaDeVendas_Final_V29(belfar_text).split()
    
    matcher = difflib.SequenceMatcher(None, ref_norm, bel_norm)
    divergentes = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            # Captura o trecho da Belfar que é diferente
            trecho = " ".join(bel_norm[j1:j2])
            if len(trecho) > 3: # Filtra ruídos muito curtos
                divergentes.append(trecho)
    return divergentes

# ----------------- 3. PINTURA DOS PDFs -----------------
def annotate_pdf(pdf_stream, divergences, highlight_anvisa=True):
    doc = fitz.open(stream=pdf_stream, filetype="pdf")
    annotated_pages = []
    
    for page in doc:
        # 1. Marca Data Anvisa (Azul)
        if highlight_anvisa:
            anvisa_pattern = r"esta bula foi aprovada pela anvisa em \d{2}/\d{2}/\d{4}"
            for inst in page.search_for(anvisa_pattern, flags=fitz.TEXT_PRESERVE_WHITESPACE):
                a = page.add_highlight_annot(inst)
                a.set_colors(stroke=(0, 0.5, 1)) # Azul
                a.set_opacity(0.3)
                a.update()
        
        # 2. Marca Divergências (Amarelo)
        for div in divergences:
            for inst in page.search_for(div):
                a = page.add_highlight_annot(inst)
                a.set_colors(stroke=(1, 0.85, 0)) # Amarelo
                a.set_opacity(0.3)
                a.update()
        
        pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))
        annotated_pages.append(pix.tobytes("png"))
    
    return annotated_pages

# ----------------- 4. UI -----------------
st.title("💊 Comparador de Bulas (Side-by-Side)")
c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Iniciar Auditoria"):
    if f1 and f2:
        # Extração de texto para comparação
        t_ref = fitz.open(stream=f1.read(), filetype="pdf").get_text()
        t_bel = fitz.open(stream=f2.read(), filetype="pdf").get_text()
        
        # Identifica divergências matematicamente
        divs = get_divergences(t_ref, t_bel)
        
        # Anota e renderiza
        f1.seek(0); f2.seek(0)
        imgs_ref = annotate_pdf(f1.read(), [], highlight_anvisa=True) # Referencia só marca Anvisa
        f2.seek(0)
        imgs_bel = annotate_pdf(f2.read(), divs, highlight_anvisa=True) # Belfar marca tudo
        
        # Exibe Lado a Lado
        max_pag = max(len(imgs_ref), len(imgs_bel))
        for i in range(max_pag):
            st.divider()
            col_r, col_b = st.columns(2)
            with col_r:
                st.subheader(f"Referência (Pág {i+1})")
                if i < len(imgs_ref): st.image(imgs_ref[i], use_container_width=True)
            with col_b:
                st.subheader(f"BELFAR (Pág {i+1})")
                if i < len(imgs_bel): st.image(imgs_bel[i], use_container_width=True)
    else:
        st.error("Carregue ambos os arquivos.")
