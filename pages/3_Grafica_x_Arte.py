# app.py (OCR melhorado e extração refinada; sidebar forçada aberta)
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

# ----------------- Config UI -----------------
st.set_page_config(page_title="Gráfica x Arte (robusto)", page_icon="💊", layout="wide")
st.markdown("""
<style>
    section[data-testid="stSidebar"] {
        display: block !important;
        visibility: visible !important;
        width: 260px !important;
        min-width: 260px !important;
        max-width: 260px !important;
        margin-left: 0 !important;
        transform: translateX(0) !important;
        transition: none !important;
        position: relative !important;
        background-color: #f7f9fb !important;
        z-index: 999 !important;
    }
    section[data-testid="stSidebar"] > div:first-child { width: 260px !important; min-width: 260px !important; }
    button[kind="header"], [data-testid="collapsedControl"], button[data-testid="baseButton-header"] { display: none !important; }

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
    .highlight-blue { background-color: #d1ecf1; color: #0c5460; padding: 2px 6px; border-radius: 5px; border: 1px solid #bee5eb; font-weight: 700; }
    .topico-item { display: block; margin-left: 20px; margin-bottom: 6px; text-indent: -15px; }
    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; }
    .border-info { border-left: 6px solid #17a2b8 !important; }
    .small-muted { color: #6c757d; font-size: 0.88rem; }
</style>
""", unsafe_allow_html=True)

# ----------------- Models & Sections -----------------
MODELOS_PARA_TENTAR = [
    "models/gemini-2.5-flash", "gemini-2.5-flash",
    "models/gemini-2.5", "gemini-2.5",
    "models/gemini-3-flash", "gemini-3-flash",
    "models/gemma-3-27b", "gemma-3-27b",
    "models/gemma-3-12b", "gemma-3-12b",
    "models/gemma-3-4b", "gemma-3-4b",
    "models/text-bison-001", "text-bison-001"
]

SECOES_PACIENTE = [
    "APRESENTAÇÕES", "COMPOSIÇÃO",
    "PARA QUE ESTE MEDICAMENTO É INDICADO?",
    "COMO ESTE MEDICAMENTO FUNCIONA?",
    "QUANDO NÃO DEVO USAR ESTE MEDICAMENTO?",
    "O QUE DEVO SABER ANTES DE USAR ESTE MEDICAMENTO?",
    "ONDE, COMO E POR QUANTO TEMPO POSSO GUARDAR ESTE MEDICAMENTO?",
    "COMO DEVO USAR ESTE MEDICAMENTO?",
    "O QUE DEVO FAZER QUANDO EU ME ESQUECER DE USAR ESTE MEDICAMENTO?",
    "O QUE FAZER SE ALGUEM USAR UMA QUANTIDADE MAIOR DO QUE A INDICADA DESTE MEDICAMENTO?",
    "QUAIS OS MALES QUE ESTE MEDICAMENTO PODE CAUSAR?",
    "DIZERES LEGAIS"
]

SIMILARITY_THRESHOLD = 0.92

# ----------------- Util functions -----------------
def strip_accents(s: str) -> str:
    return unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('ASCII')

def tokenize_words(s: str):
    return re.findall(r'\w+', s, flags=re.UNICODE)

def jaccard_similarity(a: str, b: str) -> float:
    sa = set(tokenize_words(a)); sb = set(tokenize_words(b))
    if not sa and not sb: return 1.0
    if not sa or not sb: return 0.0
    inter = sa.intersection(sb); union = sa.union(sb)
    return len(inter) / len(union)

