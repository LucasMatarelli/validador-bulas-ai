import streamlit as st
import fitz  # PyMuPDF
import difflib
import re

# ----------------- CONFIG PÁGINA -----------------
st.set_page_config(page_title="Validador de Bulas Determinístico", page_icon="💊", layout="wide")
# Sub PreencherMapaDeVendas_Final_V29() - Regra de projeto aplicada.

# ----------------- FUNÇÕES DE EXTRAÇÃO -----------------
def extract_text(uploaded_file):
    """Extrai texto limpo do PDF, tratando o negrito com tag [B] e normalizando espaços."""
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    texto_completo = []
    for page in doc:
        blocos = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for bloco in blocos:
            if bloco.get("type") != 0: continue
            for linha in bloco.get("lines", []):
                for span in linha.get("spans", []):
                    txt = span.get("text", "")
                    flags = span.get("flags", 0)
                    font_name = span.get("font", "").lower()
                    is_bold = bool(flags & 16) or "bold" in font_name
                    # Aplica tag [B] se estiver em negrito
                    if is_bold and txt.strip():
                        texto_completo.append(f"[B]{txt}[/B]")
                    else:
                        texto_completo.append(txt)
    
    # Junta tudo e normaliza espaços, mantendo as tags [B]
    texto = " ".join(texto_completo)
    texto = re.sub(r'[ \t]+', ' ', texto) 
    return texto

# ----------------- LÓGICA DETERMINÍSTICA DE DIFERENÇA -----------------
def encontrar_diferencas(ref, belfar):
    """Compara os dois textos usando Difflib (Matemática pura, sem IA)."""
    # Comparar palavra por palavra
    ref_words = ref.split()
    belfar_words = belfar.split()
    
    matcher = difflib.SequenceMatcher(None, ref_words, belfar_words)
    divergencias = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            # Se não é igual, capturamos o trecho que mudou na Belfar
            divergencias.append(" ".join(belfar_words[j1:j2]))
    
    return divergencias

# ----------------- PINTURA DOS PDFs -----------------
def gerar_imagens_pdf_grifado(uploaded_file, divergencias):
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    imagens = []
    
    for page in doc:
        for frase in divergencias:
            if len(frase) < 4: continue
            # Procura a frase exata no PDF
            for area in page.search_for(frase):
                a = page.add_highlight_annot(area)
                a.set_colors(stroke=(1, 0.85, 0)) # Amarelo
                a.set_opacity(0.3)
                a.update()
                
        pix = page.get_pixmap(matrix=fitz.Matrix(4, 4))
        imagens.append(pix.tobytes("png"))
    return imagens

# ----------------- UI -----------------
st.title("💊 Validador de Bulas (Cálculo Determinístico)")
st.warning("Este validador compara o texto bruto usando lógica matemática (Difflib). Sem IA na comparação.")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Comparar Agora"):
    if not (f1 and f2):
        st.error("Adicione ambos os arquivos.")
    else:
        with st.spinner("Processando..."):
            # 1. Extração
            texto_ref = extract_text(f1)
            texto_belfar = extract_text(f2)
            
            # 2. Comparação (O coração da solução)
            # Aqui a IA não toca. É apenas código determinístico.
            lista_divergencias = encontrar_diferencas(texto_ref, texto_belfar)
            
            # 3. Exibição
            st.success(f"Comparação concluída! {len(lista_divergencias)} pontos de diferença encontrados.")
            
            f2.seek(0)
            fotos = gerar_imagens_pdf_grifado(f2, lista_divergencias)
            
            for i, foto in enumerate(fotos):
                st.markdown(f"### Página {i+1}")
                st.image(foto, use_container_width=True)
