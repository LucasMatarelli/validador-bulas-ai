import streamlit as st
import fitz  # PyMuPDF
import difflib
import re

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Normaliza o texto, mas PRESERVA as tags de negrito para comparação."""
    # Primeiro, transformamos as tags em algo seguro para não serem afetadas pelo lowercase
    texto = texto.replace("[B]", "@@BOLD_START@@").replace("[/B]", "@@BOLD_END@@")
    texto = texto.lower()
    # Remove espaços extras
    texto = re.sub(r'[ \t\r\n]+', ' ', texto)
    # Devolve as tags
    texto = texto.replace("@@bold_start@@", "[B]").replace("@@bold_end@@", "[/B]")
    return texto.strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Pro", layout="wide")

# ----------------- 2. EXTRAÇÃO E COMPARAÇÃO -----------------
def extract_text_with_bold(uploaded_file):
    """Extrai texto preservando negrito como tag [B]...[/B]."""
    doc = fitz.open("pdf", uploaded_file.getvalue())
    full_text = ""
    for page in doc:
        # Extração preservando formatação
        blocks = page.get_text("dict")["blocks"]
        for b in blocks:
            if "lines" in b:
                for l in b["lines"]:
                    for s in l["spans"]:
                        text = s["text"]
                        # Check bold: bit 4 of flags is bold
                        if s["flags"] & 2**4 or "bold" in s["font"].lower():
                            full_text += f"[B]{text}[/B]"
                        else:
                            full_text += text
    return full_text

def get_divergences(ref_text, bel_text):
    """Compara texto mantendo as tags [B] na string."""
    # Aplica Sub obrigatória (que agora preserva tags)
    ref_norm = Sub_PreencherMapaDeVendas_Final_V29(ref_text)
    bel_norm = Sub_PreencherMapaDeVendas_Final_V29(bel_text)
    
    # Compara por palavras (que agora incluem [B] como parte da palavra)
    ref_words = ref_norm.split()
    bel_words = bel_norm.split()
    
    matcher = difflib.SequenceMatcher(None, ref_words, bel_words)
    divergentes = []
    
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != 'equal':
            # Captura o trecho da Belfar que diverge
            trecho = " ".join(bel_words[j1:j2])
            # Remove tags para a busca visual no PDF, pois o search_for não lê [B]
            clean_trecho = trecho.replace("[B]", "").replace("[/B]", "")
            if len(clean_trecho.strip()) > 3:
                divergentes.append(clean_trecho.strip())
    return list(set(divergentes))

# ----------------- 3. ANOTAÇÃO -----------------
def annotate_doc(uploaded_file, divergencias):
    doc = fitz.open("pdf", uploaded_file.getvalue())
    for page in doc:
        # Anvisa (Azul)
        for inst in page.search_for("esta bula foi aprovada pela anvisa em"):
            a = page.add_highlight_annot(inst)
            a.set_colors(stroke=(0, 0.5, 1)); a.set_opacity(0.3); a.update()
        # Divergências (Amarelo)
        for div in divergencias:
            for inst in page.search_for(div):
                a = page.add_highlight_annot(inst)
                a.set_colors(stroke=(1, 0.85, 0)); a.set_opacity(0.4); a.update()
    return doc

# ----------------- 4. UI -----------------
st.title("💊 Validador de Bulas (Estrito)")
c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Iniciar Auditoria"):
    if f1 and f2:
        t_ref = extract_text_with_bold(f1)
        t_bel = extract_text_with_bold(f2)
        divs = get_divergences(t_ref, t_bel)
        
        f1.seek(0); f2.seek(0)
        doc_ref = annotate_doc(f1, [])
        doc_bel = annotate_doc(f2, divs)
        
        max_pag = max(len(doc_ref), len(doc_bel))
        for i in range(max_pag):
            col_r, col_b = st.columns(2)
            with col_r:
                if i < len(doc_ref): st.image(doc_ref.load_page(i).get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"))
            with col_b:
                if i < len(doc_bel): st.image(doc_bel.load_page(i).get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png"))