# ----------------- Cleaning helpers -----------------
def clean_metadata_and_footers(texto: str) -> str:
    if not texto:
        return texto
    t = texto
    # remove lines that are only numbers (pagination remnants)
    lines = t.splitlines()
    filtered = []
    for ln in lines:
        if re.match(r'^\s*\d+\s*[\.\)]?\s*$', ln):
            continue
        filtered.append(ln)
    t = "\n".join(filtered)
    # common metadata patterns
    t = re.sub(r'(?m)^\s*[A-Z0-9_]{8,}\s*$', '', t)
    patterns_line = [
        r'(?im)^\s*.*medida\s+da\s+bula.*$',
        r'(?im)^\s*.*tipologia\s+da\s+bula.*$',
        r'(?im)^\s*.*tipologia:.*$',
        r'(?im)^\s*.*impress(ã|a)o.*:.*$',
        r'(?im)^\s*.*papel:.*$',
        r'(?im)^\s*.*cor:.*$',
        r'(?im)^\s*.*frente\/verso.*$'
    ]
    for p in patterns_line: t = re.sub(p, '', t)
    t = re.sub(r'(?im)\d{1,2},\d{2}\s*cm\s*[x×X]\s*\d{1,2},\d{2}\s*cm', '', t)
    page_patterns = [
        r'(?im)\bBula(?:\s+ao\s+Paciente)?\s+P[aá]gina\s*\d+\s*(?:de|\/)\s*\d+\b',
        r'(?im)\bBula(?:\s+ao\s+Paciente)?\s+P[aá]gina\s*\d+\b',
        r'(?im)\bP[aá]gina\s*\d+\s*(?:de|\/)\s*\d+\b',
        r'(?im)\bP[aá]gina\s*\d+\b'
    ]
    for p in page_patterns: t = re.sub(p, '', t)
    t = re.sub(r'(?im)\bfrente\b', '', t); t = re.sub(r'(?im)\bverso\b', '', t)
    t = re.sub(r'(?im)\bBUL[_A-Z0-9-]*\b', '', t)
    t = re.sub(r'-\s*\n\s*', '', t)
    t = re.sub(r'[ \t]{2,}', ' ', t)
    t = re.sub(r'\r', '\n', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    lines = [ln.rstrip() for ln in t.splitlines()]
    lines = [ln for ln in lines if ln.strip() != "" and not re.match(r'^[\W_]{1,40}$', ln.strip())]
    t = "\n".join(lines)
    return t.strip()

def remover_rodapes_bula(texto: str) -> str:
    if not texto:
        return texto
    t = texto
    patterns = [
        r'\b\d+ª\s*PROVA\b.*',
        r'Medida\s+do\s+bula.*',
        r'Tipologia\s+de\s+bula[:\-]?.*',
        r'Papel\s*[:\-]?.*',
        r'FRENTE.*Medida.*',
        r'conte[úu]do:.*atendimento@',
        r'www\.[^\s]+',
        r'[A-Z]{3,}\_\w{5,}'
    ]
    for p in patterns:
        t = re.sub(p, '', t, flags=re.IGNORECASE)
    lines = t.splitlines()
    out = []
    for ln in lines:
        ln_s = ln.strip()
        if not ln_s: continue
        if re.match(r'^[\d\W_]{1,30}$', ln_s): continue
        if re.match(r'^\s*\d+\s*$', ln_s): continue
        out.append(ln.rstrip())
    retorno = '\n'.join(out)
    retorno = re.sub(r'\n{3,}', '\n\n', retorno)
    return retorno.strip()

# ----------------- OCR via Gemini (improved) -----------------
def ocr_via_gemini_bytes(bytes_data, api_keys):
    """
    Calls the generative model to perform OCR on a PDF byte stream.
    Returns extracted text (preferably with <b>/<i> preserved) or error message.
    """
    if not bytes_data:
        return "", "Arquivo vazio para OCR"

    # Stronger OCR prompt. Be explicit: only return the raw extracted text (no JSON, no commentary).
    prompt_ocr = """EXTRAIA APENAS O TEXTO DO PDF ABAIXO.
Preserve as tags HTML <b> e <i> exatamente onde o texto está em negrito/itálico.
NÃO inclua explicações, títulos adicionais ou JSON.
NÃO adicione cabeçalhos como "OCR result".
Remova rodapés técnicos (medidas, tipologia, códigos) e mantenha o conteúdo do paciente.
FORMATO: devolva apenas o texto puro (com <b> e <i> quando aplicável) e quebras de linha.

PDF em anexo:"""

    safety_settings = {
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE
    }

    log_err = []
    for i, key in enumerate(api_keys):
        try:
            genai.configure(api_key=key)
        except Exception as e:
            log_err.append(f"Key {i+1} configure error: {e}")
            continue

        for modelo in MODELOS_PARA_TENTAR:
            try:
                model = genai.GenerativeModel(modelo)
                # call - passing file bytes and prompt; response expected in .text
                response = model.generate_content(
                    [{'mime_type': 'application/pdf', 'data': bytes_data}, prompt_ocr],
                    safety_settings=safety_settings,
                    generation_config={"response_mime_type": "text/plain", "temperature": 0.0}
                )
                texto_extraido = getattr(response, "text", "") or ""
                if not texto_extraido.strip():
                    continue

                # Clean typical model prefixes/footers that some models add
                # Remove common leading phrases the model might append
                texto_extraido = re.sub(r'^\s*(OCR\s*Result:|Texto extraído:|Resultado:)\s*', '', texto_extraido, flags=re.IGNORECASE)
                # If model put triple backticks or code fence, strip them
                texto_extraido = re.sub(r'^```(?:[\w\-]+)?\s*', '', texto_extraido)
                texto_extraido = re.sub(r'\s*```$', '', texto_extraido)

                # Remove trailing disclaimers that some models add
                texto_extraido = re.sub(r'\n?--+\n?.*$', '', texto_extraido.strip(), flags=re.DOTALL)

                # Normalize newlines
                texto_extraido = texto_extraido.replace('\r\n', '\n').replace('\r', '\n')

                # Post-process: remove odd repeated whitespace and ensure html tags intact
                # Remove any accidental spaces inside tags
                texto_extraido = re.sub(r'<\s+b\s*>', '<b>', texto_extraido, flags=re.IGNORECASE)
                texto_extraido = re.sub(r'<\s*/\s*b\s*>', '</b>', texto_extraido, flags=re.IGNORECASE)
                texto_extraido = re.sub(r'<\s+i\s*>', '<i>', texto_extraido, flags=re.IGNORECASE)
                texto_extraido = re.sub(r'<\s*/\s*i\s*>', '</i>', texto_extraido, flags=re.IGNORECASE)

                # Remove obvious footer lines
                texto_extraido = remover_rodapes_bula(texto_extraido)
                texto_extraido = clean_metadata_and_footers(texto_extraido)

                # If still empty after cleaning, continue searching
                if not re.sub(r'<[^>]+>', '', texto_extraido).strip():
                    continue

                return texto_extraido, None

            except Exception as e_model:
                err_msg = str(e_model)
                log_err.append(f"Key {i+1} | {modelo}: {err_msg}")
                # if rate-limited, small backoff
                if "429" in err_msg or "quota" in err_msg.lower():
                    time.sleep(2)
                continue

    return "", " | ".join(log_err)

# ----------------- Smart extraction from bytes (preserve bold/italic when possible) -----------------
def extract_text_smart_from_bytes(bytes_data, filename, api_keys=None):
    """
    1) Try to extract with PyMuPDF preserving styling (bold/italic -> <b>/<i>).
    2) If extracted plain text is too small, call OCR via Gemini.
    3) Return cleaned text (with <b>/<i> when possible).
    """
    try:
        raw_text = ""
        fname = filename.lower()
        if fname.endswith('.pdf'):
            doc = fitz.open(stream=bytes_data, filetype="pdf")
            total_text_chars = 0
            for page in doc:
                blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get("blocks", [])
                page_text_spans = ""
                for block in blocks:
                    if block.get("type") != 0:
                        continue
                    for line in block.get("lines", []):
                        line_text = ""
                        for span in line.get("spans", []):
                            content = span.get("text", "")
                            if content is None:
                                continue
                            flags = span.get("flags", 0)
                            font_name = span.get("font", "").lower()
                            is_bold = ((flags & 16) or "bold" in font_name or "black" in font_name or "heavy" in font_name or "semibold" in font_name)
                            is_italic = ((flags & 2) or "italic" in font_name or "oblique" in font_name)
                            formatted = content
                            if is_bold and is_italic:
                                formatted = f"<b><i>{content}</i></b>"
                            elif is_bold:
                                formatted = f"<b>{content}</b>"
                            elif is_italic:
                                formatted = f"<i>{content}</i>"
                            line_text += formatted
                        # Keep line breaks
                        page_text_spans += line_text + "\n"
                # If page_text_spans is empty or only whitespace, fallback to page.get_text("text")
                if page_text_spans.strip():
                    raw_text += page_text_spans + "\n"
                    total_text_chars += len(re.sub(r'<[^>]+>', '', page_text_spans))
                else:
                    try:
                        fallback = page.get_text("text") or ""
                        raw_text += fallback + "\n"
                        total_text_chars += len(fallback)
                    except Exception:
                        # ignore
                        pass
            doc.close()
            # if very little extracted, call OCR
            if total_text_chars < 60 and api_keys:
                st.info(f"Arquivo '{filename}' com pouco texto detectado ({total_text_chars} chars). Usando OCR remoto...")
                texto_ocr, err = ocr_via_gemini_bytes(bytes_data, api_keys)
                if texto_ocr:
                    return texto_ocr
                else:
                    st.warning(f"OCR remoto falhou: {err}. Retornando texto local (pode estar incompleto).")
                    return clean_metadata_and_footers(raw_text)
            return clean_metadata_and_footers(raw_text)

        elif fname.endswith('.docx'):
            try:
                doc = docx.Document(BytesIO(bytes_data))
            except Exception:
                return "", "Erro ao abrir docx"
            raw = ""
            for para in doc.paragraphs:
                para_text = ""
                for run in para.runs:
                    content = run.text
                    if not content:
                        continue
                    formatted = content
                    if run.bold and run.italic:
                        formatted = f"<b><i>{content}</i></b>"
                    elif run.bold:
                        formatted = f"<b>{content}</b>"
                    elif run.italic:
                        formatted = f"<i>{content}</i>"
                    para_text += formatted
                raw += para_text + "\n\n"
            return clean_metadata_and_footers(raw)

        else:
            return "", "Tipo de arquivo não suportado"

    except Exception as e:
        st.error(f"Erro leitura: {e}")
        return ""

# ----------------- Section extraction & diff (kept concise) -----------------
def _normalize_line_for_search(line: str) -> str:
    ln = re.sub(r'^\s*\d+\s*[\.\)\-]?\s*', '', line)
    ln = re.sub(r'^[^\w]+', '', ln)
    return re.sub(r'\s+', ' ', strip_accents(ln).lower()).strip()

def extract_sections_by_headers(text, sections_list=SECOES_PACIENTE):
    if not text:
        return []
    orig_lines = text.splitlines()
    plain_lines = [re.sub(r'<[^>]+>', '', ln) for ln in orig_lines]
    norm_lines = [_normalize_line_for_search(ln) for ln in plain_lines]
    found = []
    plain_text_all = "\n".join(plain_lines)
    for s in sections_list:
        if not s: continue
        tokens = re.findall(r'\w+', s)
        if not tokens: continue
        patt = r'\b' + r'\W+'.join(map(re.escape, tokens)) + r'\b'
        m = re.search(patt, plain_text_all, flags=re.IGNORECASE)
        if m:
            before = plain_text_all[:m.start()]
            line_idx = before.count("\n")
            start = sum(len(l)+1 for l in orig_lines[:line_idx]) if line_idx < len(orig_lines) else m.start()
            end = start + (len(orig_lines[line_idx]) if line_idx < len(orig_lines) else 0)
            found.append((start, end, s, line_idx))
            continue
        tokens_norm = [strip_accents(t).lower() for t in tokens]
        for idx, ln_norm in enumerate(norm_lines):
            pos = 0; ok = True
            max_tokens = min(8, len(tokens_norm))
            for tk in tokens_norm[:max_tokens]:
                p = ln_norm.find(tk, pos)
                if p == -1:
                    ok = False; break
                pos = p + len(tk)
            if ok:
                start_est = sum(len(l)+1 for l in orig_lines[:idx])
                end_est = start_est + len(orig_lines[idx])
                found.append((start_est, end_est, s, idx))
                break
    if not found: return []
    found.sort(key=lambda x: x[0])
    secoes = []
    for idx, (start, end, titulo, line_idx) in enumerate(found):
        start_content = end
        end_content = found[idx+1][0] if idx+1 < len(found) else len(text)
        conteudo = text[start_content:end_content].strip()
        conteudo = clean_metadata_and_footers(conteudo)
        conteudo_lines = [re.sub(r'^\s*\d+\s*[\.\)\-]?\s*', '', ln) for ln in conteudo.splitlines()]
        conteudo_lines = [ln for ln in conteudo_lines if not re.match(r'^\s*\d+\s*[\.\)]?\s*$', ln)]
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
        if not titulo: continue
        key = titulo.upper()
        txt_ref = mapa_ref.get(key, "")
        txt_mkt = mapa_mkt.get(key, "")
        # fallback heuristics (try to find title in the other doc)
        if (not txt_ref) and txt_mkt:
            tokens = re.findall(r'\w+', titulo)
            if tokens:
                patt = r'\b' + r'\W+'.join(map(re.escape, tokens[:8])) + r'\b'
                plain_ref = re.sub(r'<[^>]+>', '', text_ref or "")
                m = re.search(patt, plain_ref, flags=re.IGNORECASE)
                if m:
                    start = m.end()
                    next_pos = None
                    for s2 in sections_list:
                        if not s2: continue
                        if s2.strip().upper() == titulo.strip().upper(): continue
                        p2 = r'\b' + r'\W+'.join(re.findall(r'\w+', s2)) + r'\b'
                        m2 = re.search(p2, plain_ref[start:], flags=re.IGNORECASE)
                        if m2:
                            pos2 = start + m2.start()
                            if next_pos is None or pos2 < next_pos:
                                next_pos = pos2
                    end = next_pos if next_pos is not None else len(plain_ref)
                    candidate = plain_ref[start:end].strip()
                    candidate = clean_metadata_and_footers(candidate)
                    if len(candidate) > 20: txt_ref = candidate
        if (not txt_mkt) and txt_ref:
            tokens = re.findall(r'\w+', titulo)
            if tokens:
                patt = r'\b' + r'\W+'.join(map(re.escape, tokens[:8])) + r'\b'
                plain_mkt = re.sub(r'<[^>]+>', '', text_mkt or "")
                m = re.search(patt, plain_mkt, flags=re.IGNORECASE)
                if m:
                    start = m.end()
                    next_pos = None
                    for s2 in sections_list:
                        if not s2: continue
                        if s2.strip().upper() == titulo.strip().upper(): continue
                        p2 = r'\b' + r'\W+'.join(re.findall(r'\w+', s2)) + r'\b'
                        m2 = re.search(p2, plain_mkt[start:], flags=re.IGNORECASE)
                        if m2:
                            pos2 = start + m2.start()
                            if next_pos is None or pos2 < next_pos:
                                next_pos = pos2
                    end = next_pos if next_pos is not None else len(plain_mkt)
                    candidate = plain_mkt[start:end].strip()
                    candidate = clean_metadata_and_footers(candidate)
                    if len(candidate) > 20: txt_mkt = candidate
        if not txt_ref and not txt_mkt:
            continue
        final.append({"titulo": titulo, "texto_anvisa": txt_ref, "texto_mkt": txt_mkt})
    return final

# ----------------- Diff helpers and gerar_diff_html -----------------
def _protect_html_tags(s: str):
    if not s: return s, {}
    mapping = {}; index = 0
    def repl(m):
        nonlocal index
        token = chr(0xE000 + index)
        mapping[token] = m.group(0)
        index += 1
        return token
    protected = re.sub(r'<[^>]+>', repl, s)
    return protected, mapping

def _restore_html_tags(s: str, mapping: dict):
    if not mapping: return s
    for token, tag in mapping.items():
        if token in s: s = s.replace(token, tag)
    return s

def diff_preserve_original(a: str, b: str):
    a = a or ""; b = b or ""
    pa, ma = _protect_html_tags(a); pb, mb = _protect_html_tags(b)
    matcher = difflib.SequenceMatcher(None, pa, pb)
    parts_a = []; parts_b = []; tem = False
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            parts_a.append(pa[i1:i2]); parts_b.append(pb[j1:j2])
        elif tag == 'replace':
            parts_a.append(f'<span class="highlight-yellow">{pa[i1:i2]}</span>')
            parts_b.append(f'<span class="highlight-yellow">{pb[j1:j2]}</span>')
            tem = True
        elif tag == 'delete':
            parts_a.append(f'<span class="highlight-yellow">{pa[i1:i2]}</span>'); tem = True
        elif tag == 'insert':
            parts_b.append(f'<span class="highlight-yellow">{pb[j1:j2]}</span>'); tem = True
    out_a = ''.join(parts_a); out_b = ''.join(parts_b)
    out_a = _restore_html_tags(out_a, ma); out_a = _restore_html_tags(out_a, mb)
    out_b = _restore_html_tags(out_b, mb); out_b = _restore_html_tags(out_b, ma)
    return out_a, out_b, tem

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

def verificar_ortografia_inteligente(texto):
    try:
        spell = SpellChecker(language='pt')
        whitelist = {'mg','ml','mcg','ui','g','kg','l','dl','mmhg','bpm','kcal','anvisa','cnpj','cep','sac','bula'}
        spell.word_frequency.load_words(whitelist)
        return texto
    except:
        return texto

def gerar_diff_html(texto_ref, texto_novo):
    if texto_ref is None: texto_ref = ""
    if texto_novo is None: texto_novo = ""
    display_ref = texto_ref.replace('\n', '<br>'); display_novo = texto_novo.replace('\n', '<br>')
    comp_ref = clean_metadata_and_footers(texto_ref); comp_novo = clean_metadata_and_footers(texto_novo)
    norm_ref = normalize_for_comparison(comp_ref); norm_novo = normalize_for_comparison(comp_novo)
    comp_ref_nohy = re.sub(r'[-–—]', ' ', norm_ref); comp_novo_nohy = re.sub(r'[-–—]', ' ', norm_novo)
    if comp_ref_nohy == comp_novo_nohy:
        return melhorar_visual_topicos(display_ref), melhorar_visual_topicos(verificar_ortografia_inteligente(display_novo)), False
    if norm_ref == norm_novo:
        return melhorar_visual_topicos(display_ref), melhorar_visual_topicos(verificar_ortografia_inteligente(display_novo)), False
    if norm_ref and norm_novo:
        shorter, longer = (norm_ref, norm_novo) if len(norm_ref) <= len(norm_novo) else (norm_novo, norm_ref)
        if shorter and shorter in longer:
            return melhorar_visual_topicos(display_ref), melhorar_visual_topicos(verificar_ortografia_inteligente(display_novo)), False
    ratio = difflib.SequenceMatcher(None, norm_ref, norm_novo).ratio()
    jacc = jaccard_similarity(norm_ref, norm_novo)
    if ratio >= SIMILARITY_THRESHOLD or jacc >= SIMILARITY_THRESHOLD:
        return melhorar_visual_topicos(display_ref), melhorar_visual_topicos(verificar_ortografia_inteligente(display_novo)), False
    r_html, n_html, diff_bool = diff_preserve_original(display_ref, display_novo)
    r_html = melhorar_visual_topicos(r_html); n_html = verificar_ortografia_inteligente(n_html); n_html = melhorar_visual_topicos(n_html)
    return r_html, n_html, diff_bool

def normalize_for_comparison(text: str) -> str:
    if not text: return ""
    t = clean_metadata_and_footers(text)
    t = re.sub(r'(?m)^\s*\d+\s*[\.\)\-]\s*', '', t)
    t = re.sub(r'\b\d+\s*[\.\)]\s+', ' ', t)
    t = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', t)
    t = re.sub(r'<[^>]+>', '', t)
    t = strip_accents(t).lower()
    t = re.sub(r'[-–—]', ' ', t)
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

# ----------------- UI flow -----------------
st.title("💊 Gráfica x Arte (robusto)")
st.markdown("<div class='small-muted'>Comparação automática de seções com preservação de <b>negrito</b> e <i>itálico</i>.</div>", unsafe_allow_html=True)

tipo_bula = st.radio("Escolha o Tipo de Bula:", ("Paciente",), horizontal=True)
c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Gráfica", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("📜 Arte Vigente", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência"):
    secret_names = ["GEMINI_API_KEY","GEMINI_API_KEY1","GEMINI_API_KEY2","GEMINI_API_KEY3","GEMNI_API_KEY1","GEMNI_API_KEY2","GEMNI_API_KEY3"]
    keys_raw = [st.secrets.get(n) for n in secret_names]
    keys_validas = [k for k in keys_raw if k]

    if not f1 or not f2:
        st.warning("Adicione os arquivos."); st.stop()

    try:
        f1_bytes = f1.read(); f2_bytes = f2.read()
    except Exception as e:
        st.error(f"Erro ao ler arquivos: {e}"); st.stop()

    with st.spinner("Extraindo texto (local) e acionando OCR quando necessário..."):
        t_anvisa = extract_text_smart_from_bytes(f1_bytes, f1.name, api_keys=keys_validas)
        t_mkt = extract_text_smart_from_bytes(f2_bytes, f2.name, api_keys=keys_validas)

        if not t_anvisa or len(re.findall(r'\w', re.sub(r'<[^>]+>', '', t_anvisa))) < 20:
            st.error("ERRO: Conteúdo do arquivo GRÁFICA insuficiente para análise."); st.stop()
        if not t_mkt or len(re.findall(r'\w', re.sub(r'<[^>]+>', '', t_mkt))) < 20:
            st.error("ERRO: Conteúdo do arquivo ARTE insuficiente para análise."); st.stop()

    secoes_alvo = SECOES_PACIENTE
    dados_secoes = align_sections_between_texts(t_anvisa, t_mkt, secoes_alvo)

    if not dados_secoes:
        st.info("Nenhuma seção padrão encontrada automaticamente. Extraindo conteúdo inteiro como fallback.")
        dados_secoes = [{"titulo": "CONTEÚDO INTEIRO", "texto_anvisa": t_anvisa, "texto_mkt": t_mkt}]

    secoes_finais = []; divs_count = 0
    for item in dados_secoes:
        titulo_raw = (item.get('titulo') or '').strip()
        titulo = re.sub(r'^[\?\!\.\-\s]+', '', titulo_raw).strip()
        titulo = re.sub(r'[\s\-\–\—]*\d{1,4}\s*$', '', titulo).strip()
        txt_ref = (item.get('texto_anvisa') or "").strip()
        txt_mkt = (item.get('texto_mkt') or "").strip()
        titulo_upper = titulo.upper()
        if "CABEÇALHO" in titulo_upper:
            def safe_extract_header(raw_text, secoes_alvo):
                menor = None
                for s in secoes_alvo:
                    if s.strip().upper() == "CABEÇALHO DA BULA": continue
                    patt = r'\b' + r'\W+'.join(re.findall(r'\w+', s)) + r'\b'
                    m = re.search(patt, raw_text, flags=re.IGNORECASE)
                    if m:
                        if menor is None or m.start() < menor: menor = m.start()
                if menor is None:
                    m = re.search(r'\bAPRESENTA\S*\b', raw_text, flags=re.IGNORECASE)
                    menor = m.start() if m else None
                if menor is None: return ""
                header_raw = raw_text[:menor].strip()
                header_raw = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', header_raw)
                header_clean = clean_metadata_and_footers(header_raw)
                if len(header_clean) < 20: return ""
                if len(header_clean) > max(2000, int(len(raw_text)*0.35)): return ""
                return header_clean
            if (not txt_ref or len(txt_ref) < 50):
                novo_ref = safe_extract_header(t_anvisa, secoes_alvo)
                if novo_ref: txt_ref = novo_ref
            if (not txt_mkt or len(txt_mkt) < 50):
                novo_mkt = safe_extract_header(t_mkt, secoes_alvo)
                if novo_mkt: txt_mkt = novo_mkt
            txt_ref = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', txt_ref)
            txt_mkt = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', txt_mkt)

        html_ref, html_mkt, teve_diff = gerar_diff_html(txt_ref, txt_mkt)
        status = "DIVERGENTE" if teve_diff else "CONFORME"
        if teve_diff: divs_count += 1

        if not html_ref or re.sub(r'<[^>]+>', '', html_ref).strip() == "":
            html_ref = '<i>(Sem conteúdo extraído)</i>'
        if not html_mkt or re.sub(r'<[^>]+>', '', html_mkt).strip() == "":
            html_mkt = '<i>(Sem conteúdo extraído)</i>'

        secoes_finais.append({"titulo": titulo, "texto_anvisa": html_ref, "texto_mkt": html_mkt, "status": status})

    # Resumo e exibição
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
        status = item['status']; titulo = item['titulo'] or "Sem título"
        if "DIZERES LEGAIS" in titulo.upper(): icon, css, aberto = "⚖️", "border-info", True
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
