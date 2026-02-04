# app.py (ajustado para resolver: cabeçalhos com tags, linhas numéricas soltas, e seções concatenadas)
import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import docx
import json
import difflib
import re
import unicodedata
import time
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from spellchecker import SpellChecker
from io import BytesIO

# ----------------- 1. VISUAL & CSS -----------------
st.set_page_config(page_title="Gráfica x Arte (versão robusta)", page_icon="💊", layout="wide")

st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    .texto-box { 
        font-family: 'Segoe UI', system-ui, -apple-system, "Helvetica Neue", Arial;
        font-size: 0.96rem;
        line-height: 1.6;
        color: #212529;
        background-color: #ffffff;
        padding: 22px;
        border-radius: 8px;
        border: 1px solid #e6e9ec;
        box-shadow: 0 6px 18px rgba(18, 40, 80, 0.03);
        text-align: left;
        min-height: 120px;
        overflow-wrap: anywhere;
    }
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 2px 6px; border-radius: 5px; border: 1px solid #ffeeba; font-weight: 700; }
    .highlight-red { background-color: #f8d7da; color: #721c24; border-bottom: 2px solid #dc3545; font-weight: 700; cursor: help; }
    .highlight-blue { background-color: #d1ecf1; color: #0c5460; padding: 2px 6px; border-radius: 5px; border: 1px solid #bee5eb; font-weight: 700; }
    .topico-item { display: block; margin-left: 20px; margin-bottom: 6px; text-indent: -15px; }
    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; } 
    .border-info { border-left: 6px solid #17a2b8 !important; }
    .titulo-secao { font-weight:700; letter-spacing: 0.2px; }
    div[data-testid="stMetric"] { background-color: #fbfdff; border: 1px solid #eef3fa; padding: 12px; border-radius: 8px; text-align: center; box-shadow: none; }
    section[data-testid="stSidebar"] { display: block !important; visibility: visible !important; width: 260px !important; min-width: 260px !important; max-width: 260px !important; margin-left: 0 !important; transform: translateX(0) !important; transition: none !important; position: relative !important; background-color: #f7f9fb !important; z-index: 999 !important; }
    .small-muted { color: #6c757d; font-size: 0.88rem; }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO (modelos ampliados) -----------------
MODELOS_PARA_TENTAR = [
    "models/gemini-2.5-flash", "gemini-2.5-flash",
    "models/gemini-2.5", "gemini-2.5",
    "models/gemini-3-flash", "gemini-3-flash",
    "models/gemini-1.5-flash", "gemini-1.5-flash",
    "models/gemini-1.5", "gemini-1.5",
    "models/gemma-3-27b", "gemma-3-27b",
    "models/gemma-3-12b", "gemma-3-12b",
    "models/gemma-3-4b", "gemma-3-4b",
    "models/text-bison-001", "text-bison-001", "chat-bison-001", "models/chat-bison-001"
]

SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO",
    "PARA QUE ESTE MEDICAMENTO É INDICADO", "COMO ESTE MEDICAMENTO FUNCIONA?",
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?", "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?", "COMO DEVO USAR ESTE MEDICAMENTO?",
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
    "DIZERES LEGAIS"
]

SECOES_PROFISSIONAL = SECOES_PACIENTE
SECOES_SEM_COMPARACAO = []
SIMILARITY_THRESHOLD = 0.92

# ----------------- 3. FUNÇÕES AUXILIARES (LIMPEZA, NORMALIZAÇÃO) -----------------

def strip_accents(s: str) -> str:
    return unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('ASCII')

def tokenize_words(s: str):
    return re.findall(r'\w+', s, flags=re.UNICODE)

def jaccard_similarity(a: str, b: str) -> float:
    sa = set(tokenize_words(a))
    sb = set(tokenize_words(b))
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    inter = sa.intersection(sb)
    union = sa.union(sb)
    return len(inter) / len(union)

def clean_metadata_and_footers(texto: str) -> str:
    if not texto:
        return texto
    t = texto

    # remover linhas que sejam apenas números ou números com ponto/parentese (ex: "1." "2)")
    lines = t.splitlines()
    filtered = []
    for ln in lines:
        if re.match(r'^\s*\d+\s*[\.\)]?\s*$', ln):
            continue
        filtered.append(ln)
    t = "\n".join(filtered)

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

    # remover linhas vazias extras e linhas com só símbolos
    lines = [ln.rstrip() for ln in t.splitlines()]
    lines = [ln for ln in lines if ln.strip() != "" and not re.match(r'^[\W_]{1,40}$', ln.strip())]
    t = "\n".join(lines)

    return t.strip()

def remove_section_titles_for_comparison(texto: str, sections_list=SECOES_PACIENTE) -> str:
    if not texto:
        return texto
    t = texto
    for s in sections_list:
        if not s or s.strip().upper() == "CABEÇALHO DA BULA":
            continue
        patt = r'\b' + r'\W+'.join(re.findall(r'\w+', s)) + r'\b'
        t = re.sub(patt, ' ', t, flags=re.IGNORECASE)
    t = re.sub(r'(?im)\bInform[aç]o(?:es)?\s+ao\s+paciente\b', ' ', t)
    t = re.sub(r'\s{2,}', ' ', t)
    return t.strip()

def normalize_for_comparison(text: str) -> str:
    if not text:
        return ""
    t = clean_metadata_and_footers(text)
    t = remove_section_titles_for_comparison(t)
    t = re.sub(r'(?m)^\s*\d+\s*[\.\)\-]\s*', '', t)
    t = re.sub(r'\b\d+\s*[\.\)]\s+', ' ', t)
    t = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', t)
    t = re.sub(r'<[^>]+>', '', t)
    t = strip_accents(t).lower()
    t = re.sub(r'[-–—]', ' ', t)
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

# ----------------- 4. VISUAL E ORTOGRAFIA -----------------

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
    padrao = r'(Esta\s+bula\s+foi\s+(?:atualizada\s+conforme\s+Bula\s+Padr\S*?\s+)?aprovada\s+pela\s+Anvisa\s+em\s*)(\d{2}/\d{2}/\d{4}|\d{2}/\d{4})'
    def replacer(match):
        return f'{match.group(1)}<span class="highlight-blue">{match.group(2)}</span>'
    return re.sub(padrao, replacer, texto, count=0, flags=re.IGNORECASE | re.DOTALL)

def verificar_ortografia_inteligente(texto):
    try:
        spell = SpellChecker(language='pt')
        whitelist = {'mg','ml','mcg','ui','g','kg','l','dl','mmhg','bpm','kcal','anvisa','cnpj','cep','sac','bula'}
        spell.word_frequency.load_words(whitelist)
        return texto
    except:
        return texto

# ----------------- 5. DIFF ROBUSTO (COM PROTEÇÃO DE TAGS) -----------------

def _protect_html_tags(s: str):
    if not s:
        return s, {}
    mapping = {}
    index = 0
    def repl(m):
        nonlocal index
        token = chr(0xE000 + index)
        mapping[token] = m.group(0)
        index += 1
        return token
    protected = re.sub(r'<[^>]+>', repl, s)
    return protected, mapping

def _restore_html_tags(s: str, mapping: dict):
    if not mapping:
        return s
    for token, tag in mapping.items():
        if token in s:
            s = s.replace(token, tag)
    return s

def diff_preserve_original(text_a: str, text_b: str):
    if text_a is None: text_a = ""
    if text_b is None: text_b = ""
    prot_a, map_a = _protect_html_tags(text_a)
    prot_b, map_b = _protect_html_tags(text_b)
    matcher = difflib.SequenceMatcher(None, prot_a, prot_b)
    parts_a = []
    parts_b = []
    tem = False
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            parts_a.append(prot_a[i1:i2])
            parts_b.append(prot_b[j1:j2])
        elif tag == 'replace':
            parts_a.append(f'<span class="highlight-yellow">{prot_a[i1:i2]}</span>')
            parts_b.append(f'<span class="highlight-yellow">{prot_b[j1:j2]}</span>')
            tem = True
        elif tag == 'delete':
            parts_a.append(f'<span class="highlight-yellow">{prot_a[i1:i2]}</span>')
            tem = True
        elif tag == 'insert':
            parts_b.append(f'<span class="highlight-yellow">{prot_b[j1:j2]}</span>')
            tem = True
    out_a = ''.join(parts_a)
    out_b = ''.join(parts_b)
    out_a = _restore_html_tags(out_a, map_a)
    out_a = _restore_html_tags(out_a, map_b)
    out_b = _restore_html_tags(out_b, map_b)
    out_b = _restore_html_tags(out_b, map_a)
    return out_a, out_b, tem

def diff_palavra_a_palavra(texto_ref, texto_novo):
    ref_sem_tags = re.sub(r'<[^>]+>', '', texto_ref)
    novo_sem_tags = re.sub(r'<[^>]+>', '', texto_novo)
    palavras_ref = ref_sem_tags.split()
    palavras_novo = novo_sem_tags.split()
    matcher = difflib.SequenceMatcher(None, palavras_ref, palavras_novo)
    html_ref_list = []
    html_novo_list = []
    tem_diff = False
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            texto = " ".join(palavras_ref[i1:i2])
            html_ref_list.append(texto)
            html_novo_list.append(texto)
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

def gerar_diff_html(texto_ref, texto_novo):
    if texto_ref is None: texto_ref = ""
    if texto_novo is None: texto_novo = ""
    display_ref = texto_ref.replace('\n', '<br>')
    display_novo = texto_novo.replace('\n', '<br>')
    norm_ref = normalize_for_comparison(texto_ref)
    norm_novo = normalize_for_comparison(texto_novo)
    comp_ref_nohy = re.sub(r'[-–—]', ' ', normalize_for_comparison(texto_ref))
    comp_novo_nohy = re.sub(r'[-–—]', ' ', normalize_for_comparison(texto_novo))
    if comp_ref_nohy == comp_novo_nohy:
        return melhorar_visual_topicos(display_ref), melhorar_visual_topicos(verificar_ortografia_inteligente(display_novo)), False
    if norm_ref == norm_novo:
        return melhorar_visual_topicos(display_ref), melhorar_visual_topicos(verificar_ortografia_inteligente(display_novo)), False
    if norm_ref and norm_novo:
        shorter, longer = (norm_ref, norm_novo) if len(norm_ref) <= len(norm_novo) else (norm_novo, norm_ref)
        if shorter and shorter in longer:
            prop = len(shorter) / max(1, len(longer))
            if prop >= 0.88:
                return melhorar_visual_topicos(display_ref), melhorar_visual_topicos(verificar_ortografia_inteligente(display_novo)), False
    ratio = difflib.SequenceMatcher(None, norm_ref, norm_novo).ratio()
    jacc = jaccard_similarity(norm_ref, norm_novo)
    if ratio >= SIMILARITY_THRESHOLD or jacc >= SIMILARITY_THRESHOLD:
        return melhorar_visual_topicos(display_ref), melhorar_visual_topicos(verificar_ortografia_inteligente(display_novo)), False
    html_ref, html_novo, diff_bool = diff_preserve_original(display_ref, display_novo)
    html_ref = melhorar_visual_topicos(html_ref)
    html_novo = melhorar_visual_topicos(html_novo)
    return html_ref, html_novo, diff_bool

# ----------------- 6. REMOVER RODAPÉS (SUAVE) -----------------

def remover_rodapes_bula(texto):
    if not texto:
        return texto
    t = texto
    padroes = [
        r'\b\d+ª\s*PROVA\b.*',
        r'Medida\s+do\s+bula.*',
        r'Tipologia\s+de\s+bula[:\-]?.*',
        r'Papel\s*[:\-]?.*',
        r'FRENTE.*Medida.*',
        r'conte[úu]do:.*atendimento@',
        r'www\.[^\s]+',
        r'[A-Z]{3,}\_\w{5,}',
    ]
    for p in padroes:
        t = re.sub(p, '', t, flags=re.IGNORECASE)
    linhas = t.splitlines()
    linhas_filtradas = []
    for ln in linhas:
        ln_s = ln.strip()
        if not ln_s:
            continue
        if re.match(r'^[\d\W_]{1,30}$', ln_s):
            continue
        if re.match(r'^\s*\d+\s*$', ln_s):
            continue
        linhas_filtradas.append(ln.rstrip())
    retorno = '\n'.join(linhas_filtradas)
    retorno = re.sub(r'\n{3,}', '\n\n', retorno)
    return retorno.strip()

# ----------------- 7. OCR VIA GEMINI -----------------
def ocr_via_gemini_bytes(bytes_data, api_keys):
    if not bytes_data:
        return "", "Arquivo vazio para OCR"
    prompt_ocr = """
    ATENÇÃO: Você é um robô de OCR ULTRA-PRECISO para documentos farmacêuticos brasileiros.
    IDIOMA: Português do Brasil.

    REGRAS ABSOLUTAS:
    1. COPIE caractere por caractere EXATAMENTE como está escrito no documento.
    2. NÃO invente, corrija, traduza ou resuma.
    3. Preserve formatação <b> e <i> caso exista.
    4. NÃO extraia rodapés técnicos (medidas, tipologia, código de arquivo).
    5. Extraia TODO o conteúdo principal da bula.
    """
    safety_settings = {
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    }
    log_erros_ocr = []
    for i, key in enumerate(api_keys):
        try:
            genai.configure(api_key=key)
            for modelo in MODELOS_PARA_TENTAR:
                try:
                    model = genai.GenerativeModel(modelo)
                    response = model.generate_content(
                        [{'mime_type': 'application/pdf', 'data': bytes_data}, prompt_ocr],
                        safety_settings=safety_settings
                    )
                    texto_extraido = getattr(response, "text", "") or ""
                    if texto_extraido.strip():
                        texto_extraido = remover_rodapes_bula(texto_extraido)
                        return texto_extraido, None
                except Exception as e_model:
                    err_msg = str(e_model)
                    log_erros_ocr.append(f"Key {i+1} | {modelo}: {err_msg}")
                    if "429" in err_msg or "quota" in err_msg.lower():
                        time.sleep(2)
                    continue
        except Exception as e_key:
            log_erros_ocr.append(f"Key {i+1} Falha Config: {str(e_key)}")
            continue
    return "", " | ".join(log_erros_ocr)

# ----------------- 8. EXTRAÇÃO INTELIGENTE (BYTES) -----------------
def extract_text_smart_from_bytes(bytes_data, filename, api_keys=None):
    try:
        raw_text = ""
        fname = filename.lower()
        if fname.endswith('.pdf'):
            doc = fitz.open(stream=bytes_data, filetype="pdf")
            for page in doc:
                blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
                for block in blocks:
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        line_text = ""
                        for span in line.get("spans", []):
                            content = span.get("text", "")
                            if not content:
                                continue
                            flags = span.get("flags", 0)
                            font_name = span.get("font", "").lower()
                            is_bold = ((flags & 16) or "bold" in font_name or "black" in font_name or "heavy" in font_name or "semibold" in font_name)
                            is_italic = ((flags & 2) or "italic" in font_name or "oblique" in font_name)
                            formatted_text = content
                            if is_bold and is_italic:
                                formatted_text = f"<b><i>{content}</i></b>"
                            elif is_bold:
                                formatted_text = f"<b>{content}</b>"
                            elif is_italic:
                                formatted_text = f"<i>{content}</i>"
                            line_text += formatted_text
                        raw_text += line_text + "\n"
                raw_text += "\n"
            doc.close()
        elif fname.endswith('.docx'):
            try:
                doc = docx.Document(BytesIO(bytes_data))
            except Exception:
                return "", "Erro ao abrir docx"
            for para in doc.paragraphs:
                para_text = ""
                for run in para.runs:
                    content = run.text
                    if not content:
                        continue
                    formatted_text = content
                    if run.bold and run.italic:
                        formatted_text = f"<b><i>{content}</i></b>"
                    elif run.bold:
                        formatted_text = f"<b>{content}</b>"
                    elif run.italic:
                        formatted_text = f"<i>{content}</i>"
                    para_text += formatted_text
                raw_text += para_text + "\n\n"
        else:
            return "", "Tipo de arquivo não suportado"

        texto_sem_tags = re.sub(r'<[^>]+>', '', raw_text).strip()
        texto_para_checar = remover_rodapes_bula(texto_sem_tags)

        alnum_count = len(re.findall(r'\w', texto_para_checar))
        if (fname.endswith('.pdf') and alnum_count < 60 and api_keys):
            st.warning(f"👁️ Arquivo '{filename}' com pouco texto detectado ({alnum_count} chars alfanuméricos). Ativando OCR...")
            texto_ocr, erro_ocr = ocr_via_gemini_bytes(bytes_data, api_keys)
            if texto_ocr:
                st.success(f"✅ OCR bem-sucedido para '{filename}'!")
                return texto_ocr
            else:
                st.error(f"❌ Falha no OCR de '{filename}'. Detalhes: {erro_ocr}")
                return raw_text

        return raw_text

    except Exception as e:
        st.error(f"Erro leitura: {str(e)}")
        return ""

# ----------------- 9. EXTRAÇÃO DETERMINÍSTICA DE SEÇÕES (robusta) -----------------
def _normalize_line_for_search(line: str) -> str:
    return re.sub(r'\s+', ' ', strip_accents(line).lower()).strip()

def extract_sections_by_headers(text, sections_list=SECOES_PACIENTE):
    """
    Busca os títulos baseado em versão 'plain' (sem tags) por linha e utiliza índices de linhas
    para extrair conteúdo preservando as tags originais.
    """
    if not text:
        return []

    # lines originais (com tags) e linhas "plain" (sem tags) para busca
    orig_lines = text.splitlines()
    plain_lines = [re.sub(r'<[^>]+>', '', ln) for ln in orig_lines]
    norm_lines = [_normalize_line_for_search(re.sub(r'^[^\w]+', '', ln)) for ln in plain_lines]

    found = []
    for s in sections_list:
        if not s:
            continue
        tokens = re.findall(r'\w+', s)
        if not tokens:
            continue
        # primeiro tente procura direta no texto plain completo (mais robusto)
        patt = r'\b' + r'\W+'.join(map(re.escape, tokens)) + r'\b'
        plain_text_all = "\n".join(plain_lines)
        m = re.search(patt, plain_text_all, flags=re.IGNORECASE)
        if m:
            # determinar em que linha isso ocorreu
            before = plain_text_all[:m.start()]
            line_idx = before.count("\n")
            start = None
            # map to orig_lines positions
            if line_idx < len(orig_lines):
                start = sum(len(l)+1 for l in orig_lines[:line_idx])
                end = start + len(orig_lines[line_idx])
                found.append((start, end, s, line_idx))
                continue

        # fallback: procurar por tokens nas linhas (mais tolerante a quebras)
        tokens_norm = [strip_accents(t).lower() for t in tokens]
        for idx, ln_norm in enumerate(norm_lines):
            pos = 0
            ok = True
            max_tokens = min(6, len(tokens_norm))  # tentar até 6 tokens - mais tolerante para títulos longos
            for tk in tokens_norm[:max_tokens]:
                p = ln_norm.find(tk, pos)
                if p == -1:
                    ok = False
                    break
                pos = p + len(tk)
            if ok:
                start_est = sum(len(l) + 1 for l in orig_lines[:idx])
                end_est = start_est + len(orig_lines[idx])
                found.append((start_est, end_est, s, idx))
                break

    if not found:
        return []

    # ordenar por posição
    found.sort(key=lambda x: x[0])
    secoes = []
    for idx, (start, end, titulo, line_idx) in enumerate(found):
        start_content = end
        end_content = found[idx+1][0] if idx+1 < len(found) else len(text)
        conteudo = text[start_content:end_content].strip()
        # limpar metadados/rodapés/linhas numéricas
        conteudo = clean_metadata_and_footers(conteudo)
        conteudo_lines = [ln for ln in conteudo.splitlines() if not re.match(r'^\s*\d+\s*[\.\)]?\s*$', ln)]
        conteudo = "\n".join(conteudo_lines).strip()
        secoes.append({"titulo": titulo, "texto": conteudo})
    return secoes

def align_sections_between_texts(text_ref, text_mkt, sections_list=SECOES_PACIENTE):
    secoes_ref = extract_sections_by_headers(text_ref, sections_list)
    secoes_mkt = extract_sections_by_headers(text_mkt, sections_list)
    mapa_ref = {s['titulo'].upper(): s['texto'] for s in secoes_ref}
    mapa_mkt = {s['titulo'].upper(): s['texto'] for s in secoes_mkt}
    final = []
    for titulo in sections_list:
        if not titulo:
            continue
        key = titulo.upper()
        txt_ref = mapa_ref.get(key, "")
        txt_mkt = mapa_mkt.get(key, "")
        # fallback adicional: se um lado possui e o outro não, tentar localizar título no outro com busca mais solta
        if (not txt_ref) and txt_mkt:
            # procurar campo no text_ref por tokens do título
            tokens = re.findall(r'\w+', titulo)
            if tokens:
                patt = r'\b' + r'\W+'.join(map(re.escape, tokens[:6])) + r'\b'
                plain_ref = re.sub(r'<[^>]+>', '', text_ref or "")
                m = re.search(patt, plain_ref, flags=re.IGNORECASE)
                if m:
                    # extrair conteúdo heurístico
                    start = m.end()
                    # procurar próximo título conhecido
                    next_pos = None
                    for s2 in sections_list:
                        if not s2:
                            continue
                        if s2.strip().upper() == titulo.strip().upper():
                            continue
                        p2 = r'\b' + r'\W+'.join(re.findall(r'\w+', s2)) + r'\b'
                        m2 = re.search(p2, plain_ref[start:], flags=re.IGNORECASE)
                        if m2:
                            pos2 = start + m2.start()
                            if next_pos is None or pos2 < next_pos:
                                next_pos = pos2
                    end = next_pos if next_pos is not None else len(plain_ref)
                    candidate = plain_ref[start:end].strip()
                    candidate = clean_metadata_and_footers(candidate)
                    if len(candidate) > 20:
                        txt_ref = candidate
        if (not txt_mkt) and txt_ref:
            tokens = re.findall(r'\w+', titulo)
            if tokens:
                patt = r'\b' + r'\W+'.join(map(re.escape, tokens[:6])) + r'\b'
                plain_mkt = re.sub(r'<[^>]+>', '', text_mkt or "")
                m = re.search(patt, plain_mkt, flags=re.IGNORECASE)
                if m:
                    start = m.end()
                    next_pos = None
                    for s2 in sections_list:
                        if not s2:
                            continue
                        if s2.strip().upper() == titulo.strip().upper():
                            continue
                        p2 = r'\b' + r'\W+'.join(re.findall(r'\w+', s2)) + r'\b'
                        m2 = re.search(p2, plain_mkt[start:], flags=re.IGNORECASE)
                        if m2:
                            pos2 = start + m2.start()
                            if next_pos is None or pos2 < next_pos:
                                next_pos = pos2
                    end = next_pos if next_pos is not None else len(plain_mkt)
                    candidate = plain_mkt[start:end].strip()
                    candidate = clean_metadata_and_footers(candidate)
                    if len(candidate) > 20:
                        txt_mkt = candidate
        if not txt_ref and not txt_mkt:
            continue
        final.append({"titulo": titulo, "texto_anvisa": txt_ref, "texto_mkt": txt_mkt})
    return final

# ----------------- sanitize title for display -----------------
def sanitize_title_for_display(titulo: str) -> str:
    if not titulo:
        return ""
    t = re.sub(r'^[\?\!\.\-\s]+', '', titulo).strip()
    t = re.sub(r'[\s\-\–\—]*\d{1,4}\s*$', '', t).strip()
    return t

# ----------------- 10. UI PRINCIPAL -----------------
st.title("💊 Gráfica x Arte (robusto)")
st.markdown("<div class='small-muted'>Comparação automática de seções com preservação de <b>negrito</b> e <i>itálico</i>.</div>", unsafe_allow_html=True)

tipo_bula = st.radio("Escolha o Tipo de Bula:", ("Paciente",), horizontal=True)
c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Gráfica", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("📜 Arte Vigente", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência"):
    secret_names = [
        "GEMINI_API_KEY", "GEMINI_API_KEY1", "GEMINI_API_KEY2", "GEMINI_API_KEY3",
        "GEMNI_API_KEY1", "GEMNI_API_KEY2", "GEMNI_API_KEY3"
    ]
    keys_raw = [st.secrets.get(n) for n in secret_names]
    keys_validas = [k for k in keys_raw if k]

    if not f1 or not f2:
        st.warning("Adicione os arquivos.")
        st.stop()
    try:
        f1_bytes = f1.read()
        f2_bytes = f2.read()
    except Exception as e:
        st.error(f"Erro ao ler arquivos do uploader: {e}")
        st.stop()

    with st.spinner("Analisando arquivos individualmente (Texto ou OCR)..."):
        t_anvisa = extract_text_smart_from_bytes(f1_bytes, f1.name, api_keys=keys_validas)
        t_mkt = extract_text_smart_from_bytes(f2_bytes, f2.name, api_keys=keys_validas)

        if not t_anvisa or len(re.findall(r'\w', re.sub(r'<[^>]+>', '', t_anvisa))) < 20:
            st.error(f"ERRO: Conteúdo do arquivo GRÁFICA insuficiente para análise."); st.stop()
        if not t_mkt or len(re.findall(r'\w', re.sub(r'<[^>]+>', '', t_mkt))) < 20:
            st.error(f"ERRO: Conteúdo do arquivo ARTE insuficiente para análise."); st.stop()

    secoes_alvo = SECOES_PACIENTE
    dados_secoes = align_sections_between_texts(t_anvisa, t_mkt, secoes_alvo)

    if not dados_secoes:
        st.info("Nenhuma seção padrão encontrada automaticamente. Extraindo conteúdo inteiro como fallback.")
        dados_secoes = [{"titulo": "CONTEÚDO INTEIRO", "texto_anvisa": t_anvisa, "texto_mkt": t_mkt}]

    secoes_finais = []
    divs_count = 0

    for item in dados_secoes:
        titulo_raw = (item.get('titulo') or '').strip()
        titulo = sanitize_title_for_display(titulo_raw)
        txt_ref = (item.get('texto_anvisa') or "").strip()
        txt_mkt = (item.get('texto_mkt') or "").strip()
        titulo_upper = titulo.upper()
        eh_blindada = any(b in titulo_upper for b in SECOES_SEM_COMPARACAO)

        if "CABEÇALHO" in titulo_upper:
            def safe_extract_header(raw_text, secoes_alvo):
                menor = None
                for s in secoes_alvo:
                    if s.strip().upper() == "CABEÇALHO DA BULA":
                        continue
                    patt = r'\b' + r'\W+'.join(re.findall(r'\w+', s)) + r'\b'
                    m = re.search(patt, raw_text, flags=re.IGNORECASE)
                    if m:
                        if menor is None or m.start() < menor:
                            menor = m.start()
                if menor is None:
                    m = re.search(r'\bAPRESENTA\S*\b', raw_text, flags=re.IGNORECASE)
                    menor = m.start() if m else None
                if menor is None:
                    return ""
                header_raw = raw_text[:menor].strip()
                header_raw = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', header_raw)
                header_clean = clean_metadata_and_footers(header_raw)
                if len(header_clean) < 20:
                    return ""
                if len(header_clean) > max(2000, int(len(raw_text)*0.35)):
                    return ""
                return header_clean
            if (not txt_ref or len(txt_ref) < 50):
                novo_ref = safe_extract_header(t_anvisa, secoes_alvo)
                if novo_ref:
                    txt_ref = novo_ref
            if (not txt_mkt or len(txt_mkt) < 50):
                novo_mkt = safe_extract_header(t_mkt, secoes_alvo)
                if novo_mkt:
                    txt_mkt = novo_mkt
            txt_ref = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', txt_ref)
            txt_mkt = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', txt_mkt)

        if eh_blindada:
            status = "CONFORME"
            if "DIZERES LEGAIS" in titulo_upper:
                html_ref = destacar_datas(txt_ref)
                html_mkt = destacar_datas(txt_mkt)
            else:
                html_ref = txt_ref
                html_mkt = txt_mkt
            html_ref = melhorar_visual_topicos(html_ref.replace('\n', '<br>'))
            html_mkt = melhorar_visual_topicos(html_mkt.replace('\n', '<br>'))
        else:
            html_ref, html_mkt, teve_diff = gerar_diff_html(txt_ref, txt_mkt)
            status = "DIVERGENTE" if teve_diff else "CONFORME"
            if teve_diff:
                divs_count += 1

        if not html_ref or re.sub(r'<[^>]+>', '', html_ref).strip() == "":
            html_ref = '<i>(Sem conteúdo extraído)</i>'
        if not html_mkt or re.sub(r'<[^>]+>', '', html_mkt).strip() == "":
            html_mkt = '<i>(Sem conteúdo extraído)</i>'

        secoes_finais.append({"titulo": titulo, "texto_anvisa": html_ref, "texto_mkt": html_mkt, "status": status})

    st.markdown("### 📊 Resumo")
    c1, c2, c3 = st.columns(3)
    c1.metric("Seções analisadas", len(secoes_finais))
    c2.metric("Divergências", divs_count)
    c3.metric("API Keys (OCR)", len(keys_validas))

    if divs_count > 0:
        st.warning(f"⚠️ Divergências encontradas em {divs_count} seção(ões).")
    else:
        st.success("✨ Divergências: 0")

    st.divider()

    for item in secoes_finais:
        status = item['status']
        titulo = item['titulo'] or "Sem título"
        if "DIZERES LEGAIS" in titulo.upper(): icon, css, aberto = "⚖️", "border-info", True
        elif any(b in titulo.upper() for b in SECOES_SEM_COMPARACAO): icon, css, aberto = "🔒", "border-ok", False
        elif status == "CONFORME": icon, css, aberto = "✅", "border-ok", False
        else: icon, css, aberto = "⚠️", "border-warn", True

        with st.expander(f"{icon} {titulo}", expanded=aberto):
            ce, cd = st.columns(2)
            with ce:
                st.caption("Gráfica")
                st.markdown(f'<div class="texto-box {css}">{item["texto_anvisa"]}</div>', unsafe_allow_html=True)
            with cd:
                st.caption("Arte")
                st.markdown(f'<div class="texto-box {css}">{item["texto_mkt"]}</div>', unsafe_allow_html=True)
