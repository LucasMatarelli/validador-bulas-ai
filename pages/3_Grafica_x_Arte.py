# app.py - Gráfica x Arte (Versão Gemini 2.5/3.0 - Multi-Key "GEMNI")
# - Focado em Gemini 2.5 Flash e Gemini 3 Flash
# - Usa rotação de chaves (GEMNI_API_KEY1...3)
# - Sistema de pausa automática (15s) para respeitar limite de 5 RPM

import streamlit as st
import google.generativeai as genai
import fitz  # PyMuPDF
import docx
import json
import difflib
import re
import unicodedata
import time
import concurrent.futures
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from spellchecker import SpellChecker
from io import BytesIO

# ----------------- CONFIGURAÇÕES GLOBAIS -----------------
APP_TITLE = "Gráfica x Arte"

# Aumentado para suportar latência de rede/modelo
TIMEOUT_S = 40  

# Apenas os modelos disponíveis na sua conta (conforme print anterior)
MODELOS_PARA_TENTAR_OCR = [
    "gemini-2.5-flash", 
    "gemini-3-flash",
    "gemma-3-27b-it"  # Gemma precisa do sufixo -it para instruções
]

MODELOS_PARA_TENTAR_GEN = [
    "gemini-2.5-flash",
    "gemini-3-flash"
]

