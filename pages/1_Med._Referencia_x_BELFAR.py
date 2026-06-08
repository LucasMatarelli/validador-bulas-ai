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
st.set_page_config(page_title="Validador de Bulas", layout="wide")

# ----------------- 2. FUNÇÕES DE PROCESSAMENTO -----------------
def extract_text_page_by_page(uploaded_file):
    """Extrai texto e imagens página por página, aplicando a Sub obrigatória."""
    uploaded_file.seek(0)
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    paginas_texto = []
    paginas_img = []
    
    for page in doc:
        # Extração de texto página a página
        txt = page.get_text()
        # Aplicação da sub obrigatória
        paginas_texto.append(Sub_PreencherMapaDeVendas_Final_V29(txt))
        
        # Renderiza imagem da página
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        paginas_img.append(pix.tobytes("png"))
        
    return paginas_texto, paginas_img

def get_divergences(ref_text, belfar_text):
    """Compara os textos e retorna as palavras que não batem."""
    ref_words = ref_text.split()
    bel_words = belfar_text.split()
    
    matcher = difflib.SequenceMatcher(None, ref_words, bel_words)
    divergentes = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            trecho = " ".join(bel_words[j1:j2])
            if len(trecho) > 3:
                divergentes.append(trecho)
    return divergentes

# ----------------- 3. UI PRINCIPAL -----------------
st.title("💊 Comparador Visual de Bulas")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Iniciar Comparação"):
    if not (f1 and f2):
        st.warning("Envie os dois arquivos.")
    else:
        with st.spinner("Processando..."):
            # Extração
            textos_ref, imgs_ref = extract_text_page_by_page(f1)
            textos_bel, imgs_bel = extract_text_page_by_page(f2)
            
            # Exibição
            max_pag = max(len(imgs_ref), len(imgs_bel))
            
            for i in range(max_pag):
                st.divider()
                st.subheader(f"Página {i+1}")
                
                # Comparação visual
                col1, col2 = st.columns(2)
                with col1:
                    st.caption("📜 Bula Referência")
                    if i < len(imgs_ref): st.image(imgs_ref[i], use_container_width=True)
                
                with col2:
                    st.caption("📜 Bula BELFAR")
                    if i < len(imgs_bel): 
                        # Aqui rodamos a comparação na página atual
                        divs = get_divergences(textos_ref[i], textos_bel[i])
                        if divs:
                            st.warning(f"⚠️ Divergências detectadas: {len(divs)}")
                            # Dica: o st.image abaixo mostra a página limpa, 
                            # para pintar o PDF seria necessário integrar a função de annotation
                        st.image(imgs_bel[i], use_container_width=True)
