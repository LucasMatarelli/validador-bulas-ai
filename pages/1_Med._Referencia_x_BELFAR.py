import streamlit as st
import fitz
import difflib
import re

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Normaliza o texto mantendo a estrutura dos blocos."""
    texto = texto.lower()
    # Remove espaços duplos e quebras, mas preserva a ordem das frases
    texto = re.sub(r'[ \t\r\n]+', ' ', texto)
    return texto.strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Pro", layout="wide")

# ----------------- 2. LÓGICA DE COMPARAÇÃO -----------------
def truncate_at_anvisa(text):
    """Corta o texto na data da Anvisa."""
    pattern = r"esta bula foi aprovada pela anvisa em"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return text[:match.start()]
    return text

def extract_blocks(uploaded_file):
    """Extrai blocos de texto (parágrafos) de forma estruturada."""
    doc = fitz.open("pdf", uploaded_file.getvalue())
    blocks_data = []
    full_content = ""
    
    for page in doc:
        text = page.get_text("text")
        full_content += text
    
    # Aplica truncagem antes de processar
    full_content = truncate_at_anvisa(full_content)
    
    # Divide em parágrafos para comparação estruturada
    paragraphs = [p for p in full_content.split('\n') if len(p.strip()) > 3]
    return paragraphs

def get_divergences(ref_paras, bel_paras):
    """Compara parágrafo por parágrafo."""
    matcher = difflib.SequenceMatcher(None, 
                                      [Sub_PreencherMapaDeVendas_Final_V29(p) for p in ref_paras], 
                                      [Sub_PreencherMapaDeVendas_Final_V29(p) for p in bel_paras])
    
    ref_divergent_texts = []
    bel_divergent_texts = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            # Se a Referência tem algo diferente/a mais
            if tag in ['delete', 'replace']:
                ref_divergent_texts.extend(ref_paras[i1:i2])
            # Se a Belfar tem algo diferente/a mais
            if tag in ['insert', 'replace']:
                bel_divergent_texts.extend(bel_paras[j1:j2])
                
    return ref_divergent_texts, bel_divergent_texts

def annotate_pdf(doc, divergences):
    """Pinta as divergências encontradas."""
    for page in doc:
        for div in divergences:
            # Busca o trecho divergente (usando uma parte curta dele para garantir match)
            snippet = div[:30] 
            for inst in page.search_for(snippet):
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

if st.button("🚀 Comparar Bula Completa"):
    if f1 and f2:
        with st.spinner("Analisando estrutura e divergências..."):
            # Extração
            ref_paras = extract_blocks(f1)
            bel_paras = extract_blocks(f2)
            
            # Comparação (agora por blocos)
            ref_divs, bel_divs = get_divergences(ref_paras, bel_paras)
            
            # Anotação em ambos os documentos
            f1.seek(0); f2.seek(0)
            doc_ref = annotate_pdf(fitz.open("pdf", f1.getvalue()), ref_divs)
            doc_bel = annotate_pdf(fitz.open("pdf", f2.getvalue()), bel_divs)
            
            # Exibição Lado a Lado
            max_pag = max(len(doc_ref), len(doc_bel))
            for i in range(max_pag):
                st.divider()
                col_r, col_b = st.columns(2)
                with col_r:
                    if i < len(doc_ref):
                        st.image(doc_ref[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
                with col_b:
                    if i < len(doc_bel):
                        st.image(doc_bel[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"), use_container_width=True)