# Seções esperadas
SECOES_PACIENTE = [
    "CABEÇALHO DA BULA",
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

# ----------------- UI & CSS -----------------
st.set_page_config(page_title=APP_TITLE, page_icon="💊", layout="wide")
st.markdown("""
<style>
    [data-testid="stHeader"] { visibility: hidden; }
    section[data-testid="stSidebar"] { display:block !important; visibility:visible !important; width:260px !important; min-width:260px !important; max-width:260px !important; transform: translateX(0) !important; transition:none !important; position:relative !important; background:#f7f9fb !important; z-index:999 !important; }
    section[data-testid="stSidebar"] > div:first-child { width:260px !important; }
    button[kind="header"], [data-testid="collapsedControl"], button[data-testid="baseButton-header"] { display:none !important; }
    .texto-box { font-family: 'Segoe UI', sans-serif; font-size:0.95rem; line-height:1.7; color:#212529; background:#fff; padding:20px; border-radius:8px; border:1px solid #e6e9ec; box-shadow:0 4px 12px rgba(18,40,80,0.03); }
    .highlight-yellow { background:#fff3cd; color:#856404; padding:2px 6px; border-radius:5px; border:1px solid #ffeeba; font-weight:700; }
    .highlight-blue { background:#d1ecf1; color:#0c5460; padding:2px 6px; border-radius:5px; border:1px solid #bee5eb; font-weight:700; }
    .topico-item { display:block; margin-left:20px; margin-bottom:6px; text-indent:-15px; }
    .border-ok { border-left:6px solid #28a745 !important; }
    .border-warn { border-left:6px solid #ffc107 !important; }
    .border-info { border-left:6px solid #17a2b8 !important; }
</style>
""", unsafe_allow_html=True)

st.title(APP_TITLE)
st.markdown("<div class='small-muted'>Comparação automática de seções com preservação de <b>negrito</b> e <i>itálico</i>.</div>", unsafe_allow_html=True)

# ----------------- UTIL HELPERS -----------------
def strip_accents(s: str) -> str:
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('ascii')

def tokenize_words(s: str):
    return re.findall(r'\w+', s, flags=re.UNICODE)

def jaccard_similarity(a: str, b: str) -> float:
    sa = set(tokenize_words(a)); sb = set(tokenize_words(b))
    if not sa and not sb: return 1.0
    if not sa or not sb: return 0.0
    inter = sa.intersection(sb); union = sa.union(sb)
    return len(inter)/len(union)

def clean_metadata_and_footers(texto: str) -> str:
    if not texto: return texto
    t = texto
    lines = t.splitlines()
    lines = [ln for ln in lines if not re.match(r'^\s*\d+\s*[\.\)]?\s*$', ln)]
    t = "\n".join(lines)
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
    return "\n".join(lines).strip()

def remover_rodapes_bula(texto: str) -> str:
    if not texto: return texto
    t = texto
    pads = [r'\b\d+ª\s*PROVA\b.*', r'Medida\s+do\s+bula.*', r'Tipologia\s+de\s+bula[:\-]?.*', r'Papel\s*[:\-]?.*', r'FRENTE.*Medida.*', r'conte[úu]do:.*atendimento@', r'www\.[^\s]+', r'[A-Z]{3,}\_\w{5,}']
    for p in pads: t = re.sub(p, '', t, flags=re.IGNORECASE)
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

# ----------------- CHAMADA SEGURA (TIMEOUT) -----------------
def call_model_with_timeout(api_key, modelo, payload, timeout_s=TIMEOUT_S):
    """Executa model.generate_content em thread separada com timeout."""
    def worker_call():
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(modelo)
        return model.generate_content(payload)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(worker_call)
        try:
            return future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError(f"Model {modelo} timeout after {timeout_s}s")
        except Exception as e:
            raise e

# ----------------- OCR COM ROTAÇÃO DE CHAVES E BACKOFF (COTA) -----------------
def ocr_via_gemini_bytes(bytes_data, api_keys, modelos=MODELOS_PARA_TENTAR_OCR, timeout_s=TIMEOUT_S):
    if not bytes_data:
        return "", "Arquivo vazio para OCR"
    
    prompt_ocr = """EXTRAIA APENAS O TEXTO DO PDF ABAIXO.
    Preserve as tags HTML <b> e <i> exatamente onde o texto está em negrito/itálico.
    NÃO inclua explicações ou JSON. Apenas o texto (com tags se houver)."""
    
    errors = []
    
    # Itera sobre suas 3 chaves GEMNI
    for i, key in enumerate(api_keys):
        for modelo in modelos:
            try:
                # Configura a key da vez
                genai.configure(api_key=key)
                
                # Payload: Prompt + Dados Binários (MimeType)
                payload = [prompt_ocr, {'mime_type':'application/pdf', 'data':bytes_data}]
                
                resp = call_model_with_timeout(key, modelo, payload, timeout_s=timeout_s)
                texto_extraido = getattr(resp, "text", "") or ""
                
                # Se vazio, tenta próximo
                if not texto_extraido.strip():
                    errors.append(f"{modelo} (key{i+1}) returned empty")
                    continue
                
                # --- Limpeza Pós-OCR ---
                texto_extraido = re.sub(r'^\s*(OCR\s*Result:|Texto extraído:|Resultado:)\s*', '', texto_extraido, flags=re.IGNORECASE)
                texto_extraido = re.sub(r'^```(?:[\w\-]+)?\s*', '', texto_extraido)
                texto_extraido = re.sub(r'\s*```$', '', texto_extraido)
                texto_extraido = texto_extraido.replace('\r\n', '\n').replace('\r', '\n')
                texto_extraido = re.sub(r'<\s*b\s*>', '<b>', texto_extraido, flags=re.IGNORECASE)
                texto_extraido = re.sub(r'<\s*/\s*b\s*>', '</b>', texto_extraido, flags=re.IGNORECASE)
                texto_extraido = re.sub(r'<\s*i\s*>', '<i>', texto_extraido, flags=re.IGNORECASE)
                texto_extraido = re.sub(r'<\s*/\s*i\s*>', '</i>', texto_extraido, flags=re.IGNORECASE)
                
                texto_extraido = remover_rodapes_bula(texto_extraido)
                texto_extraido = clean_metadata_and_footers(texto_extraido)
                
                if not re.sub(r'<[^>]+>', '', texto_extraido).strip():
                    errors.append(f"{modelo} returned only tags/empty after cleaning")
                    continue
                
                return texto_extraido, None
                
            except Exception as e:
                msg_erro = str(e).lower()
                errors.append(f"key#{i+1}:{modelo}: {str(e)}")
                
                # PROTEÇÃO DE COTA (429):
                # Se bater cota numa key, espera 15s antes de tentar a PRÓXIMA key/modelo
                if "429" in msg_erro or "quota" in msg_erro:
                    st.toast(f"⏳ Cota atingida (Key {i+1}). Pausando 15s...", icon="🛑")
                    time.sleep(15) 
                elif "404" in msg_erro:
                    # Modelo não existe, pula rápido
                    pass 
                else:
                    time.sleep(1)
                
                continue 

    return "", " | ".join(errors)

# ----------------- Extração Local -----------------
def extract_text_from_file_obj_bytes(bytes_data, filename):
    try:
        text = ""
        fname = filename.lower()
        if fname.endswith('.pdf'):
            doc = fitz.open(stream=bytes_data, filetype="pdf")
            for page in doc:
                blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get("blocks", [])
                page_text_spans = ""
                for block in blocks:
                    if block.get("type") != 0: continue
                    for line in block.get("lines", []):
                        line_text = ""
                        for span in line.get("spans", []):
                            content = span.get("text", "")
                            if not content: continue
                            flags = span.get("flags", 0)
                            font_name = span.get("font", "").lower()
                            is_bold = ((flags & 16) or "bold" in font_name or "black" in font_name or "heavy" in font_name or "semibold" in font_name)
                            is_italic = ((flags & 2) or "italic" in font_name or "oblique" in font_name)
                            formatted_text = content
                            if is_bold and is_italic: formatted_text = f"<b><i>{content}</i></b>"
                            elif is_bold: formatted_text = f"<b>{content}</b>"
                            elif is_italic: formatted_text = f"<i>{content}</i>"
                            line_text += formatted_text
                        page_text_spans += line_text + "\n"
                if page_text_spans.strip(): text += page_text_spans + "\n"
                else:
                    try: text += page.get_text("text") + "\n"
                    except: pass
            doc.close()
        elif fname.endswith('.docx'):
            doc = docx.Document(BytesIO(bytes_data))
            for para in doc.paragraphs:
                para_text = ""
                for run in para.runs:
                    content = run.text
                    if not content: continue
                    formatted = content
                    if run.bold and run.italic: formatted = f"<b><i>{content}</i></b>"
                    elif run.bold: formatted = f"<b>{content}</b>"
                    elif run.italic: formatted = f"<i>{content}</i>"
                    para_text += formatted
                text += para_text + "\n\n"
        else: return ""
        return clean_metadata_and_footers(text.strip())
    except Exception as e:
        st.error(f"Erro extração local: {e}")
        return ""

# ----------------- Helpers Lógicos -----------------
def build_section_pattern(title: str) -> str:
    words = re.findall(r'\w+', title, flags=re.UNICODE)
    if not words: return None
    pattern = r'\b' + r'\W+'.join(map(re.escape, words)) + r'\b'
    return pattern

def _build_flexible_title_regex(title: str):
    words = re.findall(r'\w+', title, flags=re.UNICODE)
    if not words: return None
    core = r'\W+'.join(map(re.escape, words))
    regex = rf'(?:^|\n)\s*(?:\d{{1,2}}\s*[\.\)\-]\s*|[IVXLCDM]+\s*[–-]\s*)?{core}'
    return regex

def extract_section_from_raw(texto: str, section_title: str, sections_list: list) -> str:
    if not texto or not section_title: return ""
    patt = _build_flexible_title_regex(section_title)
    if patt: m = re.search(patt, texto, flags=re.IGNORECASE | re.UNICODE)
    else: m = re.search(build_section_pattern(section_title), texto, flags=re.IGNORECASE | re.UNICODE)
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

def diff_preserve_original(text_a: str, text_b: str):
    if text_a is None: text_a = ""
    if text_b is None: text_b = ""
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
    pa, ma = _protect_html_tags(text_a); pb, mb = _protect_html_tags(text_b)
    matcher = difflib.SequenceMatcher(None, pa, pb)
    parts_a = []; parts_b = []; tem=False
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            parts_a.append(pa[i1:i2]); parts_b.append(pb[j1:j2])
        elif tag == 'replace':
            parts_a.append(f'<span class="highlight-yellow">{pa[i1:i2]}</span>'); parts_b.append(f'<span class="highlight-yellow">{pb[j1:j2]}</span>'); tem=True
        elif tag == 'delete':
            parts_a.append(f'<span class="highlight-yellow">{pa[i1:i2]}</span>'); tem=True
        elif tag == 'insert':
            parts_b.append(f'<span class="highlight-yellow">{pb[j1:j2]}</span>'); tem=True
    out_a=''.join(parts_a); out_b=''.join(parts_b)
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
    except: return texto

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

def gerar_diff_html(texto_ref, texto_novo, secoes_alvo=SECOES_PACIENTE):
    if texto_ref is None: texto_ref = ""
    if texto_novo is None: texto_novo = ""
    display_ref = texto_ref.replace('\n','<br>'); display_novo = texto_novo.replace('\n','<br>')
    comp_ref = clean_metadata_and_footers(texto_ref); comp_novo = clean_metadata_and_footers(texto_novo)
    norm_ref = normalize_for_comparison(comp_ref); norm_novo = normalize_for_comparison(comp_novo)
    if norm_ref == norm_novo:
        return melhorar_visual_topicos(display_ref), melhorar_visual_topicos(verificar_ortografia_inteligente(display_novo)), False
    if norm_ref and norm_novo:
        shorter, longer = (norm_ref, norm_novo) if len(norm_ref)<=len(norm_novo) else (norm_novo, norm_ref)
        if shorter in longer:
            return melhorar_visual_topicos(display_ref), melhorar_visual_topicos(verificar_ortografia_inteligente(display_novo)), False
    ratio = difflib.SequenceMatcher(None, norm_ref, norm_novo).ratio()
    jacc = jaccard_similarity(norm_ref, norm_novo)
    if ratio >= SIMILARITY_THRESHOLD or jacc >= SIMILARITY_THRESHOLD:
        return melhorar_visual_topicos(display_ref), melhorar_visual_topicos(verificar_ortografia_inteligente(display_novo)), False
    r_html, n_html, diff_bool = diff_preserve_original(display_ref, display_novo)
    r_html = melhorar_visual_topicos(r_html); n_html = verificar_ortografia_inteligente(n_html); n_html = melhorar_visual_topicos(n_html)
    return r_html, n_html, diff_bool

def destacar_datas(texto):
    padrao = r'(Esta\s+bula\s+foi\s+(?:atualizada\s+conforme\s+Bula\s+Padr[oã]o\s+)?aprovada\s+pela\s+Anvisa\s+em\s*)(\d{2}/\d{2}/\d{4}|\d{2}/\d{4})'
    def replacer(match): return f'{match.group(1)}<span class="highlight-blue">{match.group(2)}</span>'
    return re.sub(padrao, replacer, texto, flags=re.IGNORECASE|re.DOTALL)

def safe_extract_header(texto, sections):
    if not texto: return ""
    lines = texto.splitlines()
    header_acc = []
    first_section_patts = [build_section_pattern(s) for s in sections[1:4]] # check next 3 sections
    for ln in lines:
        is_next_sec = False
        for p in first_section_patts:
            if p and re.search(p, ln, re.IGNORECASE): is_next_sec = True; break
        if is_next_sec: break
        header_acc.append(ln)
    return "\n".join(header_acc).strip()

# ----------------- INTERFACE -----------------
c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Gráfica", type=["pdf","docx"], key="f1")
f2 = c2.file_uploader("📜 Arte Vigente", type=["pdf","docx"], key="f2")

if st.button("🚀 Processar Conferência"):
    st.info("Iniciando processamento...")
    if not f1 or not f2:
        st.warning("Envie ambos os arquivos."); st.stop()

    # Leitura específica das chaves que você informou
    secret_names = ["GEMNI_API_KEY1", "GEMNI_API_KEY2", "GEMNI_API_KEY3"]
    keys_raw = [st.secrets.get(n) for n in secret_names]
    keys_validas = [k for k in keys_raw if k]
    
    if not keys_validas:
        st.error("Nenhuma chave 'GEMNI_API_KEY' encontrada nos secrets."); st.stop()
    else:
        st.write(f"Utilizando {len(keys_validas)} chaves de API para processamento.")

    f1_bytes = f1.read()
    f2_bytes = f2.read()
    buf1 = BytesIO(f1_bytes); buf1.name = getattr(f1,"name","grafica")
    buf2 = BytesIO(f2_bytes); buf2.name = getattr(f2,"name","arte_vigente")

    with st.spinner("Extraindo texto localmente..."):
        t_anvisa = extract_text_from_file_obj_bytes(f1_bytes, buf1.name)
        t_mkt = extract_text_from_file_obj_bytes(f2_bytes, buf2.name)

    len_anvisa_plain = len(re.sub(r'<[^>]+>','', t_anvisa or ""))
    len_mkt_plain = len(re.sub(r'<[^>]+>','', t_mkt or ""))

    # OCR se < 1000 chars
    if len_anvisa_plain < 1000:
        st.info(f"Gráfica tem {len_anvisa_plain} chars -> acionando OCR (Gemini 2.5/3)...")
        texto_ocr, err = ocr_via_gemini_bytes(f1_bytes, keys_validas, modelos=MODELOS_PARA_TENTAR_OCR, timeout_s=TIMEOUT_S)
        if texto_ocr:
            t_anvisa = texto_ocr
            st.success("OCR Gráfica concluído")
        else:
            st.warning(f"OCR Gráfica falhou: {err} (mantendo extração local)")

    if len_mkt_plain < 1000:
        st.info(f"Arte Vigente tem {len_mkt_plain} chars -> acionando OCR (Gemini 2.5/3)...")
        texto_ocr2, err2 = ocr_via_gemini_bytes(f2_bytes, keys_validas, modelos=MODELOS_PARA_TENTAR_OCR, timeout_s=TIMEOUT_S)
        if texto_ocr2:
            t_mkt = texto_ocr2
            st.success("OCR Arte Vigente concluído")
        else:
            st.warning(f"OCR Arte Vigente falhou: {err2} (mantendo extração local)")

    st.info(f"Tamanho final Gráfica (chars): {len(re.sub(r'<[^>]+>','', t_anvisa or ''))}")
    st.info(f"Tamanho final Arte Vigente (chars): {len(re.sub(r'<[^>]+>','', t_mkt or ''))}")

    if len(re.sub(r'<[^>]+>','', t_anvisa or "")) < 20 or len(re.sub(r'<[^>]+>','', t_mkt or "")) < 20:
        st.error("Conteúdo insuficiente após extração/OCR."); st.stop()

    # Extração de Seções (JSON)
    prompt = f"""
Você é um Extrator de Dados Farmacêuticos Rigoroso.

INPUT TEXTO 1 (GRÁFICA): {t_anvisa[:150000]}
INPUT TEXTO 2 (ARTE): {t_mkt[:150000]}

REGRAS CRÍTICAS DE EXTRAÇÃO:
- Mantenha <b> e <i> exatamente
- Extraia seções listadas e retorne JSON com campos: data_anvisa_ref, data_anvisa_mkt, secoes[]
- Títulos: {SECOES_PACIENTE}
"""
    response_obj = None
    errors = []
    
    # Loop de tentativas de Geração com Rotação de Key e Proteção 429
    for i, key in enumerate(keys_validas):
        genai.configure(api_key=key) # Garante que a key da vez está ativa
        
        for modelo in MODELOS_PARA_TENTAR_GEN:
            try:
                # Payload simples para texto
                resp = call_model_with_timeout(key, modelo, prompt, timeout_s=TIMEOUT_S)
                response_obj = resp
                st.info(f"Modelo generativo aceito: {modelo} (usando Key {i+1})")
                break
            except Exception as e:
                msg = str(e).lower()
                errors.append(f"key#{i+1}|{modelo}:{msg}")
                
                # Proteção Cota (5 RPM)
                if "429" in msg or "quota" in msg:
                    st.toast(f"⏳ Cota atingida (Key {i+1}). Pausando 15s...", icon="🛑")
                    time.sleep(15) 
                else:
                    time.sleep(1)
                continue
        if response_obj: break

    if not response_obj:
        st.error("Falha ao chamar modelo generativo: " + (" | ".join(errors)))
        st.stop()

    resp_text = getattr(response_obj, "text", None) or str(response_obj)

    def extract_json_block_local(text: str):
        if not text or '{' not in text: return None
        start = text.find('{'); depth = 0; in_string = False; esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if ch == '"' and not esc: in_string = not in_string
            if in_string:
                esc = (ch == '\\' and not esc); continue
            if ch == '{': depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0: return text[start:i+1]
        return None

    try:
        try: resultado = json.loads(resp_text)
        except Exception:
            bloco = extract_json_block_local(resp_text)
            if bloco: resultado = json.loads(bloco)
            else:
                st.error("Resposta do modelo não contém JSON válido.")
                st.code(resp_text); st.stop()
    except Exception as e:
        st.error(f"Erro ao decodificar JSON: {e}"); st.code(resp_text); st.stop()

    dados_secoes = resultado.get("secoes", [])
    secoes_finais = []
    divs_count = 0
    extracted_date_ref = resultado.get("data_anvisa_ref", "-")
    extracted_date_mkt = resultado.get("data_anvisa_mkt", "-")
    frase_padrao = r'Esta\s+bula\s+foi\s+atualizada\s+conforme\s+Bula\s+Padr[oã]o\s+aprovada\s+pela\s+Anvisa\s+em\s*(\d{2}/\d{2}/\d{4}|\d{2}/\d{4})'

    for item in dados_secoes:
        titulo = item.get('titulo','').strip()
        txt_ref = item.get('texto_anvisa','').strip()
        txt_mkt = item.get('texto_mkt','').strip()
        if not txt_ref:
            tentativa = extract_section_from_raw(t_anvisa, titulo, SECOES_PACIENTE)
            if tentativa: txt_ref = tentativa
        if not txt_mkt:
            tentativa2 = extract_section_from_raw(t_mkt, titulo, SECOES_PACIENTE)
            if tentativa2: txt_mkt = tentativa2
        txt_ref = clean_metadata_and_footers(txt_ref)
        txt_mkt = clean_metadata_and_footers(txt_mkt)

        if "CABEÇALHO" in titulo.upper():
            novo_ref = safe_extract_header(t_anvisa, SECOES_PACIENTE)
            if novo_ref and (not txt_ref or len(novo_ref) < len(txt_ref) or len(txt_ref) < 50): txt_ref = novo_ref
            novo_mkt = safe_extract_header(t_mkt, SECOES_PACIENTE)
            if novo_mkt and (not txt_mkt or len(novo_mkt) < len(txt_mkt) or len(txt_mkt) < 50): txt_mkt = novo_mkt
            txt_ref = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*','', txt_ref)
            txt_mkt = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*','', txt_mkt)

        if "DIZERES LEGAIS" in titulo.upper():
            m_ref = re.search(frase_padrao, txt_ref, flags=re.IGNORECASE)
            if m_ref and extracted_date_ref == "-": extracted_date_ref = m_ref.group(1)
            m_mkt = re.search(frase_padrao, txt_mkt, flags=re.IGNORECASE)
            if m_mkt and extracted_date_mkt == "-": extracted_date_mkt = m_mkt.group(1)
            html_ref = destacar_datas(txt_ref).replace('\n','<br>')
            html_novo = destacar_datas(txt_mkt).replace('\n','<br>')
            html_ref = verificar_ortografia_inteligente(html_ref); html_novo = verificar_ortografia_inteligente(html_novo)
            html_ref = melhorar_visual_topicos(html_ref); html_novo = melhorar_visual_topicos(html_novo)
            status = "CONFORME"
        else:
            html_ref, html_novo, teve_diff = gerar_diff_html(txt_ref, txt_mkt, SECOES_PACIENTE)
            status = "DIVERGENTE" if teve_diff else "CONFORME"
            if teve_diff: divs_count += 1
        secoes_finais.append({"titulo": titulo, "texto_anvisa": html_ref, "texto_mkt": html_novo, "status": status})

    st.markdown("### 📊 Resumo")
    c1, c2, c3 = st.columns(3)
    c1.metric("Data Gráfica", extracted_date_ref)
    c2.metric("Data Arte Vigente", extracted_date_mkt, delta="Igual" if extracted_date_ref == extracted_date_mkt and extracted_date_ref != "-" else "Diferente")
    c3.metric("Seções", len(secoes_finais))
    if divs_count > 0: st.warning(f"⚠️ Divergências encontradas em {divs_count} seção(ões).")
    else: st.success("✨ Divergências: 0")
    st.divider()

    for item in secoes_finais:
        status = item['status']; titulo = item['titulo'] or "Sem título"
        if "DIZERES LEGAIS" in titulo.upper(): icon, css, aberto = "⚖️","border-info",True
        elif status=="CONFORME": icon, css, aberto = "✅","border-ok",False
        else: icon, css, aberto = "⚠️","border-warn",True
        with st.expander(f"{icon} {titulo}", expanded=aberto):
            ce, cd = st.columns(2)
            with ce:
                st.caption("Gráfica")
                st.markdown(f'<div class="texto-box {css}">{item["texto_anvisa"]}</div>', unsafe_allow_html=True)
            with cd:
                st.caption("Arte Vigente")
                st.markdown(f'<div class="texto-box {css}">{item["texto_mkt"]}</div>', unsafe_allow_html=True)
