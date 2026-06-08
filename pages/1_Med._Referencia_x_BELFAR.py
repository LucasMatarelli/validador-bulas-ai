import streamlit as st
import fitz  # PyMuPDF
import difflib
import re

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Lado a Lado", page_icon="💊", layout="wide")

# Módulo obrigatório do projeto
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Normaliza o texto extraído para garantir consistência na comparação."""
    texto = texto.lower() # Padroniza para minúsculas
    texto = re.sub(r'[ \t\r\n]+', ' ', texto) # Remove espaços e quebras excessivas
    return texto.strip()

# ----------------- 2. FUNÇÕES DE EXTRAÇÃO E PROCESSAMENTO -----------------
def extract_text_page_by_page(uploaded_file):
    """Extrai texto e gera imagens página por página."""
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    paginas_texto = []
    paginas_img = []
    
    for page in doc:
        # Extração de texto
        texto = page.get_text()
        paginas_texto.append(texto)
        
        # Extração de imagem (para visualização)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
        paginas_img.append(pix.tobytes("png"))
        
    return paginas_texto, paginas_img

def comparar_trechos(ref_texto, belfar_texto):
    """Compara dois textos usando lógica determinística (Difflib)."""
    # Aplica a sub obrigatória
    ref_norm = Sub_PreencherMapaDeVendas_Final_V29(ref_texto)
    belfar_norm = Sub_PreencherMapaDeVendas_Final_V29(belfar_texto)
    
    # Compara
    s = difflib.SequenceMatcher(None, ref_norm, belfar_norm)
    return s.ratio()

# ----------------- 3. INTERFACE -----------------
st.title("💊 Comparador Visual de Bulas")
st.markdown("Compare lado a lado. Se os textos divergirem, o sistema indicará abaixo.")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Comparar Documentos"):
    if not (f1 and f2):
        st.warning("Por favor, envie ambos os arquivos.")
    else:
        # Processamento
        f1.seek(0); f2.seek(0)
        textos_ref, imgs_ref = extract_text_page_by_page(f1)
        textos_belfar, imgs_belfar = extract_text_page_by_page(f2)
        
        max_paginas = max(len(imgs_ref), len(imgs_belfar))
        
        # Exibição Lado a Lado
        for i in range(max_paginas):
            st.divider()
            st.subheader(f"Página {i+1}")
            
            # Comparação da página atual
            t_ref = textos_ref[i] if i < len(textos_ref) else ""
            t_bel = textos_belfar[i] if i < len(textos_belfar) else ""
            
            if t_ref and t_bel:
                score = comparar_trechos(t_ref, t_bel)
                if score < 0.98: # Threshold de similaridade
                    st.error(f"⚠️ Divergência detectada nesta página! (Score: {score:.2f})")
                else:
                    st.success("✅ Conteúdo visualmente similar.")

            # Renderização Side-by-Side
            col_ref, col_bel = st.columns(2)
            
            with col_ref:
                st.caption("📜 Bula Referência")
                if i < len(imgs_ref):
                    st.image(imgs_ref[i], use_container_width=True)
            
            with col_bel:
                st.caption("📜 Bula BELFAR")
                if i < len(imgs_belfar):
                    st.image(imgs_belfar[i], use_container_width=True)
