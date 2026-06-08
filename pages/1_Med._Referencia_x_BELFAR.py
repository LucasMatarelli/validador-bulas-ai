import streamlit as st
import fitz
import difflib
import re
import unicodedata

# ----------------- REGRA DE PROJETO OBRIGATÓRIA -----------------
def Sub_PreencherMapaDeVendas_Final_V29(texto):
    """Normaliza o texto mantendo a integridade para comparação."""
    return re.sub(r'[ \t\r\n]+', ' ', texto).lower().strip()

# ----------------- 1. CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Pro", layout="wide")

# ----------------- 2. EXTRAÇÃO POR BLOCOS (CORREÇÃO PRINCIPAL) -----------------
def normalizar(texto):
    """Normaliza texto: minúsculo, sem acentos, sem espaços duplos."""
    texto = texto.lower()
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'[ \t\r\n]+', ' ', texto).strip()
    return texto

def get_pdf_blocks(uploaded_file):
    """
    Extrai BLOCOS de texto (não palavras individuais) para comparação mais robusta.
    Retorna lista de {page, rect, text, norm} parando antes da data Anvisa.
    """
    file_bytes = uploaded_file.getvalue()
    doc = fitz.open("pdf", file_bytes)
    all_blocks = []
    stop_flag = False

    for page_idx, page in enumerate(doc):
        page_text = page.get_text().lower()
        if "esta bula foi aprovada pela anvisa em" in page_text:
            stop_flag = True

        # Extrai blocos de texto (agrupa por linha/span para evitar fragmentação de negrito)
        blocks = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for b in blocks:
            if b["type"] != 0:  # só texto
                continue
            for line in b["lines"]:
                # Agrupa todos os spans de uma linha em um único bloco
                line_text = ""
                line_rects = []
                for span in line["spans"]:
                    # Alguns spans não têm "text" (ex: spans de imagem inline)
                    raw = span.get("text", "") or ""
                    t = raw.strip()
                    if t and "bbox" in span:
                        line_text += (" " if line_text else "") + t
                        line_rects.append(fitz.Rect(span["bbox"]))

                line_text = line_text.strip()
                if not line_text:
                    continue

                # Rect que engloba todos os spans da linha
                if line_rects:
                    combined_rect = line_rects[0]
                    for r in line_rects[1:]:
                        combined_rect |= r

                    all_blocks.append({
                        "page": page_idx,
                        "rect": combined_rect,
                        "text": line_text,
                        "norm": normalizar(line_text)
                    })

        if stop_flag:
            break

    return all_blocks, doc

# ----------------- 3. COMPARAÇÃO E ANOTAÇÃO CORRIGIDA -----------------
def is_noise_block(text):
    """
    Retorna True se o bloco é provável cabeçalho/rodapé repetitivo ou ruído.
    Evita marcar falsamente numeração de página, etc.
    """
    t = text.strip().lower()
    if re.match(r'^p[aá]gina\s+\d+\s+(de|of)\s+\d+$', t):
        return True
    if re.match(r'^\d+$', t):
        return True
    return False

def process_and_mark(doc_ref, doc_bel, blocks_ref, blocks_bel):
    """
    Compara por blocos de linha inteira para evitar falsos positivos
    causados por fragmentação de texto negrito ou termos técnicos.
    """
    norm_ref = [b["norm"] for b in blocks_ref]
    norm_bel = [b["norm"] for b in blocks_bel]

    matcher = difflib.SequenceMatcher(None, norm_ref, norm_bel, autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            continue

        # Marca divergências na Referência
        if tag in ['delete', 'replace']:
            for i in range(i1, i2):
                b = blocks_ref[i]
                if is_noise_block(b["text"]):
                    continue
                page = doc_ref[b["page"]]
                # Usa add_rect_annot com preenchimento para highlight mais forte
                annot = page.add_highlight_annot(b["rect"])
                annot.set_colors(stroke=(1, 0.75, 0))   # amarelo saturado
                annot.set_opacity(0.65)
                annot.update()

        # Marca divergências na Belfar
        if tag in ['insert', 'replace']:
            for j in range(j1, j2):
                b = blocks_bel[j]
                if is_noise_block(b["text"]):
                    continue
                page = doc_bel[b["page"]]
                annot = page.add_highlight_annot(b["rect"])
                annot.set_colors(stroke=(1, 0.75, 0))   # amarelo saturado
                annot.set_opacity(0.65)
                annot.update()

def mark_anvisa(doc):
    """Pinta a data da Anvisa de azul."""
    pattern = r"esta bula foi aprovada pela anvisa em"
    for page in doc:
        for inst in page.search_for(pattern, flags=fitz.TEXT_PRESERVE_WHITESPACE):
            a = page.add_highlight_annot(inst)
            a.set_colors(stroke=(0, 0.5, 1))
            a.set_opacity(0.5)
            a.update()

# ----------------- 4. UI -----------------
st.title("💊 Comparador Visual de Bulas")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Comparar Bula Inteira"):
    if not (f1 and f2):
        st.warning("Envie os dois arquivos.")
    else:
        with st.spinner("Analisando divergências em ambas as bulas..."):
            blocks_ref, doc_ref = get_pdf_blocks(f1)
            blocks_bel, doc_bel = get_pdf_blocks(f2)

            process_and_mark(doc_ref, doc_bel, blocks_ref, blocks_bel)
            mark_anvisa(doc_ref)
            mark_anvisa(doc_bel)

            max_pag = max(len(doc_ref), len(doc_bel))
            for i in range(max_pag):
                st.divider()
                st.subheader(f"Página {i+1}")
                col_r, col_b = st.columns(2)

                with col_r:
                    if i < len(doc_ref):
                        st.image(
                            doc_ref[i].get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png"),
                            use_container_width=True
                        )
                with col_b:
                    if i < len(doc_bel):
                        st.image(
                            doc_bel[i].get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png"),
                            use_container_width=True
                        )
