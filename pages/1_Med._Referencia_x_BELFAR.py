import streamlit as st
import fitz  # PyMuPDF
import difflib
import re

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Normaliza o texto extraído para garantir consistência na comparação."""
    texto = texto.lower()
    # Remove tags de negrito e caracteres especiais, mantendo só o conteúdo textual
    texto = re.sub(r'\[B\]|\[/B\]', '', texto)
    texto = re.sub(r'[ \t\r\n]+', ' ', texto)
    return texto.strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas com Marca-Texto", layout="wide")

# ----------------- 2. FUNÇÕES DE PROCESSAMENTO -----------------
def get_divergences(ref_text, belfar_text):
    """Compara os textos e retorna as palavras que não batem."""
    ref_words = Sub_PreencherMapaDeVendas_Final_V29(ref_text).split()
    bel_words = Sub_PreencherMapaDeVendas_Final_V29(belfar_text).split()
    
    matcher = difflib.SequenceMatcher(None, ref_words, bel_words)
    divergentes = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            trecho = " ".join(bel_words[j1:j2])
            if len(trecho) > 3: # Filtra ruídos
                divergentes.append(trecho)
    return divergentes

def process_and_highlight(uploaded_file, divergencias):
    """Aplica marca-texto azul (Anvisa) e amarelo (divergências) no PDF."""
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    
    for page in doc:
        # 1. Marca Data Anvisa (Azul)
        # Busca o padrão de texto da Anvisa
        anvisa_pattern = r"(esta bula foi aprovada pela anvisa em \d{2}/\d{2}/\d{4})"
        for inst in page.search_for(anvisa_pattern, flags=fitz.TEXT_PRESERVE_WHITESPACE):
            a = page.add_highlight_annot(inst)
            a.set_colors(stroke=(0, 0.5, 1)) # Azul
            a.set_opacity(0.4)
            a.update()
        
        # 2. Marca Divergências (Amarelo)
        for div in divergencias:
            # Procura a divergência na página
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
        st.warning("Envie os dois arquivos.")
    else:
        with st.spinner("Analisando e pintando divergências..."):
            # Extração de texto para comparação
            f1.seek(0); t_ref = fitz.open(stream=f1.read(), filetype="pdf").get_text()
            f2.seek(0); t_bel = fitz.open(stream=f2.read(), filetype="pdf").get_text()
            
            # Identifica as divergências
            divs = get_divergences(t_ref, t_bel)
            
            # Processa os PDFs anotando
            f1.seek(0); f2.seek(0)
            doc_ref = process_and_highlight(f1, []) # Ref só marca Anvisa
            doc_bel = process_and_highlight(f2, divs) # Belfar marca Anvisa + Divergências
            
            # Exibição
            max_pag = max(len(doc_ref), len(doc_bel))
            
            for i in range(max_pag):
                st.divider()
                col_r, col_b = st.columns(2)
                
                with col_r:
                    st.caption(f"Referência (Pág {i+1})")
                    if i < len(doc_ref):
                        pix = doc_ref.load_page(i).get_pixmap(matrix=fitz.Matrix(2, 2))
                        st.image(pix.tobytes("png"), use_container_width=True)
                
                with col_b:
                    st.caption(f"BELFAR (Pág {i+1})")
                    if i < len(doc_bel):
                        pix = doc_bel.load_page(i).get_pixmap(matrix=fitz.Matrix(2, 2))
                        st.image(pix.tobytes("png"), use_container_width=True)
