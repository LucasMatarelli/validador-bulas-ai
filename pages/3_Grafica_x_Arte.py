# app.py - Gráfica x Arte (Versão Gemini 2.5/3.0 - OCR Integrado)
# - Atualizado para extrair data APENAS em "DIZERES LEGAIS" com frase exata.
# - Interface renomeada para Gráfica x Arte Vigente.
# - OCR automático se texto local < 1000 chars.
# - Modelos restritos: 2.5 Flash, 2.5 Flash Lite, 3 Flash.
# - CABEÇALHO removido.
# - Corrigido problema de negrito (**palavra** → <b>palavra</b>).

import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import docx
import json
import difflib
import re
import unicodedata
import time
from spellchecker import SpellChecker
from io import BytesIO

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Gráfica x Arte", page_icon="💊", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }

    .texto-box { 
        font-family: 'Segoe UI', sans-serif;
        font-size: 0.95rem;
        line-height: 1.7;
        color: #212529;
        background-color: #ffffff;
        padding: 25px;
        border-radius: 8px;
        border: 1px solid #ced4da;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        text-align: left;
    }

    .highlight-yellow { 
        background-color: #fff3cd; color: #856404; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; 
        font-weight: bold;
    }

    .highlight-blue { 
        background-color: #d1ecf1; color: #0c5460; 
        padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; 
    }

    .topico-item {
        display: block;
        margin-left: 20px;
        margin-bottom: 4px;
        text-indent: -15px; 
    }

    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; } 
    .border-info { border-left: 6px solid #17a2b8 !important; }

    div[data-testid="stMetric"] {
        background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; text-align: center;
    }

    section[data-testid="stSidebar"] {
        display: block !important;
        visibility: visible !important;
        width: 250px !important;
        min-width: 250px !important;
        max-width: 250px !important;
        margin-left: 0 !important;
        transform: translateX(0) !important;
        transition: none !important;
        position: relative !important;
        background-color: #f0f2f6 !important;
        z-index: 999 !important;
    }

    section[data-testid="stSidebar"] > div:first-child {
        width: 250px !important;
        min-width: 250px !important;
    }

    button[kind="header"],
    [data-testid="collapsedControl"],
    button[data-testid="baseButton-header"] {
        display: none !important;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO -----------------
# Lista restrita conforme solicitado
MODELOS_PARA_TENTAR = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3-flash"
]

SECOES_PACIENTE = [
    "APRESENTAÇÕES",
    "COMPOSIÇÃO",
    "PARA QUE ESTE MEDICAMENTO É INDICADO?",
    "COMO ESTE MEDICAMENTO FUNCIONA?",
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
    "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
    "COMO DEVO USAR ESTE MEDICAMENTO?",
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
    "O QUE FAZER SE ALGUÉM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
    "DIZERES LEGAIS"
]

SIMILARITY_THRESHOLD = 0.92

# ----------------- 3. LIMPEZA AUTOMATIZADA (METADADOS E RODAPÉS) -----------------
def clean_metadata_and_footers(texto: str) -> str:
    if not texto:
        return texto
    t = texto

    t = re.sub(r'(?im)^.*times\s+new\s+roman.*\n?', '', t)
    t = re.sub(r'(?im)^.*negrito.*\n?', '', t)
    t = re.sub(r'(?im)^.*corpo\s*14.*\n?', '', t)
    t = re.sub(r'(?im)^.*\bcontato\b.*\n?', '', t)
    t = re.sub(r'(?i)[\w\.-]+@belfar\.com\.br', '', t)
    t = re.sub(r'(?m)(?:\+?\d{1,3}[-\s]?)?(?:\(?\d{2}\)?[-\s]?)?\d{4,5}[-\s]?\d{4}', '', t)

    t = re.sub(r'(?m)^\s*[A-Z0-9_]{8,}\s*$', '', t)

    patterns_line = [
        r'(?im)^\s*.*medida\s+da\s+bula.*$',
        r'(?im)^\s*.*tipologia\s+da\s+bula.*$',
        r'(?im)^\s*.*tipologia:.*$',
        r'(?im)^\s*.*impress(ã|a)o.*:.*$',
        r'(?im)^\s*.*papel:.*$',
        r'(?im)^\s*.*cor:.*$',
        r'(?im)^\s*.*frente\/verso.*$',
    ]
    for p in patterns_line:
        t = re.sub(p, '', t)

    t = re.sub(r'(?im)\d{1,2},\d{2}\s*cm\s*[x×X]\s*\d{1,2},\d{2}\s*cm', '', t)
    page_patterns = [
        r'(?im)\bBula(?:\s+ao\s+Paciente)?\s+P[aá]gina\s*\d+\s*(?:de|\/)\s*\d+\b',
        r'(?im)\bBula(?:\s+ao\s+Paciente)?\s+P[aá]gina\s*\d+\b',
        r'(?im)\bP[aá]gina\s*\d+\s*(?:de|\/)\s*\d+\b',
        r'(?im)\bP[aá]gina\s*\d+\b'
    ]
    for p in page_patterns:
        t = re.sub(p, '', t)

    t = re.sub(r'(?im)\bfrente\b', '', t)
    t = re.sub(r'(?im)\bverso\b', '', t)
    t = re.sub(r'(?im)\bBUL[_A-Z0-9-]*\b', '', t)

    t = re.sub(r'-\s*\n\s*', '', t)

    t = re.sub(r'[ \t]{2,}', ' ', t)
    t = re.sub(r'\r', '\n', t)
    t = re.sub(r'\n{3,}', '\n\n', t)

    lines = [ln.rstrip() for ln in t.splitlines()]
    lines = [ln for ln in lines if ln.strip() != ""]
    t = "\n".join(lines)

    return t.strip()

# ----------------- 4. LOCALIZAÇÃO DE TÍTULOS E EXTRAÇÃO -----------------
def build_section_pattern(title: str) -> str:
    words = re.findall(r'\w+', title, flags=re.UNICODE)
    if not words:
        return None
    pattern = r'\b' + r'\W+'.join(map(re.escape, words)) + r'\b'
    return pattern

def find_first_section_index(texto: str, section_titles: list) -> int:
    menor = None
    for title in section_titles:
        if not title: continue
        patt = build_section_pattern(title)
        if not patt: continue
        m = re.search(patt, texto, flags=re.IGNORECASE | re.UNICODE)
        if m:
            idx = m.start()
            if menor is None or idx < menor:
                menor = idx
    return -1 if menor is None else menor

def _build_flexible_title_regex(title: str):
    words = re.findall(r'\w+', title, flags=re.UNICODE)
    if not words: return None
    core = r'\W+'.join(map(re.escape, words))
    regex = rf'(?:^|\n)\s*(?:\d{{1,2}}\s*[\.\)\-]\s*|[IVXLCDM]+\s*[–-]\s*)?{core}'
    return regex

def extract_section_from_raw(texto: str, section_title: str, sections_list: list) -> str:
    if not texto or not section_title: return ""
    patt = _build_flexible_title_regex(section_title)
    if patt:
        m = re.search(patt, texto, flags=re.IGNORECASE | re.UNICODE)
    else:
        m = re.search(build_section_pattern(section_title), texto, flags=re.IGNORECASE | re.UNICODE)
    if not m:
        keywords = re.findall(r'\w+', section_title)
        if keywords:
            for kcount in (min(3, len(keywords)), len(keywords)):
                core = r'\W+'.join(map(re.escape, keywords[:kcount]))
                m = re.search(core, texto, flags=re.IGNORECASE | re.UNICODE)
                if m: break
    if not m: return ""
    start = m.end()
    menor = None
    for s in sections_list:
        if not s: continue
        if s.strip().upper() == section_title.strip().upper(): continue
        p2 = _build_flexible_title_regex(s)
        if not p2: p2 = build_section_pattern(s)
        m2 = re.search(p2, texto[start:], flags=re.IGNORECASE | re.UNICODE)
        if m2:
            idx = start + m2.start()
            if menor is None or idx < menor: menor = idx
    if menor is None:
        m3 = re.search(r'\n{2,}([A-ZÀ-Ý0-9 \-]{6,})\n', texto[start:])
        if m3:
            candidate = m3.group(1).strip()
            if len(candidate.split()) <= 6: menor = start + m3.start()
    end = menor if menor is not None else len(texto)
    section_raw = texto[start:end].strip()
    section_raw = re.sub(r'(?m)^\s*\d+\s*[\.\)\-]?\s*', '', section_raw)
    section_raw = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', section_raw)
    section_clean = re.sub(r'\r', '\n', section_raw).strip()
    if len(re.sub(r'<[^>]+>', '', section_clean).strip()) < 10: return ""
    if len(re.sub(r'<[^>]+>', '', section_clean)) > max(8000, int(len(texto) * 0.8)): return ""
    return section_clean

# ----------------- 5. NORMALIZAÇÃO PARA COMPARAÇÃO -----------------
def strip_accents(s: str) -> str:
    return unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('ASCII')

def tokenize_words(s: str):
    return re.findall(r'\w+', s, flags=re.UNICODE)

def remove_section_titles_for_comparison(texto: str, sections_list=SECOES_PACIENTE) -> str:
    if not texto: return texto
    t = texto
    for s in sections_list:
        if not s: continue
        patt = build_section_pattern(s)
        if patt: t = re.sub(patt, ' ', t, flags=re.IGNORECASE)
    t = re.sub(r'(?im)\bInform[aç]o(?:es)?\s+ao\s+paciente\b', ' ', t)
    t = re.sub(r'\s{2,}', ' ', t)
    return t.strip()

def normalize_for_comparison(text: str) -> str:
    if not text: return ""
    t = clean_metadata_and_footers(text)
    t = remove_section_titles_for_comparison(t)
    t = re.sub(r'(?m)^\s*\d+\s*[\.\)\-]\s*', '', t)
    t = re.sub(r'\b\d+\s*[\.\)]\s+', ' ', t)
    t = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', t)
    t = re.sub(r'<[^>]+>', '', t)
    t = re.sub(r'[-–—]', ' ', t)
    t = strip_accents(t).lower()
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def jaccard_similarity(a: str, b: str) -> float:
    sa = set(tokenize_words(a))
    sb = set(tokenize_words(b))
    if not sa and not sb: return 1.0
    if not sa or not sb: return 0.0
    inter = sa.intersection(sb); union = sa.union(sb)
    return len(inter) / len(union)

# ----------------- 6. CONVERSÃO DE MARKDOWN PARA HTML -----------------
def converter_markdown_para_html(texto: str) -> str:
    """
    Converte markdown (** para negrito, * para itálico) em tags HTML.
    """
    if not texto:
        return texto
    
    # Converter **texto** para <b>texto</b>
    texto = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', texto)
    
    # Converter *texto* para <i>texto</i> (apenas asterisco simples que não foi capturado acima)
    texto = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', texto)
    
    return texto

# ----------------- 7. ORTOGRAFIA E VISUAL -----------------
def verificar_ortografia_inteligente(texto):
    try:
        # Primeiro converter markdown para HTML
        texto = converter_markdown_para_html(texto)
        
        spell = SpellChecker(language='pt')
        whitelist = {'mg','ml','mcg','ui','g','kg','l','dl','mmhg','bpm','kcal','anvisa','cnpj','cep','sac','bula'}
        spell.word_frequency.load_words(whitelist)
        tokens = re.split(r'(<[^>]+>|\s+|[().,:;!?/\[\]])', texto)
        resultado = []
        for token in tokens:
            if not token.strip() or token.startswith('<') or not any(c.isalpha() for c in token):
                resultado.append(token); continue
            palavra_limpa = re.sub(r'[^a-zA-ZáàâãéèêíïóôõöúçñÁÀÂÃÉÈÊÍÏÓÔÕÖÚÇÑ-]', '', token)
            if (not palavra_limpa or len(palavra_limpa) < 4 or any(c.isdigit() for c in token) or '-' in palavra_limpa or palavra_limpa[0].isupper()):
                resultado.append(token); continue
            resultado.append(token)
        return "".join(resultado)
    except: 
        return converter_markdown_para_html(texto)

def melhorar_visual_topicos(texto_html):
    linhas = re.split(r'(<br>|\n)', texto_html)
    novo_texto = []
    for linha in linhas:
        if re.search(r'^\s*[-•*]\s+', re.sub(r'<[^>]+>', '', linha).strip()):
            linha_limpa = re.sub(r'^\s*[-•*]\s+', '', linha)
            novo_texto.append(f'<div class="topico-item">• {linha_limpa}</div>')
        else:
            novo_texto.append(linha)
    return "".join(novo_texto)

def destacar_datas(texto):
    padrao = r'(Esta\s+bula\s+foi\s+(?:atualizada\s+conforme\s+Bula\s+Padr[oã]o\s+)?aprovada\s+pela\s+Anvisa\s+em\s*)(\d{2}/\d{2}/\d{4}|\d{2}/\d{4})'
    def replacer(match):
        return f'{match.group(1)}<span class="highlight-blue">{match.group(2)}</span>'
    return re.sub(padrao, replacer, texto, count=0, flags=re.IGNORECASE | re.DOTALL)

# ----------------- 8. DIFF E REGRAS DE DECISÃO -----------------
def diff_palavra_a_palavra(texto_ref, texto_novo):
    ref_sem_tags = re.sub(r'<[^>]+>', '', texto_ref)
    novo_sem_tags = re.sub(r'<[^>]+>', '', texto_novo)
    ref_sem_tags = re.sub(r'[-–—]', ' ', ref_sem_tags)
    novo_sem_tags = re.sub(r'[-–—]', ' ', novo_sem_tags)
    palavras_ref = ref_sem_tags.split()
    palavras_novo = novo_sem_tags.split()
    matcher = difflib.SequenceMatcher(None, palavras_ref, palavras_novo)
    html_ref_list = []
    html_novo_list = []
    tem_diff = False
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            texto = " ".join(palavras_ref[i1:i2]); html_ref_list.append(texto); html_novo_list.append(texto)
        elif tag == 'replace':
            html_ref_list.append(f'<span class="highlight-yellow">{" ".join(palavras_ref[i1:i2])}</span>')
            html_novo_list.append(f'<span class="highlight-yellow">{" ".join(palavras_novo[j1:j2])}</span>')
            tem_diff = True
        elif tag == 'delete':
            html_ref_list.append(f'<span class="highlight-yellow">{" ".join(palavras_ref[i1:i2])}</span>')
            tem_diff = True
        elif tag == 'insert':
            html_novo_list.append(f'<span class="highlight-yellow">{" ".join(palavras_novo[j1:j2])}</span>')
            tem_diff = True
    return " ".join(html_ref_list), " ".join(html_novo_list), tem_diff

def gerar_diff_html(texto_ref, texto_novo, secoes_alvo=SECOES_PACIENTE):
    if not texto_ref: texto_ref = ""
    if not texto_novo: texto_novo = ""

    comp_ref = clean_metadata_and_footers(texto_ref)
    comp_novo = clean_metadata_and_footers(texto_novo)

    comp_ref_nohy = re.sub(r'[-–—]', ' ', comp_ref)
    comp_novo_nohy = re.sub(r'[-–—]', ' ', comp_novo)
    norm_ref_nohy = normalize_for_comparison(comp_ref_nohy)
    norm_novo_nohy = normalize_for_comparison(comp_novo_nohy)

    if norm_ref_nohy == norm_novo_nohy:
        html_ref = comp_ref.replace('\n', '<br>'); html_ref = melhorar_visual_topicos(html_ref)
        html_novo = verificar_ortografia_inteligente(comp_novo); html_novo = html_novo.replace('\n', '<br>'); html_novo = melhorar_visual_topicos(html_novo)
        return html_ref, html_novo, False

    comp_ref_norm = clean_metadata_and_footers(comp_ref)
    comp_novo_norm = clean_metadata_and_footers(comp_novo)
    norm_ref = normalize_for_comparison(comp_ref_norm)
    norm_novo = normalize_for_comparison(comp_novo_norm)

    if norm_ref == norm_novo:
        html_ref = comp_ref.replace('\n', '<br>'); html_ref = melhorar_visual_topicos(html_ref)
        html_novo = verificar_ortografia_inteligente(comp_novo); html_novo = html_novo.replace('\n', '<br>'); html_novo = melhorar_visual_topicos(html_novo)
        return html_ref, html_novo, False

    if norm_ref and norm_novo:
        shorter, longer = (norm_ref, norm_novo) if len(norm_ref) <= len(norm_novo) else (norm_novo, norm_ref)
        if shorter and shorter in longer:
            prop = len(shorter) / max(1, len(longer))
            if prop >= 0.88:
                html_ref = comp_ref.replace('\n', '<br>'); html_ref = melhorar_visual_topicos(html_ref)
                html_novo = verificar_ortografia_inteligente(comp_novo); html_novo = html_novo.replace('\n', '<br>'); html_novo = melhorar_visual_topicos(html_novo)
                return html_ref, html_novo, False

    ratio = difflib.SequenceMatcher(None, norm_ref, norm_novo).ratio()
    jacc = jaccard_similarity(norm_ref, norm_novo)
    if ratio >= SIMILARITY_THRESHOLD or jacc >= SIMILARITY_THRESHOLD:
        html_ref = comp_ref.replace('\n', '<br>'); html_ref = melhorar_visual_topicos(html_ref)
        html_novo = verificar_ortografia_inteligente(comp_novo); html_novo = html_novo.replace('\n', '<br>'); html_novo = melhorar_visual_topicos(html_novo)
        return html_ref, html_novo, False

    r_html, n_html, diff_bool = diff_palavra_a_palavra(comp_ref, comp_novo)
    n_html_final = verificar_ortografia_inteligente(n_html); n_html_final = melhorar_visual_topicos(n_html_final)
    r_html_final = melhorar_visual_topicos(r_html.replace('\n', '<br>'))
    return r_html_final, n_html_final, diff_bool

# ----------------- 9. EXTRAÇÃO DE TEXTO LOCAL -----------------
def extract_text_from_file(uploaded_file):
    try:
        text = ""
        name = getattr(uploaded_file, "name", "uploaded")
        if name.lower().endswith('.pdf'):
            uploaded_file.seek(0)
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            for page in doc:
                blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
                for block in blocks:
                    if block.get("type") != 0: continue
                    block_text = ""
                    for line in block.get("lines", []):
                        line_text = ""
                        for span in line.get("spans", []):
                            content = span.get("text", "")
                            if not content.strip(): line_text += content; continue
                            flags = span.get("flags", 0)
                            font_name = span.get("font", "").lower()
                            is_bold = ((flags & 16) or "bold" in font_name or "black" in font_name or "heavy" in font_name or "semibold" in font_name)
                            is_italic = ((flags & 2) or "italic" in font_name or "oblique" in font_name)
                            formatted_text = content
                            if is_bold and is_italic: formatted_text = f"<b><i>{content}</i></b>"
                            elif is_bold: formatted_text = f"<b>{content}</b>"
                            elif is_italic: formatted_text = f"<i>{content}</i>"
                            line_text += formatted_text
                        block_text += line_text.strip() + " "
                    text += block_text.strip() + "\n\n"
            doc.close()
        elif name.lower().endswith('.docx'):
            try:
                uploaded_file.seek(0)
                doc = docx.Document(uploaded_file)
            except Exception:
                uploaded_file.seek(0)
                doc = docx.Document(BytesIO(uploaded_file.read()))
            for para in doc.paragraphs:
                para_text = ""
                for run in para.runs:
                    content = run.text
                    if not content: continue
                    is_bold = run.bold is True
                    is_italic = run.italic is True
                    formatted_text = content
                    if is_bold and is_italic: formatted_text = f"<b><i>{content}</i></b>"
                    elif is_bold: formatted_text = f"<b>{content}</b>"
                    elif is_italic: formatted_text = f"<i>{content}</i>"
                    para_text += formatted_text
                text += para_text + "\n\n"
        return clean_metadata_and_footers(text.strip())
    except Exception as e:
        st.error(f"Erro ao extrair texto do arquivo {getattr(uploaded_file, 'name', '')}: {str(e)}")
        return ""

# ----------------- 10. FUNÇÃO OCR (GEMINI) -----------------
def ocr_via_gemini(uploaded_file, keys_validas):
    """
    Função para realizar OCR usando Gemini 2.5 Flash quando o texto extraído localmente é insuficiente.
    """
    uploaded_file.seek(0)
    bytes_data = uploaded_file.read()
    
    # MIME type detection basic
    mime_type = "application/pdf"
    if getattr(uploaded_file, "name", "").lower().endswith(".docx"):
        return "" 
    
    prompt_ocr = """EXTRAIA TODO O TEXTO DESTE ARQUIVO.
    Mantenha formatação <b> e <i> onde apropriado.
    Não adicione comentários, apenas devolva o texto extraído."""
    
    for key in keys_validas:
        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        try:
            response = model.generate_content([
                {'mime_type': mime_type, 'data': bytes_data},
                prompt_ocr
            ])
            return clean_metadata_and_footers(response.text)
        except Exception:
            continue
    return ""

# ----------------- 11. UI PRINCIPAL E FLUXO -----------------
st.title("💊 Gráfica x Arte")

tipo_bula = st.radio("Escolha o Tipo de Bula:", ("Paciente",), horizontal=True)

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Gráfica", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("📜 Arte Vigente", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência", key="process_button"):
    st.info("Iniciando processamento...")
    if not f1 or not f2:
        st.warning("Por favor, envie ambos os arquivos antes de processar.")
        st.stop()
    
    # Identificar chaves
    secret_names = [
        "GEMINI_API_KEY", "GEMINI_API_KEY1", "GEMINI_API_KEY2", "GEMINI_API_KEY3",
        "GEMNI_API_KEY1", "GEMNI_API_KEY2", "GEMNI_API_KEY3"
    ]
    keys_raw = [st.secrets.get(n) for n in secret_names]
    keys_validas = [k for k in keys_raw if k]

    if not keys_validas:
        st.error("Erro crítico: nenhuma API key encontrada nos secrets.")
        st.stop()

    if f1 and f2:
        secoes_alvo = SECOES_PACIENTE

        with st.spinner("Lendo arquivos e analisando conteúdo..."):
            try:
                # 1. Extração Local
                f1.seek(0); f2.seek(0)
                t_anvisa = extract_text_from_file(f1)
                t_mkt = extract_text_from_file(f2)
                
                # 2. Verificação de OCR (Se < 1000 chars)
                if len(t_anvisa) < 1000:
                    st.info(f"Gráfica: Texto local insuficiente ({len(t_anvisa)} chars). Acionando OCR via IA...")
                    ocr_res = ocr_via_gemini(f1, keys_validas)
                    if len(ocr_res) > len(t_anvisa):
                        t_anvisa = ocr_res
                        st.success("OCR Gráfica realizado com sucesso.")
                    else:
                        st.warning("OCR Gráfica não retornou mais texto que a extração local.")

                if len(t_mkt) < 1000:
                    st.info(f"Arte Vigente: Texto local insuficiente ({len(t_mkt)} chars). Acionando OCR via IA...")
                    ocr_res2 = ocr_via_gemini(f2, keys_validas)
                    if len(ocr_res2) > len(t_mkt):
                        t_mkt = ocr_res2
                        st.success("OCR Arte Vigente realizado com sucesso.")
                    else:
                        st.warning("OCR Arte Vigente não retornou mais texto que a extração local.")

                st.info(f"Tamanho final Gráfica: {len(t_anvisa)} caracteres")
                st.info(f"Tamanho final Arte Vigente: {len(t_mkt)} caracteres")

            except Exception as e:
                st.exception(f"Falha ao processar arquivos: {e}")
                st.stop()

            if len(t_anvisa) < 20 or len(t_mkt) < 20:
                st.error("Conteúdo insuficiente para análise (Arquivo vazio ou ilegível)."); st.stop()

            # Prompt para Análise Comparativa
            prompt = f"""
            Você é um Extrator de Dados Farmacêuticos Rigoroso.

            INPUT TEXTO 1 (GRÁFICA): {t_anvisa[:150000]}
            INPUT TEXTO 2 (ARTE VIGENTE): {t_mkt[:150000]}

            REGRAS CRÍTICAS DE EXTRAÇÃO:

    **SEÇÕES**: A partir de "APRESENTAÇÕES" até "DIZERES LEGAIS", extrair cada seção completa.

    **FORMATAÇÃO**: 
    Manter <b> e <i> EXATAMENTE como está
    NÃO corrigir português
    NÃO resumir
    Ignorar linhas horizontais/elementos gráficos

    Se uma seção não existir, NÃO inclua no JSON.

    LISTA DE SEÇÕES ESPERADAS: {secoes_alvo}

    SAÍDA JSON:
    {{
     "data_anvisa_ref": "dd/mm/aaaa",
     "data_anvisa_mkt": "dd/mm/aaaa",
     "secoes": [
         {{
             "titulo": "NOME EXATO DA SEÇÃO",
             "texto_anvisa": "conteúdo completo da Gráfica",
             "texto_mkt": "conteúdo completo da Arte Vigente"
         }}
     ]
    }}
    """

            response = None
            sucesso = False
            log_erros = []

            # Variáveis para armazenar datas extraídas APENAS de "DIZERES LEGAIS"
            extracted_date_ref = "-"
            extracted_date_mkt = "-"

            # Loop de Tentativas (Modelos + Keys)
            for idx_key, key in enumerate(keys_validas):
                if sucesso: break
                try:
                    genai.configure(api_key=key)
                except Exception as e:
                    log_erros.append(f"Key {idx_key+1} config error: {str(e)}")
                    continue

                for modelo in MODELOS_PARA_TENTAR:
                    try:
                        st.info(f"Analisando com modelo: {modelo} (Key {idx_key+1})...")
                        model = genai.GenerativeModel(
                            modelo,
                            generation_config={"response_mime_type": "application/json", "temperature": 0.0}
                        )
                        response = model.generate_content(prompt)
                        sucesso = True
                        break
                    except Exception as e:
                        log_erros.append(f"Key {idx_key+1} | {modelo}: {str(e)}")
                        time.sleep(1)
                        continue

            if not sucesso:
                st.error("❌ Falha total ao chamar a API Gemini. Verifique logs abaixo.")
                if log_erros:
                    st.code("\n".join(log_erros))
                st.stop()

            # Processamento da Resposta
            try:
                resp_text = getattr(response, "text", None) or str(response)

                def extract_json_block_local(text: str):
                    if not text or '{' not in text: return None
                    start = text.find('{'); depth = 0; in_string = False; esc = False
                    for i in range(start, len(text)):
                        ch = text[i]
                        if ch == '"' and not esc: in_string = not in_string
                        if in_string: esc = (ch == '\\' and not esc); continue
                        if ch == '{': depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0: return text[start:i+1]
                    return None

                try:
                    resultado = json.loads(resp_text)
                except Exception:
                    bloco = extract_json_block_local(resp_text)
                    if bloco: resultado = json.loads(bloco)
                    else: st.error("JSON inválido na resposta da IA."); st.stop()

            except Exception as e:
                st.exception(f"Erro ao decodificar resposta: {e}")
                st.stop()

            try:
                dados_secoes = resultado.get("secoes", [])
                secoes_finais = []
                divs_count = 0
                frase_padrao = r'Esta\s+bula\s+foi\s+atualizada\s+conforme\s+Bula\s+Padr[oã]o\s+aprovada\s+pela\s+Anvisa\s+em\s*(\d{2}/\d{2}/\d{4}|\d{2}/\d{4})'

                for item in dados_secoes:
                    titulo = item.get('titulo', '').strip()
                    txt_ref = item.get('texto_anvisa', '').strip()
                    txt_mkt = item.get('texto_mkt', '').strip()

                    # Fallback extração local se a IA falhar em trazer o texto
                    if not txt_ref:
                        tentativa = extract_section_from_raw(t_anvisa, titulo, secoes_alvo)
                        if tentativa: txt_ref = tentativa
                    if not txt_mkt:
                        tentativa2 = extract_section_from_raw(t_mkt, titulo, secoes_alvo)
                        if tentativa2: txt_mkt = tentativa2

                    txt_ref = clean_metadata_and_footers(txt_ref)
                    txt_mkt = clean_metadata_and_footers(txt_mkt)

                    if "DIZERES LEGAIS" in titulo.upper():
                        m_ref = re.search(frase_padrao, txt_ref, flags=re.IGNORECASE)
                        if m_ref: extracted_date_ref = m_ref.group(1)
                        m_mkt = re.search(frase_padrao, txt_mkt, flags=re.IGNORECASE)
                        if m_mkt: extracted_date_mkt = m_mkt.group(1)

                        html_ref = destacar_datas(txt_ref).replace('\n', '<br>')
                        html_novo = destacar_datas(txt_mkt).replace('\n', '<br>')
                        html_ref = verificar_ortografia_inteligente(html_ref)
                        html_novo = verificar_ortografia_inteligente(html_novo)
                        html_ref = melhorar_visual_topicos(html_ref)
                        html_novo = melhorar_visual_topicos(html_novo)
                        status = "CONFORME"
                    else:
                        html_ref, html_novo, teve_diff = gerar_diff_html(txt_ref, txt_mkt, secoes_alvo)
                        status = "DIVERGENTE" if teve_diff else "CONFORME"
                        if teve_diff: divs_count += 1

                    secoes_finais.append({
                        "titulo": titulo,
                        "texto_anvisa": html_ref,
                        "texto_mkt": html_novo,
                        "status": status
                    })

                data_ref = extracted_date_ref if extracted_date_ref != "-" else "-"
                data_mkt = extracted_date_mkt if extracted_date_mkt != "-" else "-"

                st.markdown("### 📊 Resumo")
                c1, c2, c3 = st.columns(3)
                c1.metric("Data Gráfica", data_ref)
                c2.metric("Data Arte Vigente", data_mkt, delta="Igual" if data_ref == data_mkt and data_ref != "-" else "Diferente")
                c3.metric("Seções", len(secoes_finais))

                sub1, sub2 = st.columns(2)
                sub1.info(f"✅ Conformes: {len(secoes_finais) - divs_count}")
                if divs_count > 0:
                    sub2.warning(f"⚠️ Divergentes: {divs_count}")
                else:
                    sub2.success("✨ Divergências: 0")

                st.divider()

                for item in secoes_finais:
                    status = item['status']
                    titulo = item['titulo']
                    if "DIZERES LEGAIS" in titulo.upper():
                        icon, css, aberto = "⚖️", "border-info", False
                    elif status == "CONFORME":
                        icon, css, aberto = "✅", "border-ok", False
                    else:
                        icon, css, aberto = "⚠️", "border-warn", True

                    with st.expander(f"{icon} {titulo}", expanded=aberto):
                        ce, cd = st.columns(2)
                        with ce:
                            st.caption("Gráfica")
                            st.markdown(f'<div class="texto-box {css}">{item["texto_anvisa"]}</div>', unsafe_allow_html=True)
                        with cd:
                            st.caption("Arte Vigente")
                            st.markdown(f'<div class="texto-box {css}">{item["texto_mkt"]}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.exception(f"Erro ao processar resultado final: {e}")
                st.stop()

else:
    st.info("Aguardando arquivos.")
