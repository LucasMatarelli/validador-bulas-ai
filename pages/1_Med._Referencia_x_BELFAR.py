import streamlit as st
import fitz  # PyMuPDF
import difflib
import re

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Normaliza o texto para garantir consistência na comparação."""
    texto = texto.lower()
    texto = re.sub(r'\[B\]|\[/B\]', '', texto)
    texto = re.sub(r'[ \t\r\n]+', ' ', texto)
    return texto.strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas", layout="wide")

# ----------------- 2. LÓGICA DE COMPARAÇÃO E ANOTAÇÃO -----------------
def get_divergences(ref_text, belfar_text):
    """Compara os textos e retorna as palavras que não batem."""
    ref_words = Sub_PreencherMapaDeVendas_Final_V29(ref_text).split()
    bel_words = Sub_PreencherMapaDeVendas_Final_V29(belfar_text).split()
    
    matcher = difflib.SequenceMatcher(None, ref_words, bel_words)
    divergentes = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            trecho = " ".join(bel_words[j1:j2])
            if len(trecho) > 3: # Filtra palavras muito curtas/ruído
                divergentes.append(trecho)
    return divergentes

def annotate_pdf(uploaded_file, divergencias):
    """Aplica marca-texto azul (Anvisa) e amarelo (divergências)."""
    # Converte o arquivo para bytes de forma segura
    file_bytes = uploaded_file.getvalue()
    doc = fitz.open("pdf", file_bytes)
    
    for page in doc:
        # 1. Marca Data Anvisa (Azul)
        anvisa_pattern = r"esta bula foi aprovada pela anvisa em"
        for inst in page.search_for(anvisa_pattern, flags=fitz.TEXT_PRESERVE_WHITESPACE):
            a = page.add_highlight_annot(inst)
            a.set_colors(stroke=(0, 0.5, 1)) # Azul
            a.set_opacity(0.4)
            a.update()
        
        # 2. Marca Divergências (Amarelo)
        for div in divergencias:
            for inst in page.search_for(div):
                a = page.add_highlight_annot(inst)
                a.set_colors(stroke=(1, 0.85, 0)) # Amarelo
                a.set_opacity(0.4)
                a.update()
    return doc

# ----------------- 3. UI PRINCIPAL -----------------
st.title("💊 Comparador Visual de Bulas")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Comparar e Marcar"):
    if not (f1 and f2):
        st.warning("Envie os dois arquivos PDF.")
    else:
        with st.spinner("Analisando e pintando divergências..."):
            # Extração de texto para comparação (acessando via getvalue para segurança)
            t_ref = fitz.open("pdf", f1.getvalue()).get_page_text(0) # Exemplo: página 1
            t_bel = fitz.open("pdf", f2.getvalue()).get_page_text(0)
            
            # Identifica as divergências
            divs = get_divergences(t_ref, t_bel)
            
            # Processa os PDFs anotando
            doc_ref = annotate_pdf(f1, []) # Ref só marca Anvisa
            doc_bel = annotate_pdf(f2, divs) # Belfar marca Anvisa + Divergências
            
            # Exibição Lado a Lado
            max_pag = max(len(doc_ref), len(doc_bel))
            
            for i in range(max_pag):
                st.divider()
                st.subheader(f"Página {i+1}")
                col_r, col_b = st.columns(2)
                
                with col_r:
                    if i < len(doc_ref):
                        pix = doc_ref.load_page(i).get_pixmap(matrix=fitz.Matrix(2, 2))
                        st.image(pix.tobytes("png"), use_container_width=True)
                
                with col_b:
                    if i < len(doc_bel):
                        pix = doc_bel.load_page(i).get_pixmap(matrix=fitz.Matrix(2, 2))
                        st.image(pix.tobytes("png"), use_container_width=True)
