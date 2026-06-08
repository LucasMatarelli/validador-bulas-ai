import streamlit as st
import fitz
import difflib
import re
import unicodedata

# ----------------- CONFIGURAÇÃO -----------------
st.set_page_config(page_title="Validador de Bulas Pro", layout="wide")

# ----------------- NORMALIZAÇÃO -----------------
def normalizar(texto):
    texto = texto.lower()
    texto = unicodedata.normalize('NFD', texto)
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    texto = re.sub(r'\s+', ' ', texto).strip()
    # Remove pontuação isolada que causa ruído no diff
    texto = re.sub(r'[®©™°]', '', texto).strip()
    return texto

# ----------------- EXTRAÇÃO DE PALAVRAS (agrupando spans negrito) -----------------
def get_pdf_words(uploaded_file):
    """
    Extrai palavras do PDF agrupando spans da mesma linha antes de tokenizar.
    Isso evita que texto em negrito (múltiplos spans) seja tratado como tokens separados.
    Para na linha da aprovação Anvisa.
    """
    file_bytes = uploaded_file.getvalue()
    doc = fitz.open("pdf", file_bytes)
    all_words = []
    stop_flag = False

    for page_idx, page in enumerate(doc):
        page_text_lower = page.get_text().lower()
        if "esta bula foi aprovada pela anvisa em" in page_text_lower:
            stop_flag = True

        raw = page.get_text("rawdict", flags=0)
        for blk in raw.get("blocks", []):
            if blk.get("type", -1) != 0:
                continue
            for line in blk.get("lines", []):
                # 1) Monta o texto completo da linha juntando todos os spans
                line_parts = []
                span_rects = []
                for span in line.get("spans", []):
                    t = span.get("text", "") or ""
                    if t.strip() and "bbox" in span:
                        line_parts.append(t)
                        span_rects.append(fitz.Rect(span["bbox"]))

                if not line_parts:
                    continue

                # 2) Tokeniza a linha inteira em palavras
                line_text = " ".join(line_parts)
                # Calcula rect que engloba toda a linha para usar como fallback
                line_rect = span_rects[0]
                for r in span_rects[1:]:
                    line_rect |= r

                # 3) Divide em tokens (palavras) e estima rect por posição relativa
                tokens = re.findall(r'\S+', line_text)
                for tok in tokens:
                    tok_clean = normalizar(tok)
                    if not tok_clean:
                        continue
                    # Tenta localizar a palavra exata no PDF para rect preciso
                    hits = page.search_for(tok, clip=line_rect)
                    rect = hits[0] if hits else line_rect

                    all_words.append({
                        "page": page_idx,
                        "rect": rect,
                        "text": tok,
                        "norm": tok_clean
                    })

        if stop_flag:
            break

    return all_words, doc

# ----------------- COMPARAÇÃO E MARCAÇÃO -----------------
# Palavras que são iguais em ambas as bulas mas têm nomes diferentes
# (nomes de produto, fabricante) — NÃO filtrar, queremos marcar essas!
# O que filtramos é só ruído de extração.
NOISE_RE = re.compile(r'^[\d\.\,\;\:\-\/\(\)]+$')

def is_noise(norm_word):
    """Filtra tokens que são só pontuação/números isolados."""
    return bool(NOISE_RE.match(norm_word)) or len(norm_word) < 2

def process_and_mark(doc_ref, doc_bel, words_ref, words_bel):
    norm_ref = [w["norm"] for w in words_ref]
    norm_bel = [w["norm"] for w in words_bel]

    matcher = difflib.SequenceMatcher(None, norm_ref, norm_bel, autojunk=False)
    opcodes = matcher.get_opcodes()

    for tag, i1, i2, j1, j2 in opcodes:
        if tag == 'equal':
            continue

        if tag in ('delete', 'replace'):
            for i in range(i1, i2):
                w = words_ref[i]
                if is_noise(w["norm"]):
                    continue
                page = doc_ref[w["page"]]
                a = page.add_highlight_annot(w["rect"])
                a.set_colors(stroke=(1, 0.7, 0))
                a.set_opacity(0.7)
                a.update()

        if tag in ('insert', 'replace'):
            for j in range(j1, j2):
                w = words_bel[j]
                if is_noise(w["norm"]):
                    continue
                page = doc_bel[w["page"]]
                a = page.add_highlight_annot(w["rect"])
                a.set_colors(stroke=(1, 0.7, 0))
                a.set_opacity(0.7)
                a.update()

def mark_anvisa(doc):
    pattern = "esta bula foi aprovada pela anvisa em"
    for page in doc:
        hits = page.search_for(pattern)
        for inst in hits:
            a = page.add_highlight_annot(inst)
            a.set_colors(stroke=(0, 0.5, 1))
            a.set_opacity(0.5)
            a.update()

# ----------------- UI -----------------
st.title("💊 Comparador Visual de Bulas")

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Bula Referência", type=["pdf"])
f2 = c2.file_uploader("📜 Bula BELFAR", type=["pdf"])

if st.button("🚀 Comparar Bula Inteira"):
    if not (f1 and f2):
        st.warning("Envie os dois arquivos.")
    else:
        with st.spinner("Analisando divergências..."):
            words_ref, doc_ref = get_pdf_words(f1)
            words_bel, doc_bel = get_pdf_words(f2)

            process_and_mark(doc_ref, doc_bel, words_ref, words_bel)
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
