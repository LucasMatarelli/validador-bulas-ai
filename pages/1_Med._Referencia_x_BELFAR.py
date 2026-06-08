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
st.set_page_config(page_title="Validador de Bulas Completo", layout="wide")

# ----------------- 2. LÓGICA DE PROCESSAMENTO -----------------
def extract_full_text(uploaded_file):
    """Extrai o texto completo de todas as páginas do PDF."""
    doc = fitz.open("pdf", uploaded_file.getvalue())
    full_text = ""
    for page in doc:
        full_text += page.get_text()
    return Sub_PreencherMapaDeVendas_Final_V29(full_text)

def get_divergences(ref_text, belfar_text):
    """Compara os textos completos e retorna as frases divergentes."""
    ref_words = ref_text.split()
    bel_words = belfar_text.split()
    
    matcher = difflib.SequenceMatcher(None, ref_words, bel_words)
    divergentes = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            # Captura blocos de texto divergentes (trechos de 5 a 10 palavras)
            trecho = " ".join(bel_words[j1:j2])
            if len(trecho.split()) >= 3: 
                divergentes.append(trecho)
    return list(set(divergentes)) # Remove duplicados

def annotate_doc(uploaded_file, divergencias):
    """Aplica marcações em TODAS as páginas do documento."""
    doc = fitz.open("pdf", uploaded_file.getvalue())
    
    for page in doc:
        # 1. Marca Data Anvisa (Azul) - Padrão Geral
        anvisa_pattern = r"esta bula foi aprovada pela anvisa em"
        for inst in page.search_for(anvisa_pattern, flags=fitz.TEXT_PRESERVE_WHITESPACE):
            a = page.add_highlight_annot(inst)
            a.set_colors(stroke=(0, 0.5, 1))
            a.set_opacity(0.3)
            a.update()
        
        # 2. Marca Divergências (Amarelo)
        for div in divergencias:
            for inst in page.search_for(div):
                a = page.add_highlight_annot(inst)
                a.set_colors(stroke=(1, 0.85, 0))
                a.set_opacity(0.3)
                a.update()
    return doc

# ----------------- 3. UI PRINCIPAL -----------------
st.title("💊 Comparador Visual de Bulas (Bula Inteira)")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Iniciar Auditoria Total"):
    if not (f1 and f2):
        st.warning("Envie os dois arquivos.")
    else:
        with st.spinner("Analisando documentos inteiros..."):
            # Extração global
            t_ref = extract_full_text(f1)
            t_bel = extract_full_text(f2)
            
            # Comparação
            divs = get_divergences(t_ref, t_bel)
            
            # Anotação em ambos os documentos
            f1.seek(0); f2.seek(0)
            doc_ref = annotate_doc(f1, divs)
            doc_bel = annotate_doc(f2, divs)
            
            # Exibição Lado a Lado
            max_pag = max(len(doc_ref), len(doc_bel))
            for i in range(max_pag):
                st.divider()
                col_r, col_b = st.columns(2)
                
                with col_r:
                    st.caption(f"Referência - Pág {i+1}")
                    if i < len(doc_ref):
                        pix = doc_ref.load_page(i).get_pixmap(matrix=fitz.Matrix(2, 2))
                        st.image(pix.tobytes("png"), use_container_width=True)
                
                with col_b:
                    st.caption(f"BELFAR - Pág {i+1}")
                    if i < len(doc_bel):
                        pix = doc_bel.load_page(i).get_pixmap(matrix=fitz.Matrix(2, 2))
                        st.image(pix.tobytes("png"), use_container_width=True)
