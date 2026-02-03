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
st.set_page_config(page_title="Gráfica x Arte (robusto)", page_icon="💊", layout="wide")

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
        min-height: 120px;
        overflow-wrap: break-word;
        white-space: pre-wrap;
    }
    .highlight-yellow { background-color: #fff3cd; color: #856404; padding: 2px 4px; border-radius: 4px; border: 1px solid #ffeeba; font-weight: bold; }
    .highlight-red { background-color: #f8d7da; color: #721c24; border-bottom: 2px solid #dc3545; font-weight: bold; cursor: help; }
    .highlight-blue { background-color: #d1ecf1; color: #0c5460; padding: 2px 4px; border-radius: 4px; border: 1px solid #bee5eb; font-weight: bold; }
    .topico-item { display: block; margin-left: 20px; margin-bottom: 4px; text-indent: -15px; }
    .border-ok { border-left: 6px solid #28a745 !important; }
    .border-warn { border-left: 6px solid #ffc107 !important; } 
    .border-info { border-left: 6px solid #17a2b8 !important; }
    div[data-testid="stMetric"] { background-color: #f8f9fa; border: 1px solid #dee2e6; padding: 10px; border-radius: 5px; text-align: center; }
    section[data-testid="stSidebar"] { display: block !important; visibility: visible !important; width: 250px !important; min-width: 250px !important; max-width: 250px !important; margin-left: 0 !important; transform: translateX(0) !important; transition: none !important; position: relative !important; background-color: #f0f2f6 !important; z-index: 999 !important; }
    section[data-testid="stSidebar"] > div:first-child { width: 250px !important; min-width: 250px !important; }
    section[data-testid="stSidebar"][aria-expanded="false"], section[data-testid="stSidebar"][aria-expanded="true"] { margin-left: 0 !important; transform: translateX(0) !important; }
    button[kind="header"], [data-testid="collapsedControl"], button[data-testid="baseButton-header"] { display: none !important; }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO -----------------
MODELOS_PARA_TENTAR = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash"
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
    """
    Limpeza suave para REMOVER metadados/rodapés visíveis que atrapalham comparação.
    Ampliei padrões para remover dimensões, 'provas', datas isoladas, códigos, links, linhas de pontos etc.
    """
    if not texto:
        return texto
    t = texto

    # Remover linhas que são apenas medidas (e.g. "450 mm", "190 mm", "12mm", "12 mm")
    t = re.sub(r'(?im)^\s*\d{1,4}\s*(?:m{0,1}m|mm)\b.*$', '', t)

    # Remover linhas de prova / revisões e datas curtas em linhas
    t = re.sub(r'(?im)^\s*\d+\s*(?:ª|a)?\s*prova\b.*$', '', t)
    t = re.sub(r'(?im)^\s*(?:prova|revis[oã]o)\b.*$', '', t)
    # datas isoladas dd/mm/yyyy ou dd/mm/yy ou dd-mm-yyyy
    t = re.sub(r'(?m)^\s*\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}\s*$', '', t)

    # Remover nomes de arquivo / tags técnicas exclusivamente MAIÚSCULAS com underscores
    t = re.sub(r'(?m)^\s*[A-Z0-9_]{8,}\s*$', '', t)

    # Remove linhas tipicamente técnicas (medidas, tipologia, papel, cor, frente/verso)
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

    # Dimensões e paginação (variações)
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

    # Remover sequências longas de pontos/tracinhos que normalmente são guias visuais
    t = re.sub(r'(?m)[\.\-]{3,}', ' ', t)

    # Remove quebras por hífen no final da linha (sílabas cortadas)
    t = re.sub(r'-\s*\n\s*', '', t)

    # normaliza espaços e quebras
    t = re.sub(r'[ \t]{2,}', ' ', t)
    t = re.sub(r'\r', '\n', t)
    t = re.sub(r'\n{3,}', '\n\n', t)

    # limpar linhas vazias e linhas que só contenham números/códigos curtos
    lines = [ln.rstrip() for ln in t.splitlines()]
    filtered = []
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        # linhas apenas com números ou medidas curtas -> pular
        if re.match(r'^[\d\W_]{1,30}$', s) and not re.search(r'[A-Za-zÀ-ÿ]', s):
            continue
        filtered.append(ln)
    t = "\n".join(filtered)

    return t.strip()

def remove_section_titles_for_comparison(texto: str, sections_list=SECOES_PACIENTE) -> str:
    """
    Remove títulos de seção conhecidos apenas para COMPARAÇÃO (mantém visualização intacta).
    """
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
    """
    Normalização forte para comparar conteúdo sem ruído: acentos, pontuação, títulos, numeração.
    """
    if not text:
        return ""
    t = clean_metadata_and_footers(text)
    t = remove_section_titles_for_comparison(t)
    # remover numeração tipo "2." ou "2)"
    t = re.sub(r'(?m)^\s*\d+\s*[\.\)\-]\s*', '', t)
    t = re.sub(r'\b\d+\s*[\.\)]\s+', ' ', t)
    # remover numerais romanos no começo de linhas
    t = re.sub(r'(?m)^\s*[IVXLCDM]+\s*[–-]\s*', '', t)
    t = re.sub(r'<[^>]+>', '', t)
    t = strip_accents(t).lower()
    # remove pontuação mas deixa espaços
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
    """Corretor conservador (não altera), mantém placeholders."""
    try:
        spell = SpellChecker(language='pt')
        whitelist = {
            'mg','ml','mcg','ui','g','kg','l','dl','mmhg','bpm','kcal','anvisa','cnpj','cep','sac','bula'
        }
        spell.word_frequency.load_words(whitelist)
        return texto
    except:
        return texto

# ----------------- 5. DIFF ROBUSTO (PROTEÇÃO DE TAGS + REMOÇÃO DE TOKENS RESIDUAIS) -----------------

def _protect_html_tags(s: str):
    """
    Substitui cada tag HTML (<...>) por um único caractere do Private Use Area
    e retorna a string protegida + um mapeamento token->tag.
    """
    if not s:
        return s, {}

    mapping = {}
    index = 0

    def repl(m):
        nonlocal index
        token = chr(0xE000 + index)  # private use char
        mapping[token] = m.group(0)
        index += 1
        return token

    protected = re.sub(r'<[^>]+>', repl, s)
    return protected, mapping

def _restore_html_tags(s: str, mapping: dict):
    """
    Substitui tokens únicos de volta para as tags originais.
    """
    if not mapping:
        return s
    # substitui todos os tokens por suas tags
    for token, tag in mapping.items():
        if token in s:
            s = s.replace(token, tag)
    return s

def _remove_private_use_chars(s: str):
    """
    Remove qualquer caractere do bloco Private Use (evita aparecer glyphs estranhos como '?').
    """
    if not s:
        return s
    return re.sub(r'[\uE000-\uF8FF]', '', s)

def diff_preserve_original(text_a: str, text_b: str):
    """
    Faz diff em nível de caracteres preservando EXATAMENTE os textos originais,
    protegendo tags HTML para NÃO quebrá-las. Envolve trechos divergentes com
    <span class="highlight-yellow">...</span>.
    Retorna (html_a, html_b, tem_diff)
    """
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

    # Restaurar tags originais
    out_a = _restore_html_tags(out_a, map_a)
    out_a = _restore_html_tags(out_a, map_b)  # segurança - restaurar qualquer token do outro mapa
    out_b = _restore_html_tags(out_b, map_b)
    out_b = _restore_html_tags(out_b, map_a)

    # Garantir que nenhum private-use-char fique aparecendo (evita '?')
    out_a = _remove_private_use_chars(out_a)
    out_b = _remove_private_use_chars(out_b)

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

def _alnum_only(s: str) -> str:
    return re.sub(r'[^0-9a-zA-Z]', '', strip_accents(s).lower()) if s else ""

def gerar_diff_html(texto_ref, texto_novo):
    """
    Faz comparação robusta com heurísticas extras:
    - normalização forte
    - checagem alfanumérica apenas (ignora pontuações/espacos)
    - se realmente diferente: diff preservando tags
    """
    if texto_ref is None: texto_ref = ""
    if texto_novo is None: texto_novo = ""

    display_ref = texto_ref.replace('\n', '<br>')
    display_novo = texto_novo.replace('\n', '<br>')

    norm_ref = normalize_for_comparison(texto_ref)
    norm_novo = normalize_for_comparison(texto_novo)

    # 0) se apenas diferenças de pontuação/espaços (mesmo conteúdo alfanumérico) -> conforme
    if _alnum_only(norm_ref) and _alnum_only(norm_ref) == _alnum_only(norm_novo):
        return melhorar_visual_topicos(display_ref), melhorar_visual_topicos(verificar_ortografia_inteligente(display_novo)), False

    # 1) igualdade absoluta após normalização
    if norm_ref == norm_novo:
        return melhorar_visual_topicos(display_ref), melhorar_visual_topicos(verificar_ortografia_inteligente(display_novo)), False

    # 2) substring (um contém o outro em grande proporção) -> conforme
    if norm_ref and norm_novo:
        shorter, longer = (norm_ref, norm_novo) if len(norm_ref) <= len(norm_novo) else (norm_novo, norm_ref)
        if shorter and shorter in longer:
            prop = len(shorter) / max(1, len(longer))
            if prop >= 0.88:
                return melhor_visual_topicos(display_ref), melhor_visual_topicos(verificar_ortografia_inteligente(display_novo)), False

    # 3) similaridade mista (sequence + jaccard)
    ratio = difflib.SequenceMatcher(None, norm_ref, norm_novo).ratio()
    jacc = jaccard_similarity(norm_ref, norm_novo)
    if ratio >= SIMILARITY_THRESHOLD or jacc >= SIMILARITY_THRESHOLD:
        return melhorar_visual_topicos(display_ref), melhorar_visual_topicos(verificar_ortografia_inteligente(display_novo)), False

    # 4) Caso contrário: diff em nível de caracteres PRESERVANDO o texto original
    html_ref, html_novo, diff_bool = diff_preserve_original(display_ref, display_novo)
    html_ref = melhorar_visual_topicos(html_ref)
    html_novo = melhor_visual_topicos = melhorar_visual_topicos(html_novo)  # keep consistent naming
    return html_ref, html_novo, diff_bool

# ----------------- 6. REMOVER RODAPÉS (SUAVE) -----------------

def remover_rodapes_bula(texto):
    """
    Versão suavizada: remove padrões técnicos óbvios, medidas, provas, datas isoladas e links.
    Preserva linhas com texto corrido.
    """
    if not texto:
        return texto

    t = texto

    padroes = [
        r'(?im)^\s*\d{1,4}\s*(?:m{0,1}m|mm)\b.*',   # 450 mm, 190 mm, etc
        r'(?im)^\s*\d+\s*(?:ª|a)?\s*prova\b.*',     # 1ª PROVA ...
        r'(?im)^\s*(?:prova|revis[oã]o)\b.*',
        r'(?im)^\s*\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}\s*$',  # isolated dates
        r'(?im)^\s*Medida\s+do\s+bula.*',
        r'(?im)^\s*Tipologia\s+de\s+bula[:\-]?.*',
        r'(?im)^\s*Papel\s*[:\-]?.*',
        r'(?im)^\s*FRENTE.*Medida.*',
        r'(?im)conte[úu]do:.*atendimento@',
        r'(?im)www\.[^\s]+',
        r'(?im)[A-Z]{3,}\_\w{5,}',
    ]
    for p in padroes:
        t = re.sub(p, '', t, flags=re.IGNORECASE)

    linhas = t.splitlines()
    linhas_filtradas = []
    for ln in linhas:
        ln_s = ln.strip()
        if not ln_s:
            continue
        # remover linhas curtas que só contenham códigos / números / medidas
        if re.match(r'^[\d\W_]{1,30}$', ln_s) and not re.search(r'[A-Za-zÀ-ÿ]', ln_s):
            continue
        # remover linhas com muitos pontos/tracinhos
        if re.match(r'^[\.\- ]{3,}$', ln_s):
            continue
        linhas_filtradas.append(ln.rstrip())

    retorno = '\n'.join(linhas_filtradas)
    retorno = re.sub(r'\n{3,}', '\n\n', retorno)

    # Remover número residual isolado no fim do documento (ex: "1" solto)
    retorno = re.sub(r'(?m)\n\s*\d+\s*$', '\n', retorno)

    return retorno.strip()

# ----------------- 7. OCR VIA GEMINI (mantive sua lógica, com pequenas seguranças) -----------------

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
    """
    Trabalha sobre bytes (evita múltiplas leituras do UploadedFile).
    Heurística de fallback para OCR mais robusta.
    """
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
                            formatted_text = content  # NÃO STRIP para evitar picotamento
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

        # limpeza leve para checagem
        texto_sem_tags = re.sub(r'<[^>]+>', '', raw_text).strip()
        texto_para_checar = remover_rodapes_bula(texto_sem_tags)

        # Heurística: se poucos caracteres alfanuméricos -> tentar OCR
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

# ----------------- 9. EXTRAÇÃO DETERMINÍSTICA DE SEÇÕES (MELHORADA) -----------------

def _normalize_line_for_search(line: str) -> str:
    return re.sub(r'\s+', ' ', strip_accents(line).lower()).strip()

def extract_sections_by_headers(text, sections_list=SECOES_PACIENTE):
    """
    Localiza títulos no texto e retorna lista com dicionários {'titulo','texto'}.
    Estratégia:
      1) tentativa estrita por regex no texto inteiro
      2) fallback por linha: procurar linha que contenha tokens do título em ordem (limitado às primeiras 3 palavras)
         e que seja uma linha curta / uppercase / ou que comece com numeração (ex: '9. ').
    Isso reduz casos em que um título aparece dentro de outro texto e garante maior precisão.
    """
    if not text:
        return []

    found = []
    text_lines = text.splitlines()
    text_norm_lines = [_normalize_line_for_search(ln) for ln in text_lines]

    for s in sections_list:
        if not s:
            continue
        tokens = re.findall(r'\w+', s)
        if not tokens:
            continue
        # padrão tolerante (palavras em ordem)
        patt = r'(?im)\b' + r'\W+'.join(map(re.escape, tokens)) + r'\b'
        m = re.search(patt, text)
        if m:
            found.append((m.start(), m.end(), s))
            continue

        # fallback línea a línea (fuzzy), procura por linha que contenha as primeiras 3 tokens em ordem
        tokens_norm = [strip_accents(t).lower() for t in tokens]
        for idx, ln_norm in enumerate(text_norm_lines):
            pos = 0
            ok = True
            for tk in tokens_norm[:3]:
                p = ln_norm.find(tk, pos)
                if p == -1:
                    ok = False
                    break
                pos = p + len(tk)
            if ok:
                orig_ln = text_lines[idx].strip()
                # condições para aceitar como header: linha curta, ou toda em maiúsculas, ou começa com número (ex: '9.')
                if len(orig_ln) <= 140 or orig_ln.upper() == orig_ln or re.match(r'^\s*\d+\s*[\.\)]', orig_ln):
                    start_est = sum(len(l) + 1 for l in text_lines[:idx])
                    end_est = start_est + len(text_lines[idx])
                    found.append((start_est, end_est, s))
                    break

    if not found:
        return []

    # ordenar e extrair trechos entre headers
    found.sort(key=lambda x: x[0])
    secoes = []
    for idx, (start, end, titulo) in enumerate(found):
        start_content = end
        end_content = found[idx+1][0] if idx+1 < len(found) else len(text)
        conteudo = text[start_content:end_content].strip()
        conteudo = clean_metadata_and_footers(conteudo)
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
        # Inclui mesmo que um dos lados esteja vazio, para mostrar lado-a-lado (evita colunas sem nada)
        if not txt_ref and not txt_mkt:
            continue
        final.append({"titulo": titulo, "texto_anvisa": txt_ref, "texto_mkt": txt_mkt})
    return final

# ----------------- 10. UI PRINCIPAL -----------------
st.title("💊 Gráfica x Arte — versão ajustada")

tipo_bula = st.radio("Escolha o Tipo de Bula:", ("Paciente",), horizontal=True)

c1, c2 = st.columns(2)
f1 = c1.file_uploader("📜 Gráfica", type=["pdf", "docx"], key="f1")
f2 = c2.file_uploader("📜 Arte Vigente", type=["pdf", "docx"], key="f2")

if st.button("🚀 Processar Conferência"):
    keys_raw = [
        st.secrets.get("GEMINI_API_KEY"),
        st.secrets.get("GEMINI_API_KEY2"),
        st.secrets.get("GEMINI_API_KEY3")
    ]
    keys_validas = [k for k in keys_raw if k]

    if not f1 or not f2:
        st.warning("Adicione os arquivos.")
        st.stop()

    # Lê os arquivos UMA vez em bytes — evita leituras intermitentes/vazias
    try:
        f1_bytes = f1.read()
        f2_bytes = f2.read()
    except Exception as e:
        st.error(f"Erro ao ler arquivos do uploader: {e}")
        st.stop()

    with st.spinner("Analisando arquivos individualmente (Texto ou OCR)..."):
        t_anvisa = extract_text_smart_from_bytes(f1_bytes, f1.name, api_keys=keys_validas)
        t_mkt = extract_text_smart_from_bytes(f2_bytes, f2.name, api_keys=keys_validas)

        # validação robusta (checar caracteres alfanuméricos)
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
        titulo = (item.get('titulo') or '').strip()
        txt_ref = (item.get('texto_anvisa') or "").strip()
        txt_mkt = (item.get('texto_mkt') or "").strip()

        titulo_upper = titulo.upper()
        eh_blindada = any(b in titulo_upper for b in SECOES_SEM_COMPARACAO)

        # Cabeçalho (se houver lógica específica)
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

        # Evita colunas totalmente em branco na UI
        if not html_ref or re.sub(r'<[^>]+>', '', html_ref).strip() == "":
            html_ref = '<i>(Sem conteúdo extraído)</i>'
        if not html_mkt or re.sub(r'<[^>]+>', '', html_mkt).strip() == "":
            html_mkt = '<i>(Sem conteúdo extraído)</i>'

        secoes_finais.append({"titulo": titulo, "texto_anvisa": html_ref, "texto_mkt": html_mkt, "status": status})

    # Exibição do resumo e seções
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
