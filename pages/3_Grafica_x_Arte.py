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
    
    .highlight-red { 
        background-color: #f8d7da; color: #721c24; 
        border-bottom: 2px solid #dc3545; 
        font-weight: bold;
        cursor: help;
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
    
    section[data-testid="stSidebar"][aria-expanded="false"],
    section[data-testid="stSidebar"][aria-expanded="true"] {
        margin-left: 0 !important;
        transform: translateX(0) !important;
    }
    
    button[kind="header"],
    [data-testid="collapsedControl"],
    button[data-testid="baseButton-header"] {
        display: none !important;
    }
</style>
""", unsafe_allow_html=True)

# ----------------- 2. CONFIGURAÇÃO -----------------
MODELOS_PARA_TENTAR = [
    "models/gemini-2.5-flash", 
    "models/gemini-2.0-flash", 
    "models/gemini-1.5-flash", 
    "gemini-1.5-flash"
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

# Seções que você quer blindar da comparação (mantive vazio por padrão)
SECOES_SEM_COMPARACAO = []

# Threshold de similaridade (ajuste se achar necessário)
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
    Limpeza suave para REMOVER apenas metadados/rodapés visíveis que atrapalham compara��ão.
    NÃO usar esta versão para gerar o texto exibido - apenas para comparação.
    """
    if not texto:
        return texto
    t = texto

    # Remove nomes de arquivo / tags técnicas exclusivamente MAIÚSCULAS com underscores
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

    # Remove quebras por hífen no final da linha (sílabas cortadas)
    t = re.sub(r'-\s*\n\s*', '', t)

    # normaliza espaços e quebras
    t = re.sub(r'[ \t]{2,}', ' ', t)
    t = re.sub(r'\r', '\n', t)
    t = re.sub(r'\n{3,}', '\n\n', t)

    # limpar linhas vazias
    lines = [ln.rstrip() for ln in t.splitlines()]
    lines = [ln for ln in lines if ln.strip() != ""]
    t = "\n".join(lines)

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
    # count=0 para destacar todas as ocorrências
    return re.sub(padrao, replacer, texto, count=0, flags=re.IGNORECASE | re.DOTALL)

def verificar_ortografia_inteligente(texto):
    """Mantém essencialmente o texto — corretor conservador (não altera)."""
    try:
        spell = SpellChecker(language='pt')
        whitelist = {
            'mg','ml','mcg','ui','g','kg','l','dl','mmhg','bpm','kcal','anvisa','cnpj','cep','sac','bula'
        }
        spell.word_frequency.load_words(whitelist)
        # Não alteramos o texto aqui, só mantemos integração se quiser futuramente
        return texto
    except:
        return texto

# ----------------- 5. DIFF ROBUSTO (CHAR-PRESERVING) -----------------

def diff_preserve_original(text_a: str, text_b: str):
    """
    Faz diff em nível de caracteres preservando EXATAMENTE os textos originais,
    envolvendo trechos divergentes com <span class="highlight-yellow">...</span>.
    Retorna (html_a, html_b, tem_diff)
    """
    if text_a is None: text_a = ""
    if text_b is None: text_b = ""
    matcher = difflib.SequenceMatcher(None, text_a, text_b)
    parts_a = []
    parts_b = []
    tem = False
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == 'equal':
            parts_a.append(text_a[i1:i2])
            parts_b.append(text_b[j1:j2])
        elif tag == 'replace':
            parts_a.append(f'<span class="highlight-yellow">{text_a[i1:i2]}</span>')
            parts_b.append(f'<span class="highlight-yellow">{text_b[j1:j2]}</span>')
            tem = True
        elif tag == 'delete':
            parts_a.append(f'<span class="highlight-yellow">{text_a[i1:i2]}</span>')
            tem = True
        elif tag == 'insert':
            parts_b.append(f'<span class="highlight-yellow">{text_b[j1:j2]}</span>')
            tem = True
    return ''.join(parts_a), ''.join(parts_b), tem

def diff_palavra_a_palavra(texto_ref, texto_novo):
    # Mantive por compatibilidade, mas não usamos quando queremos preservar texto original
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
    """
    Faz comparação robusta:
    - Normaliza fortemente e verifica igualdade.
    - Substring-proportion e similaridade Jaccard/SequenceMatcher para evitar falsos-positivos.
    - Só se realmente diferente, executa diff preservando os textos originais (char-level).
    """
    if texto_ref is None: texto_ref = ""
    if texto_novo is None: texto_novo = ""

    # Para exibição, usamos a versão literal (preservando <b>/<i> se houver)
    display_ref = texto_ref.replace('\n', '<br>')
    display_novo = texto_novo.replace('\n', '<br>')

    # Versões preparadas para comparação
    norm_ref = normalize_for_comparison(texto_ref)
    norm_novo = normalize_for_comparison(texto_novo)

    # 1) igualdade absoluta após normalização
    if norm_ref == norm_novo:
        return melhorar_visual_topicos(display_ref), melhorar_visual_topicos(verificar_ortografia_inteligente(display_novo)), False

    # 2) substring (um contém o outro em grande proporção) -> conforme
    if norm_ref and norm_novo:
        shorter, longer = (norm_ref, norm_novo) if len(norm_ref) <= len(norm_novo) else (norm_novo, norm_ref)
        if shorter and shorter in longer:
            prop = len(shorter) / max(1, len(longer))
            if prop >= 0.88:
                return melhorar_visual_topicos(display_ref), melhorar_visual_topicos(verificar_ortografia_inteligente(display_novo)), False

    # 3) similaridade mista
    ratio = difflib.SequenceMatcher(None, norm_ref, norm_novo).ratio()
    jacc = jaccard_similarity(norm_ref, norm_novo)
    if ratio >= SIMILARITY_THRESHOLD or jacc >= SIMILARITY_THRESHOLD:
        return melhorar_visual_topicos(display_ref), melhorar_visual_topicos(verificar_ortografia_inteligente(display_novo)), False

    # 4) Caso contrário: diff em nível de caracteres PRESERVANDO o texto original
    # usamos display_ref/display_novo (com <b>/<i> preservados) para construir o destaque
    html_ref, html_novo, diff_bool = diff_preserve_original(display_ref, display_novo)
    # garantir aplicações de visual improvements (topicos) somente depois de construído
    html_ref = melhorar_visual_topicos(html_ref)
    html_novo = melhorar_visual_topicos(html_novo)
    return html_ref, html_novo, diff_bool

# ----------------- 6. REMOVER RODAPÉS (SUAVE) -----------------

def remover_rodapes_bula(texto):
    """
    Versão suavizada: remove padrões técnicos óbvios MAS preserva linhas com texto corrido.
    """
    if not texto:
        return texto

    t = texto

    # padrões específicos que costumam ser metadados
    padroes = [
        r'\b\d+ª\s*PROVA\b.*',                    # 1ª PROVA - date
        r'Medida\s+do\s+bula.*',                  # linhas de medidas
        r'Tipologia\s+de\s+bula[:\-]?.*',         # tipologia
        r'Papel\s*[:\-]?.*',                      # papel
        r'FRENTE.*Medida.*',                       # frente linha técnica
        r'conte[úu]do:.*atendimento@',             # emails técnicos
        r'www\.[^\s]+',                            # links soltos
        r'[A-Z]{3,}\_\w{5,}',                     # BUL_SOMETHING identifiers
    ]
    for p in padroes:
        t = re.sub(p, '', t, flags=re.IGNORECASE)

    # remover linhas curtas que só contenham códigos / números / medidas
    linhas = t.splitlines()
    linhas_filtradas = []
    for ln in linhas:
        ln_s = ln.strip()
        if not ln_s:
            continue
        if re.match(r'^[\d\W_]{1,30}$', ln_s):
            continue
        linhas_filtradas.append(ln.rstrip())

    retorno = '\n'.join(linhas_filtradas)
    retorno = re.sub(r'\n{3,}', '\n\n', retorno)
    return retorno.strip()

# ----------------- 7. OCR VIA GEMINI (mantive sua lógica, com pequenas seguranças) -----------------

def ocr_via_gemini(uploaded_file, api_keys):
    uploaded_file.seek(0)
    bytes_data = uploaded_file.read()

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

# ----------------- 8. EXTRAÇÃO INTELIGENTE (RETORNA RAW PARA EXIBIÇÃO) -----------------

def extract_text_smart(uploaded_file, api_keys=None):
    try:
        raw_text = ""
        if uploaded_file.name.lower().endswith('.pdf'):
            uploaded_file.seek(0)
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            for page in doc:
                blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
                for block in blocks:
                    if block.get("type") != 0:
                        continue
                    block_text = ""
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
                        block_text += line_text.strip() + " "
                    raw_text += block_text.strip() + "\n\n"
            doc.close()

        elif uploaded_file.name.lower().endswith('.docx'):
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

        texto_sem_tags = re.sub(r'<[^>]+>', '', raw_text).strip()
        texto_limpo_para_checar = remover_rodapes_bula(texto_sem_tags)

        eh_pdf = uploaded_file.name.lower().endswith('.pdf')
        if eh_pdf and len(texto_limpo_para_checar) < 1000 and api_keys:
            st.warning(f"👁️ Arquivo '{uploaded_file.name}' detectado com pouco texto ({len(texto_sem_tags)} chars). Ativando OCR...")
            texto_ocr, erro_ocr = ocr_via_gemini(uploaded_file, api_keys)
            if texto_ocr:
                st.success(f"✅ OCR bem-sucedido para '{uploaded_file.name}'!")
                return texto_ocr
            else:
                st.error(f"❌ Falha no OCR de '{uploaded_file.name}'. Detalhes: {erro_ocr}")
                return raw_text

        return raw_text

    except Exception as e:
        st.error(f"Erro leitura: {str(e)}")
        return ""

# ----------------- 9. UI PRINCIPAL -----------------
st.title("💊 Gráfica x Arte")

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

    if not keys_validas:
        st.error("Erro Crítico: Nenhuma API Key encontrada no secrets."); st.stop()

    if f1 and f2:
        secoes_alvo = SECOES_PACIENTE

        with st.spinner("Analisando arquivos individualmente (Texto ou OCR)..."):
            t_anvisa = extract_text_smart(f1, api_keys=keys_validas)
            t_mkt = extract_text_smart(f2, api_keys=keys_validas)

            if not t_anvisa or len(re.sub(r'<[^>]+>', '', t_anvisa).strip()) < 20:
                st.error(f"ERRO: Conteúdo do arquivo GRÁFICA insuficiente para análise."); st.stop()
            if not t_mkt or len(re.sub(r'<[^>]+>', '', t_mkt).strip()) < 20:
                st.error(f"ERRO: Conteúdo do arquivo ARTE insuficiente para análise."); st.stop()

            prompt = f"""
            Você é um Extrator de Dados Farmacêuticos ULTRA-RIGOROSO (ROBÔ DE CÓPIA PERFEITA).
            
            INPUT TEXTO 1 (REF - GRÁFICA): {t_anvisa[:180000]}
            INPUT TEXTO 2 (MKT - ARTE): {t_mkt[:180000]}
            
            REGRAS ABSOLUTAS - NÃO NEGOCIÁVEIS:
            1. COPIE o texto PALAVRA POR PALAVRA, CARACTERE POR CARACTERE exatamente como está nos inputs.
            2. PROIBIDO inventar, corrigir, "melhorar" ou alterar QUALQUER palavra.
            3. PROIBIDO traduzir termos.
            4. PRESERVE TODA a formatação <b> e <i> dos textos originais.
            5. MANTENHA todos os hífens, acentos e pontuação EXATAMENTE como aparecem.
            6. EXTRAIA TODO o conteúdo de cada seção - NÃO CORTE o texto no meio, NÃO omita palavras.
            7. Se não encontrar a data de aprovação da Anvisa, retorne "N/A" nos campos de data.
            
            LISTA DE SEÇÕES ESPERADAS: {secoes_alvo}
            
            SAÍDA JSON:
            {{"data_anvisa_ref": "...", "data_anvisa_mkt": "...", "secoes": [{{"titulo": "...", "texto_anvisa": "...", "texto_mkt": "..."}}]}}
            """

            response = None
            sucesso = False
            log_erros = []

            for idx_key, key in enumerate(keys_validas):
                if sucesso: break

                genai.configure(api_key=key)

                for modelo in MODELOS_PARA_TENTAR:
                    try:
                        model = genai.GenerativeModel(modelo, generation_config={"response_mime_type": "application/json", "temperature": 0.0})
                        response = model.generate_content(prompt)
                        sucesso = True
                        break 
                    except Exception as e:
                        erro_msg = str(e)
                        log_erros.append(f"Key {idx_key+1} | {modelo}: {erro_msg}")
                        if "429" in erro_msg or "quota" in erro_msg.lower():
                            time.sleep(3)
                        else:
                            time.sleep(0.5)
                        continue

            if not sucesso:
                st.error("❌ Falha Total na Análise."); st.code("\n".join(log_erros)); st.stop()

            try:
                resultado = json.loads(response.text)

                data_ref = resultado.get("data_anvisa_ref") or "N/A"
                data_mkt = resultado.get("data_anvisa_mkt") or "N/A"

                dados_secoes = resultado.get("secoes") or []

                secoes_finais = []
                divs_count = 0

                for item in dados_secoes:
                    titulo = (item.get('titulo') or '').strip()
                    txt_ref = (item.get('texto_anvisa') or "").strip()
                    txt_mkt = (item.get('texto_mkt') or "").strip()

                    titulo_upper = titulo.upper()
                    eh_blindada = any(b in titulo_upper for b in SECOES_SEM_COMPARACAO)

                    # Não sobrescrever o texto da seção: usamos safe rules apenas para CABEÇALHO se necessário
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

                        novo_ref = safe_extract_header(t_anvisa, secoes_alvo)
                        if novo_ref and (not txt_ref or len(novo_ref) < len(txt_ref) or len(txt_ref) < 50):
                            txt_ref = novo_ref
                        novo_mkt = safe_extract_header(t_mkt, secoes_alvo)
                        if novo_mkt and (not txt_mkt or len(novo_mkt) < len(txt_mkt) or len(txt_mkt) < 50):
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
                        # comparação robusta: passar textos originais (gera diff internamente com limpeza)
                        html_ref, html_mkt, teve_diff = gerar_diff_html(txt_ref, txt_mkt)
                        status = "DIVERGENTE" if teve_diff else "CONFORME"
                        if teve_diff:
                            divs_count += 1

                    secoes_finais.append({"titulo": titulo, "texto_anvisa": html_ref, "texto_mkt": html_mkt, "status": status})

                # Exibição do resumo e seções
                st.markdown("### 📊 Resumo")
                c1, c2, c3 = st.columns(3)
                c1.metric("Data Ref", data_ref)
                c2.metric("Data MKT", data_mkt, delta="Igual" if data_ref == data_mkt else "Diferente")
                c3.metric("Seções", len(secoes_finais))

                sub1, sub2 = st.columns(2)
                sub1.info(f"✅ Conformes: {len(secoes_finais) - div_count if (div_count:=divs_count) or True else 0}")
                if divs_count > 0: sub2.warning(f"⚠️ Divergentes: {divs_count}")
                else: sub2.success("✨ Divergências: 0")

                st.divider()

                for item in secoes_finais:
                    status = item['status']
                    titulo = item['titulo']
                    if "DIZERES LEGAIS" in titulo.upper(): icon, css, aberto = "⚖️", "border-info", True
                    elif any(b in titulo.upper() for b in SECOES_SEM_COMPARACAO): icon, css, aberto = "🔒", "border-ok", False
                    elif status == "CONFORME": icon, css, aberto = "✅", "border-ok", False
                    else: icon, css, aberto = "⚠️", "border-warn", True

                    with st.expander(f"{icon} {titulo}", expanded=aberto):
                        ce, cd = st.columns(2)
                        with ce: st.caption("Gráfica"); st.markdown(f'<div class="texto-box {css}">{item["texto_anvisa"]}</div>', unsafe_allow_html=True)
                        with cd: st.caption("Arte"); st.markdown(f'<div class="texto-box {css}">{item["texto_mkt"]}</div>', unsafe_allow_html=True)

            except Exception as e:
                st.error(f"Erro ao processar JSON: {e}")
                try: st.code(response.text)
                except: pass
    else:
        st.warning("Adicione os arquivos.")
